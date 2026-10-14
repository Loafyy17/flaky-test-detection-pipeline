import os
import re

import pandas as pd

IDOFT_TEST_COL = 'Fully-Qualified Test Name (packageName.ClassName.methodName)'


def load_data(filepath):
    if os.path.exists(filepath):
        try:
            return pd.read_csv(filepath, dtype=str, keep_default_na=False)
        except pd.errors.EmptyDataError:
            pass
    return pd.DataFrame()


def norm_test(name):
    """FlakeSync names look like Class#method (maybe with a trailing '-'); IDoFT uses Class.method."""
    return str(name).strip().replace('#', '.').rstrip('-.')


def repo_of(url):
    return re.sub(r'\.git$', '', str(url).strip().rstrip('/').split('/')[-1])


# Load IDoFT dataset: the set of (repo, test) pairs it already knows about
idoft_df = load_data('pr-data.csv')
idoft_keys = set()
if not idoft_df.empty:
    idoft_df.columns = idoft_df.columns.str.strip()
    if IDOFT_TEST_COL in idoft_df.columns:
        for url, test in zip(idoft_df['Project URL'], idoft_df[IDOFT_TEST_COL]):
            idoft_keys.add((repo_of(url), norm_test(test)))

# Load detected data. Each summary names its test column differently.
idflakies_df = load_data('idflakies_summary.csv')
nondex_df = load_data('nondex_summary.csv')
flakesync_df = load_data('flakesync_td_tests.csv')


def test_column(df):
    for col in ('flaky_tests', 'test_name'):
        if col in df.columns:
            return col
    return None


def count_total(df):
    col = test_column(df)
    return len(df) if col else 0


# A detected test is "unique" when IDoFT has no row for the same project and test
# (any SHA: a known flaky test found at a newer commit is not a new find).
def get_unique(df):
    unique_list = []
    col = test_column(df)
    if df.empty or col is None:
        return unique_list
    seen = set()
    for _, row in df.iterrows():
        proj = row.get('project_name', 'Unknown').strip()
        sha = row.get('sha', 'Unknown').strip()
        test = row[col].strip()
        key = (proj, norm_test(test))
        if key not in idoft_keys and (proj, sha, test) not in seen:
            seen.add((proj, sha, test))
            unique_list.append(f"- {proj}, {sha}, {test}")
    return unique_list


idflakies_total = count_total(idflakies_df)
nondex_total = count_total(nondex_df)
flakesync_total = count_total(flakesync_df)

idflakies_unique = get_unique(idflakies_df)
nondex_unique = get_unique(nondex_df)
flakesync_unique = get_unique(flakesync_df)

# Write formatted output
with open('unique_tests.txt', 'w') as f:
    f.write("Flakies:\n")
    f.write(f"iDFlakies: {idflakies_total}\n")
    f.write(f"nondex: {nondex_total}\n")
    f.write(f"flakesync: {flakesync_total}\n\n")

    f.write("unique flakies:\n")
    f.write(f"iDflakies: {len(idflakies_unique)}\n")
    for item in idflakies_unique:
        f.write(f"{item}\n")

    f.write(f"Nondex: {len(nondex_unique)}\n")
    for item in nondex_unique:
        f.write(f"{item}\n")

    f.write(f"flakesync: {len(flakesync_unique)}\n")
    for item in flakesync_unique:
        f.write(f"{item}\n")

print("Generated unique_tests.txt successfully.")
