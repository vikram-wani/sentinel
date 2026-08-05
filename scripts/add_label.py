"""Merges a single new label into examples/labels/taubench_ground_truth.json.

Usage:
  python scripts/add_label.py /tmp/new_label.json

Reads the existing ground-truth file (creates it if missing), merges in
whatever key(s) are in the given file, writes back, and prints a validation
summary. Never requires pasting the whole accumulated file again.
"""
import json
import sys
from pathlib import Path

GROUND_TRUTH = Path("examples/labels/taubench_ground_truth.json")

if len(sys.argv) != 2:
    raise SystemExit("usage: python scripts/add_label.py <path-to-new-label.json>")

new_label_path = Path(sys.argv[1])
new_entry = json.loads(new_label_path.read_text())

if GROUND_TRUTH.exists():
    existing = json.loads(GROUND_TRUTH.read_text())
else:
    GROUND_TRUTH.parent.mkdir(parents=True, exist_ok=True)
    existing = {}

before = len(existing)
existing.update(new_entry)
after = len(existing)

GROUND_TRUTH.write_text(json.dumps(existing, indent=2))

added = after - before
verb = "added" if added else "updated (key already existed)"
print(f"{verb}: {list(new_entry.keys())}")
print(f"total labels now: {after}")
print(f"all keys: {list(existing.keys())}")
