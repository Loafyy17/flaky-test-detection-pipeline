import pandas as pd
import json
import os

# Fetch pr-data.csv from IDoFT repo
url = "https://raw.githubusercontent.com/TestingResearchIllinois/idoft/main/pr-data.csv"
df = pd.read_csv(url)

# Clean column names
df.columns = df.columns.str.strip()

# Extract and deduplicate target project runs
deduped = df[['Project URL', 'SHA Detected', 'Module Path']].drop_duplicates()

# Optional limit for testing (set via MAX_RUNS environment variable)
max_runs = os.environ.get("MAX_RUNS")
if max_runs and max_runs.isdigit():
    deduped = deduped.head(int(max_runs))

matrix_include = []
for _, row in deduped.iterrows():
    repo_url = str(row['Project URL']).strip()
    
    # Clean repo slug (e.g. "https://github.com/owner/repo" -> "owner/repo")
    repo_slug = repo_url.replace("https://github.com/", "").rstrip("/").replace(".git", "")
    repo_name = repo_slug.split("/")[-1]
    
    matrix_include.append({
        "repo_url": repo_url,
        "repo_slug": repo_slug,  # Added clean owner/repo slug
        "repo_name": repo_name,
        "sha": str(row['SHA Detected']).strip(),
        "module_path": str(row['Module Path']).strip() if pd.notna(row['Module Path']) else "."
    })

# Output JSON string for GitHub Actions matrix
matrix_json = json.dumps({"include": matrix_include})
print(f"matrix={matrix_json}")
