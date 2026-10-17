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

from csv_common import RUN_COLUMNS, norm_test

if len(sys.argv) < 5:
    sys.exit(__doc__)
tool, repo_url, sha, module_path = sys.argv[1:5]
if tool not in ("idflakies", "nondex", "flakesync"):
    sys.exit(f"unknown tool {tool!r} (expected idflakies, nondex or flakesync)")

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
    """test (a.b.C.m) -> {"delaylocs": (failed, ran), "main": (failed, ran)}, from the Maven log.

    run-detector writes '=== flakesync: <Class#method> (<goal>) ===' before each goal.
    delaylocs = the delay-injected runs; main = the plain run with no delays (the baseline).
    Inside a section every Surefire result line for the test's own class is a run, and it
    failed if Failures+Errors > 0.
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
        if cur_goal not in ("main", "delaylocs") or not cur_test:
            continue
        m = SUREFIRE.search(line.strip())
        if m and m.group(5) == cls:
            ran, failed = int(m.group(1)) - int(m.group(4)), int(m.group(2)) + int(m.group(3))
            if ran > 0:
                rec = out.setdefault(norm_test(cur_test), {"delaylocs": (0, 0), "main": (0, 0)})
                f, n = rec[cur_goal]
                rec[cur_goal] = (f + min(failed, ran), n + ran)
    return out


fails = defaultdict(set)   # test -> run ids it failed in
seen = defaultdict(set)    # test -> run ids it ran in (iDFlakies)
runs = set()               # all NonDex run folders

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
    # Failure rate = failed rounds / rounds the test ran in. Only the detection-round files
    # count (.dtfixingtools/detection-results/<config>/round<N>.json). Everything else under
    # .dtfixingtools (minimized/, fixer/, re-runs of suspected tests) also contains per-test
    # results, but counting those inflates the denominator well beyond the configured rounds.
    cand = [p for p in files_under(".dtfixingtools")
            if os.path.basename(p) != "flaky-lists.json"
            and (os.path.basename(p).endswith(".json") or "." not in os.path.basename(p))]
    norm_p = lambda p: p.replace("\\", "/")
    rounds = [p for p in cand if "/detection-results/" in norm_p(p)]
    if not rounds:   # layout differs from the documented one: drop only the known extra folders
        rounds = [p for p in cand if not any(f"/{d}/" in norm_p(p) for d in ("minimized", "fixer"))]
        print(f"warning: no detection-results files found, counting {len(rounds)} result files")
    else:
        print(f"iDFlakies: counting {len(rounds)} detection-round files (of {len(cand)} json files)")
    for p in rounds:
        try:
            data = json.load(open(p, errors="ignore"))
        except Exception:
            continue
        for name, result in result_entries(data):
            r = result.upper()
            if r in ("SKIPPED", "SKIP"):
                continue
            seen[name].add(p)
            if r in ("FAILURE", "ERROR", "FAIL"):
                fails[name].add(p)

elif tool == "nondex":
    names = set()
    for p in files_under(".nondex"):
        d, b = os.path.dirname(p), os.path.basename(p)
        if b in ("config", "failures"): runs.add(d)      # one folder per NonDex run
        if p.endswith(SKIP_EXT): continue
        for line in lines_of(p):
            n = clean(line)
            if n:
                names.add(n)
                fails[n].add(d)

else:  # flakesync
    names = set()
    log_path = os.environ.get("TOOL_LOG") or next(
        (p for p in files_under("logs") if os.path.basename(p) == "flakesync_log.txt"), None)
    flake_rates = flakesync_rates(log_path)
    # Candidate = at least one delay-injected (delaylocs) run of the test FAILED. It is only
    # kept (see the filter below) if it also passed in the normal, no-delay run.
    names = {t for t, r in flake_rates.items() if r["delaylocs"][0] >= 1}
    # Failure-rate cell for FlakeSync = how many delay locations FlakeSync found for the test
    # (non-blank lines of <test>-Locations.txt); "n/a" when that file is missing.
    loc_counts = {}
    for p in files_under(".flakesync"):
        if p.endswith("Locations.txt"):
            n = norm_test(os.path.basename(p).replace("Locations.txt", ""))
            if n:
                loc_counts[n] = sum(1 for l in lines_of(p) if l.strip())

# ---- Keep only tests that are demonstrably flaky: they must have failed AND passed ----
dropped = {"failed in every run": 0, "never failed": 0, "no pass/fail evidence": 0}


def is_flaky(t):
    if tool == "idflakies":
        if not seen.get(t):
            return True            # no round data: rely on iDFlakies' own flaky-lists.json verdict
        f, n = len(fails[t]), len(seen[t])
    elif tool == "nondex":
        if not runs:
            dropped["no pass/fail evidence"] += 1
            return False
        f, n = len(fails[t] & runs), len(runs)
    else:  # flakesync: failed with delays, and passed in the normal (no-delay) run
        r = flake_rates.get(t)
        if not r or r["main"][1] == 0:
            dropped["no pass/fail evidence"] += 1   # no baseline run to show it can pass
            return False
        if r["main"][0] > 0:
            dropped["failed in every run"] += 1     # fails without delays too
            return False
        return True
    if f == 0:
        dropped["never failed"] += 1
    elif f == n:
        dropped["failed in every run"] += 1
    return 0 < f < n


all_candidates = len(names)
names = {t for t in names if is_flaky(t)}
print(f"kept {len(names)} of {all_candidates} candidates; dropped: " +
      ", ".join(f"{v} {k}" for k, v in dropped.items() if v))

out_dir = os.path.join(os.environ.get("GITHUB_WORKSPACE", "."), "flaky_rows")
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, f"{tool}.csv")
with open(out, "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(RUN_COLUMNS)
    for t in sorted(names):
        if tool == "idflakies" and seen.get(t):
            rate = f"{len(fails[t])}/{len(seen[t])}"
        elif tool == "nondex" and runs:
            rate = f"{len(fails[t] & runs)}/{len(runs)}"
        elif tool == "flakesync" and t in loc_counts:
            rate = str(loc_counts[t])   # number of locations, not a pass/fail ratio
        else:
            rate = "n/a"   # no run counts / Locations file found
        w.writerow([tool, rate, repo_url, sha, module_path, t])
print(f"tool={tool} runs_seen={len(runs)} tests={len(names)} -> {out}")
