import os
import sys
import tempfile

# Point the app at a throwaway database + storage folder BEFORE it is imported.
_TMP = tempfile.mkdtemp(prefix="cnc_stamp_test_")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["SESSION_SECRET"] = "test-only-secret"
os.environ.pop("DASH_USERS", None)
os.environ.pop("STAMP_STORAGE_PATH", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
