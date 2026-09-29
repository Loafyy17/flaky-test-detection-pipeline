import pandas as pd
import json
import os

# Your exact repository tracking sheet URL
url = "https://raw.githubusercontent.com/TestingResearchIllinois/idoft/main/pr-data.csv"
df = pd.read_csv(url)

# Clean whitespaces from column names
df.columns = df.columns.str.strip()

# Deduplicate rows based on the core project info to match your layout
deduped = df[['Project URL', 'SHA Detected', 'Module Path']].drop_duplicates().reset_index(drop=True)

# 1. Safely extract and convert the OFFSET environment variable
offset_env = os.environ.get("OFFSET", "0")
offset = int(offset_env) if offset_env.isdigit() else 0

# 2. Safely extract and convert the MAX_RUNS environment variable
max_runs_env = os.environ.get("MAX_RUNS")
max_runs = int(max_runs_env) if (max_runs_env and max_runs_env.isdigit()) else None

# 3. Apply precise chunk slicing using .iloc based on the user parameters
if max_runs is not None:
    deduped = deduped.iloc[offset : offset + max_runs]
else:
    deduped = deduped.iloc[offset:]

matrix_include = []
for _, row in deduped.iterrows():
    repo_url = str(row['Project URL']).strip()
    
    # FIX: Use .strip("/") to completely wipe out any accidental leading/trailing slashes
    repo_slug = repo_url.replace("https://github.com", "").replace(".git", "").strip("/")
    repo_name = repo_slug.split("/")[-1]
    
    matrix_include.append({
        "repo_url": repo_url,
        "repo_slug": repo_slug,
        "repo_name": repo_name,
        "sha": str(row['SHA Detected']).strip(),
        "module_path": str(row['Module Path']).strip() if pd.notna(row['Module Path']) else "."
    })

# Output the matrix string format required by your original YAML configuration
matrix_json = json.dumps({"include": matrix_include})
print(f"matrix={matrix_json}")
