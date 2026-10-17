#!/usr/bin/env python3
"""Usage: build_rows.py <tool> <repo_url> <sha> <module_path>

Runs inside each detector job. Collects the flaky tests that tool found plus a
failure rate (failed runs / total runs) and writes flaky_rows/<tool>.csv.
The pr-data.csv lookup (In pr-data, Category, Status, PR Link, Notes) is done once,
later, by merge_rows.py in the aggregate job.

File selection and name cleaning mirror aggregate_results.py, which is known to work.
"""
import csv, json, os, re, sys
from collections import defaultdict

from csv_common import RUN_COLUMNS_V2 as RUN_COLUMNS, norm_test

if len(sys.argv) < 5:
    sys.exit(__doc__)
tool, repo_url, sha, module_path = sys.argv[1:5]
if tool not in ("idflakies", "nondex", "flakesync"):
    sys.exit(f"unknown tool {tool!r} (expected idflakies, nondex or flakesync)")

# NonDex/iDFlakies also report tests that fail in EVERY shuffled/random run while passing in the
# clean/original run (they depend on a specific order). Set True to drop those (N/N) rows.
EXCLUDE_ALWAYS_FAILING = False

SKIP_EXT = (".html", ".keep", ".png", ".jpg", ".class", ".xml", ".json")


def clean(raw):
    """Same rules as clean_and_validate_test_name in aggregate_results.py."""
    if not raw or not isinstance(raw, str): return None
    line = raw.strip()
    if (not line or line[0] in "#<[" or line.startswith(("at ", "INFO", "WARN", "ERROR",
            "Tests run:", "Test set:")) or "InaccessibleObjectException" in line
            or "LogFactory" in line):
        return None
    if " -- " in line: line = line.split(" -- ")[0].strip()
    if " <<<" in line: line = line.split(" <<<")[0].strip()
    if "(" in line and ")" in line: line = line.split("(")[0].strip()
    if " " in line: line = line.split()[0].strip()
    # Exception / framework class names (e.g. java.lang.AssertionError) are not tests
    if line.startswith(("java.", "javax.", "jdk.", "sun.", "org.junit.", "junit.", "org.opentest4j.")):
        return None
    last = line.split(".")[-1]
    if last[:1].isupper() and last.endswith(("Error", "Exception", "Failure")):
        return None
    parts = line.split(".")
    if len(parts) >= 3 and all(p.isidentifier() for p in parts):
        return line
    return None


def files_under(dirname):
    for root, _, files in os.walk("."):
        if f"/{dirname}/" in root + "/":
            for f in files:
                yield os.path.join(root, f)


def lines_of(path):
    try:
        with open(path, errors="ignore") as fh:
            for line in fh:
                yield line
    except Exception as e:
        print("skip", path, e)


