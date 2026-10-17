#!/usr/bin/env python3
"""Usage: merge_rows.py [pr-data.csv] [rows glob] [output csv]

Runs once in the aggregate job: merges every tool's flaky_rows/<tool>.csv and fills
In pr-data / Project URL / SHA / Module Path / Category / Status / PR Link / Notes
from pr-data.csv.
"""
import csv, glob, io, sys
from collections import defaultdict

from csv_common import FINAL_COLUMNS, TEST_COL, norm_module, norm_test, norm_url

pr_path = sys.argv[1] if len(sys.argv) > 1 else "pr-data.csv"
rows_glob = sys.argv[2] if len(sys.argv) > 2 else "artifacts/rows-*/*.csv"
out_path = sys.argv[3] if len(sys.argv) > 3 else "flaky_tests.csv"

# --- load pr-data.csv (utf-8-sig so a BOM can't corrupt the first header) ---
pr = defaultdict(list)   # (normalised project url, normalised test) -> pr-data rows
pr_loaded = False
try:
    with open(pr_path, newline="", encoding="utf-8-sig", errors="ignore") as fh:
        for r in csv.DictReader(fh):
            r = {(k or "").strip(): (v or "").strip() for k, v in r.items() if k}
            tcol = next((k for k in r if k.startswith("Fully-Qualified Test")), None)
            if tcol and r.get("Project URL"):
                pr[(norm_url(r["Project URL"]), norm_test(r[tcol]))].append(r)
    pr_loaded = bool(pr)
except Exception as e:
    print(f"::error::could not read {pr_path}: {e}")
if not pr_loaded:
    print(f"::warning::{pr_path} missing or empty - 'In pr-data' will be 'Unknown'")
else:
    print(f"pr-data: {sum(len(v) for v in pr.values())} rows, {len(pr)} distinct (project, test) keys")


def best(cands, sha, module):
    return max(cands, key=lambda r: (r.get("SHA Detected", "") == sha,
                                     norm_module(r.get("Module Path", "")) == norm_module(module),
                                     bool(r.get("PR Link")), bool(r.get("Status"))))


tool_order = {"idflakies": 0, "nondex": 1, "flakesync": 2}
seen, rows = set(), []
files = sorted(glob.glob(rows_glob))
print(f"{len(files)} per-job row files found")
matched = 0
for p in files:
    with open(p, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            test = norm_test(r.get(TEST_COL, ""))
            if not test:
                continue
            url, sha, mod = r.get("Project URL", ""), r.get("SHA Detected", ""), r.get("Module Path", "")
            cands = pr.get((norm_url(url), test))
            if cands:
                m = best(cands, sha, mod)
                matched += 1
                # Project URL ... Notes all come from the pr-data row (fall back to the run's
                # value only if pr-data leaves a field blank).
                row = [r.get("Tool", ""), r.get("Failure rate", "") or "n/a", "Yes",
                       m.get("Project URL") or url, m.get("SHA Detected") or sha,
                       m.get("Module Path") or mod, test,
                       m.get("Category", ""), m.get("Status", ""),
                       m.get("PR Link", ""), m.get("Notes", "")]
            else:
                row = [r.get("Tool", ""), r.get("Failure rate", "") or "n/a",
                       "No" if pr_loaded else "Unknown", url, sha, mod, test, "", "", "", ""]
            key = tuple(row)
            if key not in seen:
                seen.add(key)
                rows.append(row)

rows.sort(key=lambda r: (tool_order.get(r[0], 9), r[3].lower(), r[6]))
with open(out_path, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(FINAL_COLUMNS)
    w.writerows(rows)
print(f"{len(rows)} rows written to {out_path} ({matched} matched in pr-data)")
