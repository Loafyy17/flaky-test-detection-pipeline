import os
import glob
import json
import csv

IDFLAKIES_CSV = "idflakies_summary.csv"
NONDEX_CSV = "nondex_summary.csv"

headers = ["Github Link", "SHA", "Flaky Test Identified"]

idflakies_rows = []
nondex_rows = []

print("=== STARTING AGGREGATION SCAN ===")

all_files = []
for root, dirs, files in os.walk("artifacts"):
    for file in files:
        full_path = os.path.join(root, file)
        all_files.append(full_path)

print(f"Total files found across all downloaded artifacts: {len(all_files)}")

artifact_dirs = glob.glob("artifacts/*")

for art_dir in artifact_dirs:
    print(f"\nProcessing Artifact Directory: {art_dir}")
    
    # 1. Locate run_metadata.json
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
    print(f"  iDFlakies JSON files found: {len(idflakies_files)}")

    for res_file in idflakies_files:
        try:
            with open(res_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                
                if isinstance(data, list):
                    for entry in data:
                        if isinstance(entry, dict):
                            t_name = entry.get("test_name") or entry.get("name") or entry.get("test")
                            if t_name:
                                idflakies_rows.append([github_url, sha, str(t_name)])
                
                elif isinstance(data, dict):
                    detected = (
                        data.get("detected_tests") or 
                        data.get("flakyTests") or 
                        data.get("flaky_tests") or 
                        data.get("detected") or 
                        []
                    )
                    if isinstance(detected, list):
                        for item in detected:
                            t_name = item.get("test_name") or item.get("name") if isinstance(item, dict) else str(item)
                            if t_name:
                                idflakies_rows.append([github_url, sha, str(t_name)])
        except Exception as e:
            print(f"Error reading iDFlakies file {res_file}: {e}")

    # --- 3. Parse NonDex Results ---
    # Find NonDex text/log/failure files, excluding XML, HTML, JSON, and .keep
    nondex_files = [
        f for f in all_files 
        if f.startswith(art_dir) and ".nondex" in f and not any(
            f.endswith(ext) for ext in [".xml", ".html", ".json", ".keep", ".png", ".jpg"]
        )
    ]
    print(f"  NonDex candidate failure files found: {len(nondex_files)}")

    for res_file in nondex_files:
        try:
            with open(res_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    t_name = line.strip()
                    # Filter out empty lines, XML/HTML tags, comments, and Maven debug lines
                    if (
                        t_name and 
                        not t_name.startswith("#") and 
                        not t_name.startswith("<") and 
                        not t_name.startswith("[") and
                        not t_name.startswith("INFO") and
                        "." in t_name # Test names always contain package dots (e.g. com.foo.BarTest)
                    ):
                        nondex_rows.append([github_url, sha, t_name])
        except Exception as e:
            print(f"Error reading NonDex file {res_file}: {e}")

# Deduplicate rows
idflakies_rows = [list(x) for x in set(tuple(r) for r in idflakies_rows)]
nondex_rows = [list(x) for x in set(tuple(r) for r in nondex_rows)]

# Write output CSVs
with open(IDFLAKIES_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(headers)
    writer.writerows(idflakies_rows)

with open(NONDEX_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(headers)
    writer.writerows(nondex_rows)

print(f"\nCompleted!")
print(f"  iDFlakies flaky tests detected: {len(idflakies_rows)}")
print(f"  NonDex flaky tests detected:    {len(nondex_rows)}")
