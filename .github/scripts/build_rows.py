#!/usr/bin/env python3
"""Usage: build_rows.py <tool> <repo_url> <sha> <module_path>"""
import csv, io, json, os, sys, urllib.request
from collections import defaultdict

tool, repo_url, sha, module_path = sys.argv[1:5]
PR_DATA = "https://raw.githubusercontent.com/TestingResearchIllinois/idoft/main/pr-data.csv"
COLUMNS = ["Tool", "Failure rate", "In pr-data", "Project URL", "SHA Detected",
           "Module Path", "Fully-Qualified Test Name (packageName.ClassName.methodName)",
           "Category", "Status", "PR Link"]

def norm(u): return u.strip().rstrip("/").removesuffix(".git").lower()

# --- pr-data lookup (never fatal: if the download fails, we still write rows) ---
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

def walk(dirname):
    for root, _, files in os.walk("."):
        if os.path.basename(root) == dirname or f"/{dirname}/" in root + "/":
            for f in files:
                yield os.path.join(root, f)

stats = defaultdict(lambda: [0, 0])   # test -> [failures, rounds_seen]

if tool == "idflakies":
    # one JSON per round under .dtfixingtools/detection-results/
    for p in walk(".dtfixingtools"):
        if "detection-results" in p and os.path.basename(p).startswith("round") and p.endswith(".json"):
            try:
                data = json.load(open(p))
                for name, res in (data.get("results") or {}).items():
                    stats[name][1] += 1
                    if str(res.get("result", "")).upper() in ("FAILURE", "ERROR"):
                        stats[name][0] += 1
            except Exception as e:
                print("skip", p, e)
    flaky = set()
    for p in walk(".dtfixingtools"):
        if os.path.basename(p) == "flaky-lists.json":
            try:
                for lst in json.load(open(p)).values():
                    for t in lst:
                        flaky.add(t if isinstance(t, str) else t.get("name", ""))
            except Exception: pass
    stats = {t: v for t, v in stats.items() if t in flaky}

elif tool == "nondex":
    run_dirs = set()
    for p in walk(".nondex"):
        d = os.path.dirname(p)
        if os.path.basename(p) == "config":
            run_dirs.add(d)
    total = len(run_dirs)
    for p in walk(".nondex"):
        if os.path.basename(p) == "failures":
            for line in open(p, errors="ignore"):
                t = line.strip()
                if t and " " not in t and t.count(".") >= 2:
                    stats[t][0] += 1
    for t in stats: stats[t][1] = total

elif tool == "flakesync":
    for p in walk(".flakesync"):
        if p.endswith("ResultMethods.txt"):
            t = os.path.basename(p).replace("ResultMethods.txt", "").rstrip(".")
            stats[t] = [None, None]   # FlakeSync has no per-run failure rate

os.makedirs(os.path.join(os.environ.get("GITHUB_WORKSPACE", "."), "flaky_rows"), exist_ok=True)
out = os.path.join(os.environ.get("GITHUB_WORKSPACE", "."), "flaky_rows", f"{tool}.csv")
with open(out, "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(COLUMNS)
    for t, (f, n) in sorted(stats.items()):
        m = pr.get((norm(repo_url), t))
        rate = f"{f}/{n}" if f is not None and n else "n/a"
        w.writerow([tool, rate, "Yes" if m else "No", repo_url, sha, module_path, t,
                    m.get("Category", "") if m else "", m.get("Status", "") if m else "",
                    m.get("PR Link", "") if m else ""])
print(f"wrote {len(stats)} rows to {out}")
