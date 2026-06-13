#!/usr/bin/env python3
"""Insert N notes via the REST gateway. Usage: python scripts/seed_notes.py [count]"""

import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE  = "http://localhost:8000"
COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 1000


def create_note(i: int) -> str:
    payload = json.dumps({"title": f"Note {i}", "body": f"Body of note number {i}"}).encode()
    req = urllib.request.Request(
        f"{BASE}/notes",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["id"]


def main():
    print(f"Inserting {COUNT} notes into {BASE} ...")
    done = 0
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(create_note, i): i for i in range(1, COUNT + 1)}
        for future in as_completed(futures):
            future.result()
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{COUNT}")
    print(f"Done — {COUNT} notes inserted.")


if __name__ == "__main__":
    main()
