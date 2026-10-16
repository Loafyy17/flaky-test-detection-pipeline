#!/usr/bin/env python3
"""Usage: build_rows.py <tool> <repo_url> <sha> <module_path>
File selection and name cleaning mirror aggregate_results.py, which is known to work."""
import csv, io, json, os, sys, urllib.request
from collections import defaultdict

tool, repo_url, sha, module_path = sys.argv[1:5]
PR_DATA = "https://raw.githubusercontent.com/TestingResearchIllinois/idoft/main/pr-data.csv"
COLUMNS = ["Tool", "Failure rate", "In pr-data", "Project URL", "SHA Detected",
           "Module Path", "Fully-Qualified Test Name (packageName.ClassName.methodName)",
           "Category", "Status", "PR Link"]
SKIP_EXT = (".html", ".keep", ".png", ".jpg", ".class", ".xml", ".json")

def norm(u): return u.strip().rstrip("/").removesuffix(".git").lower()

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

# --- pr-data lookup (never fatal) ---
pr = {}
try:
    text = urllib.request.urlopen(PR_DATA, timeout=60).read().decode("utf-8", "ignore")
    for r in csv.DictReader(io.StringIO(text)):
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        tcol = next((k for k in r if k.startswith("Fully-Qualified Test")), None)
        if tcol:
            pr.setdefault((norm(r.get("Project URL", "")), r[tcol]), r)
except Exception as e:
    print("pr-data lookup failed:", e)

fails = defaultdict(set)   # test -> set of run ids it failed in
runs = set()               # all run ids seen
rates = {}                 # test -> (failures, rounds) when known directly

if tool == "idflakies":
    # 1) find flaky tests, using the same logic as the old parser
    flaky = set()
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
                            if n: flaky.add(n)
            except Exception as e:
                print("bad json", p, e)
        elif b in ("failing-tests", "failing"):
            for line in lines_of(p):
                n = clean(line)
                if n: flaky.add(n)
    # 2) count failures per round (best effort; falls back to n/a)
    for p in files_under(".dtfixingtools"):
        b = os.path.basename(p)
        if "detection-results" in p and b.startswith("round") and b.endswith(".json"):
            runs.add(p)
            try:
                res = json.load(open(p, errors="ignore")).get("results") or {}
                for name, v in res.items():
                    r = v.get("result", "") if isinstance(v, dict) else str(v)
                    if str(r).upper() in ("FAILURE", "ERROR"):
                        fails[name].add(p)
            except Exception as e:
                print("round parse failed", p, e)
    names = flaky

elif tool == "nondex":
    names = set()
    for p in files_under(".nondex"):
        runs.add(os.path.dirname(p))
        if p.endswith(SKIP_EXT): continue
        for line in lines_of(p):
            n = clean(line)
            if n:
                names.add(n)
                fails[n].add(os.path.dirname(p))

elif tool == "flakesync":
    names = set()
    for p in files_under(".flakesync"):
        if p.endswith("ResultMethods.txt"):
            names.add(os.path.basename(p).replace("ResultMethods.txt", "").rstrip("."))

else:
    names = set()

out_dir = os.path.join(os.environ.get("GITHUB_WORKSPACE", "."), "flaky_rows")
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, f"{tool}.csv")
with open(out, "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(COLUMNS)
    for t in sorted(names):
        m = pr.get((norm(repo_url), t))
        rate = f"{len(fails[t])}/{len(runs)}" if tool != "flakesync" and runs and fails.get(t) else "n/a"
        w.writerow([tool, rate, "Yes" if m else "No", repo_url, sha, module_path, t,
                    m.get("Category", "") if m else "", m.get("Status", "") if m else "",
                    m.get("PR Link", "") if m else ""])
print(f"tool={tool} runs_seen={len(runs)} tests={len(names)} -> {out}")
