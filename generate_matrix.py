import pandas as pd
import json
import os

# Fetch pr-data.csv from the IDoFT repo
url = "https://raw.githubusercontent.com/TestingResearchIllinois/idoft/main/pr-data.csv"
df = pd.read_csv(url)

# Clean the columns to remove whitespace before/after the project name
df.columns = df.columns.str.strip()

# We only need the first three columns from pr-data.csv...and we do NOT need duplicates
deduped = df[['Project URL', 'SHA Detected', 'Module Path']].drop_duplicates()

# Limit amt we process
max_runs = os.environ.get("MAX_RUNS")
if max_runs and max_runs.isdigit(): # make sure it's a number
    deduped = deduped.head(int(max_runs))

# Go through each project
matrix_include = []
for _, row in deduped.iterrows():
    repo_url = ['Project URL']
    repo_name = repo_url.rstrip('/').split('/')[-1].replace('.git', '')

    matrix_include.append({
        "repo_url": repo_url,
        "repo_name": repo_name,
        "sha": str(row['SHA Detected']).strip(),
        "module_path": str(row['Module Path']).strip() if pd.notna(row['Module Path']) else "."
    })

# Output to JSON for GitHub actions
matrix_json = json.dumps({"include": matrix_include})
print(f"matrix={matrix_json}")