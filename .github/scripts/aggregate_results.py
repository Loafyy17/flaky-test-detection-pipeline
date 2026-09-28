import os
import glob
import json
import csv

IDFLAKIES_CSV = "idflakies_summary.csv"
NONDEX_CSV = "nondex_summary.csv"

headers = ["Github Link", "SHA", "Tool Name", "Flaky Test Identified"]

idflakies_rows = []
nondex_rows = []

artifact_dirs = glob.glob("artifacts/*")
print(f"Discovered {len(artifact_dirs)} artifact directories in 'artifacts/':")
for d in artifact_dirs:
    print(f" - {d}")

for art_dir in artifact_dirs:
    meta_path = os.path.join(art_dir, "run_metadata.json")
    if not os.path.exists(meta_path):
        found_meta = glob.glob(os.path.join(art_dir, "**", "run_metadata.json"), recursive=True)
        if found_meta:
            meta_path = found_meta[0]
        else:
            print(f"[WARNING] Skipping {art_dir}: No run_metadata.json found.")
            continue

    try:
        with open(meta_path, "r") as f:
            meta = json.load(f)
    except Exception as e:
        print(f"[ERROR] Could not read metadata at {meta_path}: {e}")
        continue

    github_url = meta.get("github_url", "")
    sha = meta.get("sha", "")

    # --- 1. Parse iDFlakies Results ---
    idflakies_files = (
        glob.glob(os.path.join(art_dir, "**", ".dtfixingtools", "*.json"), recursive=True) +
        glob.glob(os.path.join(art_dir, "**", "idflakies-detection-results.json"), recursive=True)
    )
    idflakies_files = list(set(idflakies_files))
    print(f"[{art_dir}] iDFlakies files found: {idflakies_files}")

    for res_file in idflakies_files:
        try:
            with open(res_file, "r") as f:
                data = json.load(f)
                
                if isinstance(data, list):
                    for entry in data:
                        if isinstance(entry, dict):
                            test_name = entry.get("test_name") or entry.get("name") or entry.get("test")
                            if test_name:
                                idflakies_rows.append([github_url, sha, "iDFlakies", str(test_name)])
                
                elif isinstance(data, dict):
                    detected = data.get("detected_tests", []) or data.get("flakyTests", []) or data.get("flaky_tests", [])
                    if isinstance(detected, list):
                        for item in detected:
                            if isinstance(item, dict):
                                test_name = item.get("test_name") or item.get("name")
                            else:
                                test_name = str(item)
                            if test_name:
                                idflakies_rows.append([github_url, sha, "iDFlakies", test_name])
        except Exception as e:
            print(f"[ERROR] Reading iDFlakies file {res_file}: {e}")

    # --- 2. Parse NonDex Results ---
    nondex_files = (
        glob.glob(os.path.join(art_dir, "**", ".nondex", "nondex-failures"), recursive=True) +
        glob.glob(os.path.join(art_dir, "**", ".nondex", "failures"), recursive=True) +
        glob.glob(os.path.join(art_dir, "**", ".nondex", "*.txt"), recursive=True)
    )
    nondex_files = list(set(nondex_files))
    print(f"[{art_dir}] NonDex files found: {nondex_files}")

    for res_file in nondex_files:
        try:
            with open(res_file, "r") as f:
                for line in f:
                    test_name = line.strip()
                    if test_name and not test_name.startswith("#"):
                        nondex_rows.append([github_url, sha, "NonDex", test_name])
        except Exception as e:
            print(f"[ERROR] Reading NonDex file {res_file}: {e}")

# Write iDFlakies CSV
with open(IDFLAKIES_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(headers)
    writer.writerows(idflakies_rows)

# Write NonDex CSV
with open(NONDEX_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(headers)
    writer.writerows(nondex_rows)

print("\n--- Aggregation Summary ---")
print(f"iDFlakies rows collected: {len(idflakies_rows)} -> written to {IDFLAKIES_CSV}")
print(f"NonDex rows collected:    {len(nondex_rows)} -> written to {NONDEX_CSV}")
