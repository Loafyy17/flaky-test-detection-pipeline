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

for art_dir in artifact_dirs:
    meta_path = os.path.join(art_dir, "run_metadata.json")
    if not os.path.exists(meta_path):
        continue

    with open(meta_path, "r") as f:
        meta = json.load(f)

    github_url = meta.get("github_url", "")
    sha = meta.get("sha", "")

    # --- 1. Parse iDFlakies Results ---
    idflakies_files = glob.glob(os.path.join(art_dir, "**", "idflakies-detection-results.json"), recursive=True)
    for res_file in idflakies_files:
        try:
            with open(res_file, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    for entry in data:
                        test_name = entry.get("test_name") or entry.get("name")
                        if test_name:
                            idflakies_rows.append([github_url, sha, "iDFlakies", test_name])
                elif isinstance(data, dict):
                    detected = data.get("detected_tests", []) or data.get("flakyTests", [])
                    for test_name in detected:
                        idflakies_rows.append([github_url, sha, "iDFlakies", str(test_name)])
        except Exception as e:
            print(f"Error reading iDFlakies file {res_file}: {e}")

    # --- 2. Parse NonDex Results ---
    nondex_files = glob.glob(os.path.join(art_dir, "**", ".nondex", "nondex-failures"), recursive=True) + \
                   glob.glob(os.path.join(art_dir, "**", ".nondex", "failures"), recursive=True)
    
    for res_file in nondex_files:
        try:
            with open(res_file, "r") as f:
                for line in f:
                    test_name = line.strip()
                    if test_name and not test_name.startswith("#"):
                        nondex_rows.append([github_url, sha, "NonDex", test_name])
        except Exception as e:
            print(f"Error reading NonDex file {res_file}: {e}")

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

print(f"Aggregation complete.")
print(f" - iDFlakies flaky tests recorded: {len(idflakies_rows)} -> {IDFLAKIES_CSV}")
print(f" - NonDex flaky tests recorded: {len(nondex_rows)} -> {NONDEX_CSV}")