#!/usr/bin/env python3
"""Compute FlakeSync failure rates from already-downloaded Maven logs (no workflow rerun).

Usage:
  python3 fail_rates_from_logs.py <logs_dir> [--csv flaky_tests.csv] [--out flakesync_failure_rates.csv] [--overwrite] [--in-place]

<logs_dir> is the unzipped `test_logs` artifact (any depth); every
flakesync_logs_<repo>_<sha>/[<module>/]logs/flakesync_log.txt inside it is read.

For each test the log has two sections (written by run-detector):
  (main)       the plain concurrentfind run  -> baseline: does the test fail with no delay?
  (delaylocs)  the delay-injected runs       -> every Surefire result line for the test's class
                                                is one run; it failed if Failures+Errors > 0.

Output 1 (--out): one row per test with the delay rate, the baseline and a verdict.
Output 2 (--csv): a copy of flaky_tests.csv, '<name>_with_rates.csv', where FlakeSync rows
                  with 'n/a' get their rate filled in (matched on SHA + test name).
                  A summary says why any row was not filled. --overwrite also replaces rates
                  that are already present. --in-place rewrites the --csv file itself instead of
                  writing '<name>_with_rates.csv' (used by the aggregate job).
"""
import argparse, csv, os, re, sys
from collections import defaultdict

MARKER = re.compile(r"^=== flakesync: (\S+?)(?: \((\w+)\))? ===\s*$")
SUREFIRE = re.compile(r"Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+).*? in (\S+)\s*$")
DIR = re.compile(r"^flakesync_logs_(.+)_([0-9a-f]{40})$")
TEST_COL = "Fully-Qualified Test Name (packageName.ClassName.methodName)"


def norm_test(n):
    return (n or "").strip().replace("#", ".").rstrip("-. ")


def parse_log(path):
    """-> {test: {'main': [fail, runs], 'delaylocs': [fail, runs]}}"""
    out = defaultdict(lambda: {"main": [0, 0], "delaylocs": [0, 0]})
    cur = goal = cls = None
    with open(path, errors="ignore") as fh:
        for line in fh:
            s = line.strip()
            m = MARKER.match(s)
            if m:
                cur, goal = m.group(1), m.group(2)
                cls = cur.split("#")[0]
                continue
            if goal not in ("main", "delaylocs"):
                continue
            m = SUREFIRE.search(s)
            if m and m.group(5) == cls:
                ran = int(m.group(1)) - int(m.group(4))
                if ran > 0:
                    failed = min(int(m.group(2)) + int(m.group(3)), ran)
                    rec = out[norm_test(cur)][goal]
                    rec[0] += failed
                    rec[1] += ran
    return out


def find_logs(root):
    for dirpath, _, files in os.walk(root):
        if "flakesync_log.txt" not in files or "__MACOSX" in dirpath:
            continue
        parts = dirpath.replace("\\", "/").split("/")
        for i, comp in enumerate(parts):
            m = DIR.match(comp)
            if m:
                module = "/".join(p for p in parts[i + 1:] if p != "logs") or "."
                yield os.path.join(dirpath, "flakesync_log.txt"), m.group(1), m.group(2), module
                break


def verdict(main, delay):
    if delay[1] == 0:
        return "no delay runs in log"
    if delay[0] == 0:
        return "no failure with delays"
    if main[1] == 0:
        return "fails with delays (no baseline)"
    return "fails without delays too" if main[0] > 0 else "delay-induced"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs_dir")
    ap.add_argument("--csv")
    ap.add_argument("--out", default="flakesync_failure_rates.csv")
    ap.add_argument("--in-place", action="store_true", help="update the --csv file itself")
    ap.add_argument("--overwrite", action="store_true", help="replace Failure rate values that are already set")
    a = ap.parse_args()

    rows, by_key, seen_tests, seen_shas = [], {}, {}, set()
    for path, repo, sha, module in find_logs(a.logs_dir):
        for test, r in sorted(parse_log(path).items()):
            d, b = r["delaylocs"], r["main"]
            rate = f"{d[0]}/{d[1]}" if d[1] else "n/a"
            rows.append([repo, sha, module, test, rate,
                         f"{b[0]}/{b[1]}" if b[1] else "n/a", verdict(b, d)])
            seen_shas.add(sha)
            seen_tests.setdefault((sha, test), []).append(module)
            if d[1]:
                by_key.setdefault((sha, test), []).append((module, rate))
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Repo", "SHA", "Module Path", TEST_COL, "Delay failure rate",
                    "Normal-run failures (no delay)", "Verdict"])
        w.writerows(rows)
    have = sum(1 for r in rows if r[4] != "n/a")
    print(f"{len(rows)} tests found in logs, {have} with delay-run counts -> {a.out}")
    kinds = defaultdict(int)
    for r in rows:
        kinds[r[6]] += 1
    for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"  {v:5d}  {k}")

    if a.csv:
        out_csv = a.csv if a.in_place else re.sub(r"\.csv$", "", os.path.basename(a.csv)) + "_with_rates.csv"   # default: current directory
        with open(a.csv, newline="", encoding="utf-8-sig") as fh:
            rd = csv.DictReader(fh)
            fields = rd.fieldnames
            data = list(rd)

        def resolve_sha(x):   # the CSV may hold an abbreviated SHA
            x = (x or "").strip().lower()
            if x in seen_shas:
                return x
            if len(x) >= 7:
                hits = [h for h in seen_shas if h.startswith(x)]
                if len(hits) == 1:
                    return hits[0]
            return None

        stats = defaultdict(list)
        total = 0
        for r in data:
            if (r.get("Tool") or "").strip().lower() != "flakesync":
                continue
            total += 1
            raw_sha, test = (r.get("SHA Detected") or "").strip(), norm_test(r.get(TEST_COL, ""))
            have = (r.get("Failure rate") or "").strip()
            sha = resolve_sha(raw_sha)
            if have not in ("", "n/a") and not a.overwrite:
                stats["already has a rate (use --overwrite to replace)"].append((raw_sha, test, have))
            elif sha is None:
                stats["SHA not found in these logs (CSV is from a different run?)"].append((raw_sha, test, ""))
            elif (sha, test) not in seen_tests:
                stats["SHA is in the logs but the test name is not"].append((raw_sha, test, ""))
            elif (sha, test) not in by_key:
                stats["test is in the logs but has no delay-run results"].append((raw_sha, test, ""))
            else:
                cands = by_key[(sha, test)]
                pick = [c for c in cands if c[0] == (r.get("Module Path") or ".")] or cands
                r["Failure rate"] = pick[0][1]
                stats["FILLED"].append((raw_sha, test, pick[0][1]))
        with open(out_csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(data)
        print(f"\n{a.csv}: {len(stats['FILLED'])}/{total} FlakeSync rows filled -> {out_csv}")
        for k, v in sorted(stats.items(), key=lambda kv: (kv[0] != "FILLED", -len(kv[1]))):
            if k == "FILLED":
                continue
            print(f"  {len(v):4d}  {k}")
            for sh, t, h in v[:3]:
                print(f"        e.g. sha={sh[:10]} test={t}" + (f" rate={h}" if h else ""))
            if k.startswith("SHA is in"):
                full = resolve_sha(v[0][0])
                print("        names in the logs for that SHA: " + ", ".join(sorted(t for (h, t) in seen_tests if h == full)[:2]))


if __name__ == "__main__":
    main()
