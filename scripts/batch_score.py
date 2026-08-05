import sys; sys.path.insert(0, "src")
import json
from collections import Counter
from sentinel.adapters.taubench import load_taubench_trace
from sentinel.localizer import analyze

d = json.load(open("data/retail.json"))
passing = [r for r in d if r["reward"] == 1.0]
failing = [r for r in d if r["reward"] == 0.0]

# 4 traces we hand-verified as passing=1.0 but NOT actually clean (real issues
# found: task40-trial0, task108-trial0, task13-trial2, task3-trial3, task3-trial1
# -- note task3-trial1 is failing=0 already so not in the passing set anyway).
KNOWN_NOT_CLEAN = {
    "taubench-retail-task40-trial0",
    "taubench-retail-task108-trial0",
    "taubench-retail-task13-trial2",
    "taubench-retail-task3-trial3",
}

print(f"=== PRECISION: {len(passing)} passing traces ===")
false_positives = []
excluded_flags = []
for r in passing:
    trace = load_taubench_trace(r)
    report = analyze(trace)
    if report.verdict == "FAILED":
        cat = report.localization.root_category
        if trace.trace_id in KNOWN_NOT_CLEAN:
            excluded_flags.append((trace.trace_id, cat))
        else:
            false_positives.append((trace.trace_id, cat))

clean_passing = len(passing) - len(KNOWN_NOT_CLEAN)
print(f"Flagged FAILED on traces we know are NOT clean (correct catches, excluded from FP count): {len(excluded_flags)}")
for tid, cat in excluded_flags:
    print(f"    {tid}: {cat}")
print(f"\nFalse positives (flagged FAILED on traces with no known issue): {len(false_positives)} / {clean_passing}")
fp_cat_counts = Counter(cat for _, cat in false_positives)
for cat, n in fp_cat_counts.most_common():
    print(f"    {cat}: {n}")
print(f"\nPrecision (on the {clean_passing} traces we have no reason to doubt): "
      f"{1 - len(false_positives)/clean_passing:.1%}")

print(f"\n=== COVERAGE: {len(failing)} failing traces ===")
covered = 0
silent = []
cov_cat_counts = Counter()
for r in failing:
    trace = load_taubench_trace(r)
    report = analyze(trace)
    if report.verdict == "FAILED":
        covered += 1
        cov_cat_counts[report.localization.root_category] += 1
    else:
        silent.append(trace.trace_id)

print(f"Sentinel produced a finding: {covered} / {len(failing)} ({covered/len(failing):.1%})")
print(f"Sentinel stayed silent (missed): {len(silent)} / {len(failing)} ({len(silent)/len(failing):.1%})")
print("\nFindings by category, across all flagged failing traces:")
for cat, n in cov_cat_counts.most_common():
    print(f"    {cat}: {n}")
