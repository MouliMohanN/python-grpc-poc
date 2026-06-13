#!/usr/bin/env python3
"""Delete all notes via the REST gateway. Usage: python scripts/delete_notes.py"""

import json
import urllib.request

BASE = "http://localhost:8000"

req = urllib.request.Request(f"{BASE}/notes", method="DELETE")
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())
    print(f"Deleted {result['deleted']} notes.")
