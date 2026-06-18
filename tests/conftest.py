import json
import os
from pathlib import Path

import pytest

# Local-only creds file outside this repo, shared with the mfp_api package's own tests.
# Not required to run the non-live test suite.
CREDS_PATH = Path(r"C:\Users\Nathan\MfpApi\creds.json")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "live: hits the real MyFitnessPal API with a real account (needs creds.json)"
    )


@pytest.fixture(scope="session", autouse=True)
def mfp_credentials():
    if not CREDS_PATH.exists():
        pytest.skip(f"no creds.json at {CREDS_PATH} -- skipping live tests")
    data = json.loads(CREDS_PATH.read_text())
    os.environ["MFP_USERNAME"] = data["username"]
    os.environ["MFP_PASSWORD"] = data["password"]
