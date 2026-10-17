import pandas as pd
import json
import os
import re
import sys
import warnings
from urllib.parse import urlparse

# Suppress pandas / deprecation warnings so they don't print to stdout and corrupt GITHUB_OUTPUT
warnings.filterwarnings('ignore')


# Exact repository tracking sheet URL from the open-source IDoFT dataset
url = "https://raw.githubusercontent.com/TestingResearchIllinois/idoft/main/pr-data.csv"
df = pd.read_csv(url)

# Clean whitespaces from column names to prevent extraction errors
df.columns = df.columns.str.strip()

# Clean and normalize columns upfront to ensure reliable downstream filtering matches
df['Project URL'] = df['Project URL'].astype(str).str.strip()
df['SHA Detected'] = df['SHA Detected'].astype(str).str.strip()
# Normalise Module Path (blank / missing means the repo root)
df['Module Path'] = df['Module Path'].fillna('.').astype(str).str.strip().replace('', '.')

# Deduplicate rows based on the core project info to match your target matrix structure
deduped = df[['Project URL', 'SHA Detected', 'Module Path']].drop_duplicates().reset_index(drop=True)

# 1. Safely extract and convert the OFFSET environment variable for pagination
offset_env = os.environ.get("OFFSET", "0")
offset = int(offset_env) if offset_env.isdigit() else 0

# 2. Safely extract and convert the MAX_RUNS environment variable for pagination batching
max_runs_env = os.environ.get("MAX_RUNS")
max_runs = int(max_runs_env) if (max_runs_env and max_runs_env.isdigit()) else None

# 3. Apply precise chunk slicing using .iloc based on the pagination parameters
if max_runs is not None:
    deduped = deduped.iloc[offset : offset + max_runs]
else:
    deduped = deduped.iloc[offset:]

matrix_include = []

# Find the test name column dynamically to avoid exact-match spelling errors from IDoFT
test_col = next((col for col in df.columns if 'Fully-Qualified Test' in col), None)
if not test_col:
    raise ValueError("Could not find the Fully-Qualified Test Name column in the IDoFT CSV!")

# Robust helper for extracting owner/repo slug regardless of protocol format
def extract_repo_slug(raw_url):
    parsed = urlparse(raw_url)
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return path

# Iterate through every unique repository-SHA configuration chunk
for _, row in deduped.iterrows():
    repo_url = row['Project URL']
    repo_slug = extract_repo_slug(repo_url)
    repo_name = repo_slug.split("/")[-1] if "/" in repo_slug else repo_slug
    sha = row['SHA Detected']


    module_path = row['Module Path']
    # repo_name only feeds job and artifact names. Several modules of one repo@sha would otherwise
    # share an artifact name and upload-artifact@v4 rejects duplicates, so add a filename-safe module slug.
    if module_path not in ('.', ''):
        repo_name = f"{repo_name}--{re.sub(r'[^A-Za-z0-9._-]+', '_', module_path).strip('_')}"

    # Group by repo_url, sha AND module so each matrix job only gets tests that live in its
    # own module (otherwise every module of a repo would be handed every module's tests)
    matching_rows = df[(df['Project URL'] == repo_url) & (df['SHA Detected'] == sha)
                       & (df['Module Path'] == module_path)]
    # Drop blanks and repeated names (pr-data can list one test several times)
    raw_tests = list(dict.fromkeys(t.strip() for t in matching_rows[test_col].dropna().astype(str) if t.strip()))

    # Format test paths with '#' character separating class from method for FlakeSync compatibility
    formatted_tests = []
    for t in raw_tests:
        t = t.strip()
        if '.' in t:
            parts = t.split('.')
            formatted_tests.append('.'.join(parts[:-1]) + '#' + parts[-1])
        else:
            formatted_tests.append(t)

    # Package into the structure required by the parallel GitHub Actions include matrix
    matrix_include.append({
        "repo_url": repo_url,
        "repo_slug": repo_slug,
        "repo_name": repo_name,
        "sha": sha,
        "module_path": module_path,
        "test_names": ",".join(formatted_tests) # Pass as comma-separated string to runner loop
    })

# Output the matrix string format required by your YAML configuration
matrix_json = json.dumps({"include": matrix_include})
print(f"matrix={matrix_json}")
