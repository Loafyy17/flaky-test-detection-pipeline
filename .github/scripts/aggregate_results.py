import os
import glob
import json
import csv
import re

IDFLAKIES_CSV = "idflakies_summary.csv"
NONDEX_CSV = "nondex_summary.csv"

headers = ["Github Link", "SHA", "Flaky Test Identified"]

idflakies_rows = []
nondex_rows = []

def clean_and_validate_test_name(raw_line):
    if not raw_line or not isinstance(raw_line, str):
        return None
    
    line = raw_line.strip()
    
    # Ignore empty lines, comments, stack traces, Maven info, and XML/HTML tags
    if (
        not line or 
        line.startswith("#") or 
        line.startswith("<") or 
        line.startswith("[") or 
        line.startswith("at ") or 
        line.startswith("INFO") or 
        line.startswith("Tests run:") or 
        line.startswith("Test set:")
    ):
        return None
    
    # Strip common Maven / Surefire trailing suffixes
    if " -- " in line:
        line = line.split(" -- ")[0].strip()
    if " <<<" in line:
        line = line.split(" <<<")[0].strip()
    if "(" in line and ")" in line:
        line = line.split("(")[0].strip()
    if " " in line:
        line = line.split()[0].strip()

    # Must be a valid Java package/class/method (e.g., com.example.FooTest.testBar)
    parts = line.split(".")
    if len(parts) >= 3 and all(p.isidentifier() for p in parts):
        return line
    
    return None


print("=== STARTING AGGREGATION SCAN ===")

all_files = []
for root, dirs, files in os.walk("artifacts"):
    for file in files:
        full_path = os.path.join(root, file)
        all_files.append(full_path)

print(f"Total files found across downloaded artifacts: {len(all_files)}")

artifact_dirs = glob.glob("artifacts/*")

for art_dir in artifact_dirs:
    print(f"\nProcessing Artifact Directory: {art_dir}")
    
    # 1. Load metadata
    meta_files = [f for f in all_files if f.startswith(art_dir) and f.endswith("run_metadata.json")]
    if not meta_files:
        print(f"Skipping {art_dir}: No run_metadata.json found.")
        continue
    
    meta_path = meta_files[0]
    github_url = ""
    sha = ""
    
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
            github_url = meta.get("github_url", "")
            sha = meta.get("sha", "")
            print(f"  Loaded Metadata -> {github_url} @ {sha}")
    except Exception as e:
        print(f"Error reading metadata {meta_path}: {e}")
        continue

    # --- 2. Parse iDFlakies Results ---
    idflakies_files = [
        f for f in all_files 
        if f.startswith(art_dir) and ".dtfixingtools" in f and f.endswith(".json")
    ]

    for res_file in idflakies_files:
        try:
            with open(res_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                
                entries = data if isinstance(data, list) else (
                    data.get("detected_tests") or 
                    data.get("flakyTests") or 
                    data.get("flaky_tests") or 
                    data.get("detected") or []
                ) if isinstance(data, dict) else []

                for entry in entries:
                    raw_t = entry.get("test_name") or entry.get("name") if isinstance(entry, dict) else str(entry)
                    cleaned = clean_and_validate_test_name(raw_t)
                    if cleaned:
                        idflakies_rows.append([github_url, sha, cleaned])
        except Exception as e:
            print(f"Error reading iDFlakies file {res_file}: {e}")

    # --- 3. Parse NonDex Results ---
    # Primary candidate failure list files
    nondex_files = [
        f for f in all_files 
        if f.startswith(art_dir) and ".nondex" in f and not any(
            f.endswith(ext) for ext in [".xml", ".html", ".json", ".keep", ".png", ".jpg", ".class"]
        )
    ]

    for res_file in nondex_files:
        try:
            with open(res_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    cleaned = clean_and_validate_test_name(line)
                    if cleaned:
                        nondex_rows.append([github_url, sha, cleaned])
        except Exception as e:
            print(f"Error reading NonDex file {res_file}: {e}")

# Deduplicate rows
idflakies_rows = [list(x) for x in set(tuple(r) for r in idflakies_rows)]
nondex_rows = [list(x) for x in set(tuple(r) for r in nondex_rows)]

# Save CSVs
with open(IDFLAKIES_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(headers)
    writer.writerows(idflakies_rows)

with open(NONDEX_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(headers)
    writer.writerows(nondex_rows)

print(f"\nCompleted!")
print(f"  Clean iDFlakies flaky tests detected: {len(idflakies_rows)}")
print(f"  Clean NonDex flaky tests detected:    {len(nondex_rows)}")
