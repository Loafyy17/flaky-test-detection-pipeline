#!/usr/bin/env python3
"""Usage: build_rows.py <tool> <repo_url> <sha> <module_path>

Runs inside each detector job. Collects the flaky tests that tool found plus a
failure rate (failed runs / total runs) and writes flaky_rows/<tool>.csv.
The pr-data.csv lookup (In pr-data, Category, Status, PR Link, Notes) is done once,
later, by merge_rows.py in the aggregate job.

File selection and name cleaning mirror aggregate_results.py, which is known to work.
"""
import csv, json, os, sys
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
    for p in files_under(".flakesync"):
        if p.endswith("ResultMethods.txt"):
            n = norm_test(os.path.basename(p).replace("ResultMethods.txt", ""))
            if n: names.add(n)

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
        else:
            rate = "n/a"   # FlakeSync reports a verdict, not pass/fail counts
        w.writerow([tool, rate, repo_url, sha, module_path, t])
print(f"tool={tool} runs_seen={len(runs)} tests={len(names)} -> {out}")
