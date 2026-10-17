#!/usr/bin/env python3
"""Runs in the aggregate job, from the workspace root, after the artifacts are downloaded.

For every artifacts/<tool>-results-<repo>-<sha>/ folder (the same artifacts
aggregate_results.py already reads) it reads run_metadata.json and runs build_rows.py
inside that folder, writing collected_rows/<artifact>/flaky_rows/<tool>.csv.

This makes flaky_tests.csv independent of the per-job rows-* artifacts, so NonDex and
FlakeSync rows can't be lost if one job's rows upload is missing.
"""
import glob, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD_ROWS = os.path.join(HERE, "build_rows.py")
OUT = os.path.abspath("collected_rows")
TOOLS = ("idflakies", "nondex", "flakesync")

count = 0
for d in sorted(glob.glob("artifacts/*-results-*")):
    if not os.path.isdir(d):
        continue
    name = os.path.basename(d)
    tool = name.split("-results-")[0]
    if tool not in TOOLS:
        continue
    metas = []
    for root, _, files in os.walk(d):          # os.walk: glob's ** skips hidden dirs
        if "run_metadata.json" in files:
            metas.append(os.path.join(root, "run_metadata.json"))
    if not metas:
        print(f"skip {name}: no run_metadata.json")
        continue
    metas.sort(key=len)                         # root metadata before nested copies
    try:
        meta = json.load(open(metas[0], encoding="utf-8"))
    except Exception as e:
        print(f"skip {name}: bad metadata ({e})")
        continue
    env = dict(os.environ, GITHUB_WORKSPACE=os.path.join(OUT, name))
    r = subprocess.run([sys.executable, BUILD_ROWS, tool, meta.get("github_url", ""),
                        meta.get("sha", ""), meta.get("module_path", ".") or "."],
                       cwd=d, env=env, capture_output=True, text=True)
    print(f"{name}: {r.stdout.strip() or r.stderr.strip()}")
    count += 1
print(f"collected rows from {count} result artifacts")
