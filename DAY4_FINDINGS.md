# Day 4 Findings Log

*Auto-generated from `taubench_ground_truth.json` — 19 traces labeled. Regenerate with `python scripts/generate_findings_log.py`, never hand-edit.*

## Root cause categories

| Category | Count | Traces |
|---|---|---|
| `missing_tool` | 9 | task111-trial1, task13-trial0, task22-trial2, task23-trial3, task48-trial0, task55-trial0, task76-trial3, task81-trial0, task93-trial0 |
| `wrong_tool_argument` | 5 | task21-trial0, task28-trial1, task72-trial2, task80-trial2, task83-trial0 |
| `ordering_error` | 3 | task41-trial2, task98-trial0, task98-trial3 |
| `grading_artifact` | 1 | task24-trial2 |
| `wrong_tool` | 1 | task102-trial0 |

## Sentinel detector coverage

| Status | Count |
|---|---|
| no detector | 9 |
| has detector | 9 |
| n/a | 1 |

## Cross-trace clusters (hand-identified, not auto-derived)

**Stops a required search/workflow after partial progress** — 8 trace(s): task102-trial0, task111-trial1, task22-trial2, task23-trial3, task55-trial0, task76-trial3, task81-trial0, task83-trial0

**Claims a false blocker, halts before any real work begins** — 3 trace(s): task13-trial0, task48-trial0, task93-trial0

**Two individually-correct calls in the wrong order; first locks out the second** — 3 trace(s): task41-trial2, task98-trial0, task98-trial3

**Value/entity is real and grounded, applied to the wrong target** — 4 trace(s): task21-trial0, task28-trial1, task80-trial2, task83-trial0


*18 of 19 labeled traces fall into a named cluster above (95% of labeled sample so far).*
