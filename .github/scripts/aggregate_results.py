import os
import glob
import json
import csv

IDFLAKIES_CSV = "idflakies_summary.csv"
NONDEX_CSV = "nondex_summary.csv"

# CHANGED: Replaced headers with those proposed in slack
headers = ["project_name", "sha", "flaky_tests"]

idflakies_rows = []
nondex_rows = []

def clean_and_validate_test_name(raw_line):
    """Validates and cleans raw lines/strings into a valid Java test identifier."""
    if not raw_line or not isinstance(raw_line, str):
        return None
    
    line = raw_line.strip()
    
    # Ignore metadata, comments, logs, and stack traces
    if (
        not line or 
        line.startswith("#") or 
        line.startswith("<") or 
        line.startswith("[") or 
        line.startswith("at ") or 
        line.startswith("INFO") or 
        line.startswith("WARN") or 
        line.startswith("ERROR") or 
        line.startswith("Tests run:") or 
        line.startswith("Test set:") or
        "InaccessibleObjectException" in line or
        "LogFactory" in line
    ):
        return None
    
    # Strip common Maven/Surefire trailing suffixes
    if " -- " in line:
        line = line.split(" -- ")[0].strip()
    if " <<<" in line:
        line = line.split(" <<<")[0].strip()
    if "(" in line and ")" in line:
        line = line.split("(")[0].strip()
    if " " in line:
        line = line.split()[0].strip()

    # Must be a valid Java test identifier (at least 2 dots, e.g., com.example.FooTest.testBar)
    parts = line.split(".")
    if len(parts) >= 3 and all(p.isidentifier() for p in parts):
        return line
    
    return None


def parse_idflakies_json(file_path):
    """Precise parser for iDFlakies flaky-lists.json structure."""
    found_tests = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
            
            if isinstance(data, dict):
                for strategy, test_list in data.items():
                    if isinstance(test_list, list):
                        for item in test_list:
                            if isinstance(item, str):
                                cleaned = clean_and_validate_test_name(item)
                                if cleaned:
                                    found_tests.append(cleaned)
                            elif isinstance(item, dict):
                                for key in ["testName", "test_name", "name"]:
                                    if key in item and isinstance(item[key], str):
                                        if item.get("flaky", True) is True:
                                            cleaned = clean_and_validate_test_name(item[key])
                                            if cleaned:
                                                found_tests.append(cleaned)
    except Exception as e:
        print(f"Error parsing iDFlakies precision JSON {file_path}: {e}")
    return found_tests


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
    
    # 1. Load run metadata
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

    # CHANGED: Dynamically extract clean repo name from Github URL
    repo_name_clean = github_url.rstrip("/").split("/")[-1].replace(".git", "")

    # --- 2. Parse iDFlakies Results ---
    idflakies_files = [
        f for f in all_files 
        if f.startswith(art_dir) 
        and ".dtfixingtools" in f 
        and os.path.basename(f) != "list.txt"
        and not any(f.endswith(ext) for ext in [".html", ".keep", ".png", ".jpg", ".class", ".xml"])
    ]

    for res_file in idflakies_files:
        base_name = os.path.basename(res_file)
        
        if base_name == "flaky-lists.json":
            detected = parse_idflakies_json(res_file)
            for t_name in detected:
                # CHANGED: Using repo_name_clean instead of github_url
                idflakies_rows.append([repo_name_clean, sha, t_name])
                
        elif base_name in ["failing-tests", "failing"]:
            try:
                with open(res_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        cleaned = clean_and_validate_test_name(line)
                        if cleaned:
                            # CHANGED: Using repo_name_clean instead of github_url
                            idflakies_rows.append([repo_name_clean, sha, cleaned])
            except Exception as e:
                print(f"Error reading iDFlakies file {res_file}: {e}")

    # --- 3. Extract Test Names directly from true failing-test-output files ---
    failing_output_files = [
        f for f in all_files 
        if f.startswith(art_dir) and "failing-test-output" in f and f.endswith(".xml")
    ]
    for xml_file in failing_output_files:
        try:
            with open(xml_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                if "<failure" in content or "<error" in content:
                    base_name = os.path.basename(xml_file)
                    class_name = base_name.replace("TEST-", "").replace(".xml", "")
                    cleaned = clean_and_validate_test_name(class_name)
                    if cleaned:
                        # CHANGED: Using repo_name_clean instead of github_url
                        idflakies_rows.append([repo_name_clean, sha, cleaned])
        except Exception as e:
            print(f"Error reading xml output verification step {xml_file}: {e}")

    # --- 4. Parse NonDex Results ---
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
                        # CHANGED: Using repo_name_clean instead of github_url
                        nondex_rows.append([repo_name_clean, sha, cleaned])
        except Exception as e:
            print(f"Error reading NonDex file {res_file}: {e}")

# Deduplicate rows completely
idflakies_rows = [list(x) for x in set(tuple(r) for r in idflakies_rows)]
nondex_rows = [list(x) for x in set(tuple(r) for r in nondex_rows)]

# Save clean CSV outputs
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
