"""Generates a findings summary directly from examples/labels/taubench_ground_truth.json.

Never hand-maintain a separate findings log -- it drifts out of sync with the
actual labels (this happened once already, task76 got mis-tracked under the
wrong cluster in conversation). This script reads the one source of truth
and regenerates the summary every time, so it's always accurate as of
whatever's actually been labeled.

Usage:
  python scripts/generate_findings_log.py
  python scripts/generate_findings_log.py --out DAY4_FINDINGS.md
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

GROUND_TRUTH = Path("examples/labels/taubench_ground_truth.json")

# Known cross-trace clusters, hand-identified during labeling, kept here
# (not inferred) since "same underlying pattern" is a judgment call, not
# something derivable purely from the category field. Update this dict as
# new clusters get identified -- it's the one piece of this file that IS
# manually maintained, deliberately kept small and separate from the rest.
CLUSTERS = {
    "premature_stop_after_progress": {
        "label": "Stops a required search/workflow after partial progress",
        "traces": ["task81-trial0", "task76-trial3", "task102-trial0", "task83-trial0",
                   "task22-trial2", "task55-trial0", "task23-trial3", "task111-trial1"],
    },
    "false_blocker_before_start": {
        "label": "Claims a false blocker, halts before any real work begins",
        "traces": ["task13-trial0", "task48-trial0", "task93-trial0"],
    },
    "sequencing_state_dependency": {
        "label": "Two individually-correct calls in the wrong order; first locks out the second",
        "traces": ["task98-trial0", "task98-trial3", "task41-trial2"],
    },
    "grounded_wrong_entity": {
        "label": "Value/entity is real and grounded, applied to the wrong target",
        "traces": ["task28-trial1", "task80-trial2", "task83-trial0", "task21-trial0"],
    },
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", help="write markdown to this path instead of stdout")
    a = p.parse_args()

    labels = json.loads(GROUND_TRUTH.read_text())
    n = len(labels)

    cat_counts = Counter(v["root_category"] for v in labels.values())
    detector_counts = Counter(
        "has detector" if v["sentinel_has_detector"] else
        ("no detector" if v["sentinel_has_detector"] is False else "n/a")
        for v in labels.values()
    )

    lines = []
    lines.append(f"# Day 4 Findings Log")
    lines.append(f"\n*Auto-generated from `taubench_ground_truth.json` — {n} traces labeled. "
                  f"Regenerate with `python scripts/generate_findings_log.py`, never hand-edit.*\n")

    lines.append("## Root cause categories\n")
    lines.append("| Category | Count | Traces |")
    lines.append("|---|---|---|")
    for cat, count in cat_counts.most_common():
        traces = sorted(k.replace("taubench-retail-", "") for k, v in labels.items()
                         if v["root_category"] == cat)
        lines.append(f"| `{cat}` | {count} | {', '.join(traces)} |")

    lines.append(f"\n## Sentinel detector coverage\n")
    lines.append("| Status | Count |")
    lines.append("|---|---|")
    for status, count in detector_counts.most_common():
        lines.append(f"| {status} | {count} |")

    lines.append(f"\n## Cross-trace clusters (hand-identified, not auto-derived)\n")
    for key, info in CLUSTERS.items():
        present = [t for t in info["traces"]
                   if f"taubench-retail-{t}" in labels]
        if not present:
            continue
        lines.append(f"**{info['label']}** — {len(present)} trace(s): {', '.join(sorted(present))}\n")

    covered = sum(1 for t in [t for c in CLUSTERS.values() for t in c["traces"]]
                  if f"taubench-retail-{t}" in labels)
    lines.append(f"\n*{covered} of {n} labeled traces fall into a named cluster above "
                  f"({covered/n:.0%} of labeled sample so far).*\n")

    out = "\n".join(lines)
    if a.out:
        Path(a.out).write_text(out)
        print(f"wrote {a.out}")
    else:
        print(out)


if __name__ == "__main__":
    main()
