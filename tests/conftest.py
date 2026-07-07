import json
from pathlib import Path

import pytest

# Local-only creds file outside this repo, shared with the mfp_api package's own tests.
# Not required to run the non-live test suite.
CREDS_PATH = Path(r"C:\Users\Nathan\MfpApi\creds.json")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "live: hits the real MyFitnessPal API with a real account (needs creds.json)"
    )


@pytest.fixture(autouse=True)
def mfp_credentials(request, monkeypatch):
    """For live tests: load creds.json into MFP_USERNAME/MFP_PASSWORD and pin the
    token path next to it, so a developer's personal ~/.mfp-mcp session is never
    used against the test account's data."""
    if request.node.get_closest_marker("live") is None:
        return
    if not CREDS_PATH.exists():
        pytest.skip(f"no creds.json at {CREDS_PATH} -- skipping live tests")
    data = json.loads(CREDS_PATH.read_text())
    monkeypatch.setenv("MFP_USERNAME", data["username"])
    monkeypatch.setenv("MFP_PASSWORD", data["password"])
    monkeypatch.setenv("MFP_TOKEN_PATH", str(CREDS_PATH.parent / "mcp_session.json"))
