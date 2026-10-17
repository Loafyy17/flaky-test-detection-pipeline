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
    # Failure rate: look at every per-round result file (.json, or extension-less)
    for p in files_under(".dtfixingtools"):
        b = os.path.basename(p)
        if b == "flaky-lists.json" or not (b.endswith(".json") or "." not in b):
            continue
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
    # Locations.txt: first line is the injected delay (ms), the rest are the code locations
    # where a delay was placed. It is rewritten by every delaylocs run, so it only reflects
    # the last one, and it says nothing about failures. Detected therefore requires BOTH
    # at least one delay-injected run that failed (from the log) AND at least one location.
    for p in files_under(".flakesync"):
        if p.endswith("Locations.txt"):
            n = norm_test(os.path.basename(p).replace("Locations.txt", ""))
            lines = [l for l in lines_of(p) if l.strip()]
            n_locs = max(len(lines) - 1, 0)          # drop the delay header line
            if n and n_locs > 0 and flake_rates.get(n, (0, 0))[0] > 0:
                names.add(n)
                print(f"flakesync detected: {n} failed {flake_rates[n][0]}/{flake_rates[n][1]} delay runs, {n_locs} locations")

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
        elif tool == "flakesync" and flake_rates.get(t):
            rate = f"{flake_rates[t][0]}/{flake_rates[t][1]}"
        else:
            rate = "n/a"   # no run counts found in the log
        w.writerow([tool, rate, repo_url, sha, module_path, t])
print(f"tool={tool} runs_seen={len(runs)} tests={len(names)} -> {out}")
