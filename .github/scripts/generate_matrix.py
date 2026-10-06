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
# Find the test name column dynamically to avoid exact-match spelling errors from IDoFT
test_col = next((col for col in df.columns if 'Fully-Qualified Test' in col), None)

if not test_col:
    raise ValueError("Could not find the Fully-Qualified Test Name column in the IDoFT CSV!")

for _, row in deduped.iterrows():
    repo_url = str(row['Project URL']).strip()
    repo_slug = repo_url.replace("https://github.com", "").replace(".git", "").strip("/")
    repo_name = repo_slug.split("/")[-1]
    sha = str(row['SHA Detected']).strip()
    
    # Get all tests for this SHA and format them with '#' for FlakeSync
    raw_tests = df[df['SHA Detected'].astype(str).str.strip() == sha][test_col].dropna().astype(str).tolist()
    formatted_tests = []
    for t in raw_tests:
        t = t.strip()
        if '.' in t:
            parts = t.split('.')
            formatted_tests.append('.'.join(parts[:-1]) + '#' + parts[-1])
        else:
            formatted_tests.append(t)
            
    matrix_include.append({
        "repo_url": repo_url,
        "repo_slug": repo_slug,
        "repo_name": repo_name,
        "sha": sha,
        "module_path": str(row['Module Path']).strip() if pd.notna(row['Module Path']) else ".",
        "test_names": ",".join(formatted_tests) # Pass as comma-separated string
    })

# Output the matrix string format required by your original YAML configuration
matrix_json = json.dumps({"include": matrix_include})
print(f"matrix={matrix_json}")
