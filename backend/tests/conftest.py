import json
import os
import sys
import pytest

# Make the backend package importable regardless of where pytest is invoked.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture(scope="session")
def proposal_text():
    with open(os.path.join(FIXTURES, "milton_proposal.txt"), encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="session")
def moa_text():
    with open(os.path.join(FIXTURES, "milton_moa.txt"), encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="session")
def expected():
    with open(os.path.join(FIXTURES, "milton_expected.json"), encoding="utf-8") as f:
        return json.load(f)
