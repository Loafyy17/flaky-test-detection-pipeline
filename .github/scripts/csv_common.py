"""Shared constants and normalisers for build_rows.py and merge_rows.py."""

TEST_COL = "Fully-Qualified Test Name (packageName.ClassName.methodName)"

# What each detector job writes (flaky_rows/<tool>.csv). No pr-data lookup happens here.
RUN_COLUMNS = ["Tool", "Failure rate", "Project URL", "SHA Detected", "Module Path", TEST_COL]

# What the final flaky_tests.csv contains.
FINAL_COLUMNS = ["Tool", "Failure rate", "In pr-data", "Project URL", "SHA Detected",
                 "Module Path", TEST_COL, "Category", "Status", "PR Link", "Notes"]


def norm_url(u):
    u = (u or "").strip().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    u = u.lower().replace("http://", "https://").replace("://www.", "://")
    return u


def norm_module(m):
    m = (m or "").strip().strip("/")
    while m.startswith("./"):
        m = m[2:]
    return "" if m == "." else m


def norm_test(name):
    """FlakeSync names look like Class#method (sometimes with a trailing '-' or '.');
    pr-data uses Class.method."""
    return (name or "").strip().replace("#", ".").rstrip("-. ")
