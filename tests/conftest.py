import os
import sys
from pathlib import Path
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Preserve original TestClient.request
_real_testclient_request = TestClient.request

def _patched_testclient_request(self, method, url, *args, **kwargs):
    curr_test = os.environ.get("PYTEST_CURRENT_TEST", "")
    # If the active test specifically tests missing Origin, do not auto-inject
    if "missing_origin" not in curr_test:
        hdrs = kwargs.get("headers")
        if hdrs is None:
            hdrs = dict(self.headers)
            kwargs["headers"] = hdrs
        elif isinstance(hdrs, dict):
            # Shallow copy to avoid mutating caller dict
            hdrs = dict(hdrs)
            kwargs["headers"] = hdrs
        if isinstance(hdrs, dict) and "Origin" not in hdrs and "origin" not in hdrs:
            hdrs["Origin"] = "http://testserver"

    return _real_testclient_request(self, method, url, *args, **kwargs)

TestClient.request = _patched_testclient_request