def result_entries(obj):
    """Yield (test, result) for any dict shaped like {"pkg.Class.method": {"result": "PASS"}}."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, dict) and "result" in v and isinstance(k, str):
                yield k, str(v["result"])
            else:
                yield from result_entries(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from result_entries(v)


MARKER = re.compile(r"^=== flakesync: (\S+?)(?: \((\w+)\))? ===\s*$")
# Surefire per-class result line, e.g.
#   Tests run: 1, Failures: 1, Errors: 0, Skipped: 0, Time elapsed: 0.1 s <<< FAILURE! - in a.b.C
SUREFIRE = re.compile(r"Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+).*? in (\S+)\s*$")


def flakesync_rates(log_path):
    """test (a.b.C.m) -> (failed_runs, total_runs), read from the Maven log.

    run-detector writes '=== flakesync: <Class#method> (<goal>) ===' before each goal.
    Only the delaylocs section counts (those are the delay-injected runs); inside it every
    Surefire result line for the test's own class is a run, and it failed if Failures+Errors > 0.
    """
    out = {}
    if not log_path or not os.path.isfile(log_path):
        return out
    cur_test, cur_goal, cls = None, None, None
    for line in lines_of(log_path):
        m = MARKER.match(line.strip())
        if m:
            cur_test, cur_goal = m.group(1), m.group(2)
            cls = cur_test.split("#")[0]
            continue
        if cur_goal != "delaylocs" or not cur_test:
            continue
        m = SUREFIRE.search(line.strip())
        if m and m.group(5) == cls:
            ran, failed = int(m.group(1)) - int(m.group(4)), int(m.group(2)) + int(m.group(3))
            if ran > 0:
                f, n = out.get(norm_test(cur_test), (0, 0))
                out[norm_test(cur_test)] = (f + min(failed, ran), n + ran)
    return out


fails = defaultdict(set)   # test -> run ids it failed in
seen = defaultdict(set)    # test -> run ids it ran in (iDFlakies)
runs = set()               # NonDex run folders / iDFlakies detection round files

if tool == "idflakies":
    names = set()
    for p in files_under(".dtfixingtools"):
        b = os.path.basename(p)
        if b == "flaky-lists.json":
            try:
                data = json.load(open(p, errors="ignore"))
                if isinstance(data, dict):
                    for lst in data.values():
                        if not isinstance(lst, list): continue
                        for item in lst:
                            if isinstance(item, str):
                                n = clean(item)
                            elif isinstance(item, dict):
                                n = next((clean(item[k]) for k in ("testName", "test_name", "name")
                                          if isinstance(item.get(k), str)), None)
                            else:
                                n = None
                            if n: names.add(n)
            except Exception as e:
                print("bad json", p, e)
        elif b in ("failing-tests", "failing"):
            for line in lines_of(p):
                n = clean(line)
                if n: names.add(n)
    # Failure rate = failed rounds / detection rounds. Only the detector's own round files
    # count: detection-results/<detector>/roundN.json (-Ddt.randomize.rounds=10 -> 10 files).
    # Re-runs of the same tests (<detector>-confirmation, -verify, ..., original order)
    # live in sibling folders and must not inflate the denominator.
    def is_detection_round(path):
        parts = path.replace("\\", "/").split("/")
        if "detection-results" not in parts:
            return False
        rest = parts[parts.index("detection-results") + 1:]
        if len(rest) != 2 or not re.fullmatch(r"round\d+\.json", rest[1]):
            return False
        d = rest[0]
        return d.startswith("random") and not any(x in d for x in ("confirmation", "verify", "filter", "sampling"))

    # A round file does NOT list every test's result. It holds only the "dependent tests" of
    # that round: {"unfilteredTests": {"dts": [{"name", "intended": {"result"}, "revealed":
    # {"result"}}]}, ...}, i.e. tests whose result in this round differed from the original
    # order (intended = original-order result, revealed = this round's result). A test that is
    # not listed behaved as in the original order.
    round_files, orig_result, round_result = [], {}, defaultdict(dict)
    for p in sorted(files_under(".dtfixingtools")):
        if not is_detection_round(p):
            continue
        try:
            data = json.load(open(p, errors="ignore"))
        except Exception:
            continue
        round_files.append(p)
        dts = ((data.get("unfilteredTests") or {}).get("dts") or []) if isinstance(data, dict) else []
        for dt in dts:
            if not isinstance(dt, dict) or not isinstance(dt.get("name"), str):
                continue
            n = norm_test(dt["name"])
            orig_result.setdefault(n, str((dt.get("intended") or {}).get("result", "PASS")).upper())
            round_result[n][p] = str((dt.get("revealed") or {}).get("result", "")).upper()
    runs = set(round_files)
    BAD = ("FAILURE", "ERROR", "FAIL")
    for n in set(orig_result) | {norm_test(x) for x in names}:
        for p in round_files:
            res = round_result[n].get(p) or orig_result.get(n, "PASS")
            if res in BAD:
                fails[n].add(p)

elif tool == "nondex":
    # .nondex/<id>/ is one shuffled run; .nondex/clean_<id>/ is the run WITHOUT shuffling.
    # Only shuffled runs form the denominator, and a test that also fails in the clean run is
    # a plain failing test (not flaky), so it is dropped.
    names, clean_failed = set(), set()
    for p in files_under(".nondex"):
        d, b = os.path.dirname(p), os.path.basename(p)
        is_clean = os.path.basename(d).startswith("clean_")
        if b in ("config", "failures") and not is_clean:
            runs.add(d)                                    # one folder per shuffled run
        if p.endswith(SKIP_EXT): continue
        for line in lines_of(p):
            n = clean(line)
            if not n: continue
            if is_clean:
                if b == "failures": clean_failed.add(n)
            else:
                names.add(n)
                fails[n].add(d)
    names -= clean_failed

else:  # flakesync
    names = set()
    log_path = os.environ.get("TOOL_LOG") or next(
        (p for p in files_under("logs") if os.path.basename(p) == "flakesync_log.txt"), None)
    flake_rates = flakesync_rates(log_path)
    # Locations.txt: first line is the injected delay (ms), the rest are the code locations
    # where delays were injected (rewritten by every delaylocs run, so it reflects the last).
    # Failure rate for FlakeSync = number of those locations. A test is detected when it has
    # at least one location and no delay run in the log passed everywhere (if the log has no
    # parsable delay runs for the test, the locations alone decide).
    loc_counts = {}
    for p in files_under(".flakesync"):
        if p.endswith("Locations.txt"):
            n = norm_test(os.path.basename(p).replace("Locations.txt", ""))
            n_locs = max(sum(1 for l in lines_of(p) if l.strip()) - 1, 0)   # drop the delay line
            if not n or n_locs == 0:
                continue
            if n in flake_rates and flake_rates[n][0] == 0:
                continue          # delays were injected but no run ever failed
            names.add(n)
            loc_counts[n] = n_locs

out_dir = os.path.join(os.environ.get("GITHUB_WORKSPACE", "."), "flaky_rows")
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, f"{tool}.csv")
with open(out, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(RUN_COLUMNS)
    for t in sorted(names):
        if tool in ("idflakies", "nondex") and runs:
            f_cnt = len(fails.get(t, set()) & runs)
            if f_cnt == 0:
                continue          # never failed in a counted run: no evidence of flakiness
            if EXCLUDE_ALWAYS_FAILING and f_cnt == len(runs):
                continue
            rate = f"{f_cnt}/{len(runs)}"
        elif tool == "flakesync" and t in loc_counts:
            rate = str(loc_counts[t])   # number of locations, not a pass/fail ratio
        else:
            rate = "n/a"   # no run counts found in the log
        delay = ""
        if tool == "flakesync":   # delay-injected runs that failed / delay runs (8 sizes)
            delay = f"{flake_rates[t][0]}/{flake_rates[t][1]}" if t in flake_rates else "n/a"
        w.writerow([tool, rate, delay, repo_url, sha, module_path, t])
print(f"tool={tool} runs_seen={len(runs)} tests={len(names)} -> {out}")
