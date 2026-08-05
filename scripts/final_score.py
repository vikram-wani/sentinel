import sys; sys.path.insert(0, "src")
import json
from sentinel.adapters.taubench import load_taubench_trace
from sentinel.localizer import analyze

raw = json.load(open("data/retail.json"))
labels = json.loads(open("examples/labels/taubench_ground_truth.json").read())
raw_by_id = {f"taubench-retail-task{r['task_id']}-trial{r['trial']}": r for r in raw}

real_failures = []   # our label says an agent decision is the root
no_fault = []        # our label says grading_artifact / root_step_index -1

for tid, gt in labels.items():
    r = raw_by_id[tid]
    trace = load_taubench_trace(r)
    report = analyze(trace)
    sentinel_cat = report.localization.root_category if report.localization else None
    sentinel_step = report.localization.root_step_index if report.localization else None

    row = {
        "trace_id": tid, "gt_cat": gt["root_category"], "gt_step": gt["root_step_index"],
        "gt_has_detector": gt["sentinel_has_detector"],
        "sentinel_verdict": report.verdict, "sentinel_cat": sentinel_cat, "sentinel_step": sentinel_step,
    }
    if gt["root_category"] == "grading_artifact":
        no_fault.append(row)
    else:
        real_failures.append(row)

print(f"=== REAL FAILURES: {len(real_failures)} traces (our label found a genuine agent fault) ===\n")
cat_match = sum(1 for x in real_failures if x["sentinel_cat"] == x["gt_cat"])
silent = sum(1 for x in real_failures if x["sentinel_verdict"] == "HEALTHY")
wrong_cat = len(real_failures) - cat_match - silent

print(f"Category matches our label exactly : {cat_match} / {len(real_failures)}")
print(f"Sentinel stayed silent (missed)     : {silent} / {len(real_failures)}")
print(f"Sentinel flagged, wrong category    : {wrong_cat} / {len(real_failures)}")

print(f"\nBroken down by whether we already knew Sentinel has a detector for this category:")
for has_det in [True, False, None]:
    subset = [x for x in real_failures if x["gt_has_detector"] == has_det]
    if not subset: continue
    m = sum(1 for x in subset if x["sentinel_cat"] == x["gt_cat"])
    print(f"  has_detector={has_det}: {m}/{len(subset)} category matches")

step_matches = [x for x in real_failures if x["sentinel_cat"] == x["gt_cat"]]
step_agree = sum(1 for x in step_matches if x["sentinel_step"] == x["gt_step"])
print(f"\nOf the {len(step_matches)} traces where category matched, "
      f"step index also matched exactly: {step_agree} / {len(step_matches)}")
print("(Reported separately on purpose -- Sentinel's anchor logic assumes a PLAN step")
print(" tau-bench traces never have, so this number is expected to be weak regardless")
print(" of whether the category-level diagnosis was right.)")

print(f"\nMismatches, for the record:")
for x in real_failures:
    if x["sentinel_cat"] != x["gt_cat"]:
        print(f"  {x['trace_id']}: ours={x['gt_cat']} (detector={x['gt_has_detector']}) "
              f"-> sentinel={x['sentinel_cat'] or 'HEALTHY'}")

print(f"\n\n=== NO-FAULT TRACES: {len(no_fault)} traces (our label says grading_artifact, agent did nothing wrong) ===\n")
correct_healthy = sum(1 for x in no_fault if x["sentinel_verdict"] == "HEALTHY")
false_positive = len(no_fault) - correct_healthy
print(f"Sentinel correctly says HEALTHY : {correct_healthy} / {len(no_fault)}")
print(f"Sentinel incorrectly says FAILED : {false_positive} / {len(no_fault)}")
for x in no_fault:
    if x["sentinel_verdict"] != "HEALTHY":
        print(f"  FALSE POSITIVE: {x['trace_id']} -> sentinel flagged {x['sentinel_cat']}")
