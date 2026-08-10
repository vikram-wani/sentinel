import sys; sys.path.insert(0, "src")
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from sentinel.adapters.taubench import load_taubench_trace
from sentinel.localizer import analyze

# How many traces to analyze concurrently. Each one that has a live judge
# candidate makes a real network call to Anthropic, so this is bounded by
# their rate limit, not by CPU -- raise it if runs stay fast and error-free,
# lower it if you start seeing rate-limit errors in the failure list below.
MAX_WORKERS = 8

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


def analyze_one(r):
    """Runs in a worker thread. Returns (trace_id, report, error) so a single
    failed trace (rate limit, transient network error) doesn't take down the
    whole batch -- it gets reported and skipped, not silently dropped."""
    try:
        trace = load_taubench_trace(r)
        report = analyze(trace)
        return trace.trace_id, report, None
    except Exception as e:
        # trace_id isn't available if load_taubench_trace itself failed;
        # fall back to the raw task/trial so the failure is still traceable.
        fallback_id = f"taubench-retail-task{r.get('task_id')}-trial{r.get('trial')}"
        return fallback_id, None, str(e)


def run_batch(records, label):
    """Submits every record to the thread pool, prints lightweight progress
    (the exact thing that was missing before -- a long silent run and an
    actually-hung run look identical without this), and returns results in
    the same order as the input regardless of which finished first."""
    results = {}
    errors = []
    start = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(analyze_one, r): i for i, r in enumerate(records)}
        done = 0
        for future in as_completed(futures):
            tid, report, err = future.result()
            idx = futures[future]
            results[idx] = (tid, report)
            if err:
                errors.append((tid, err))
            done += 1
            if done % 20 == 0 or done == len(records):
                elapsed = time.time() - start
                print(f"  {label}: {done}/{len(records)} done, {elapsed:.0f}s elapsed", flush=True)
    ordered = [results[i] for i in range(len(records))]
    if errors:
        print(f"  {len(errors)} trace(s) failed to analyze (excluded from results below):")
        for tid, err in errors[:5]:
            print(f"    {tid}: {err[:150]}")
        if len(errors) > 5:
            print(f"    ... and {len(errors) - 5} more")
    return ordered


print(f"=== PRECISION: {len(passing)} passing traces ===")
passing_results = run_batch(passing, "precision")

false_positives = []
excluded_flags = []
analyzed_ids = set()
for tid, report in passing_results:
    if report is None:
        continue  # failed to load/analyze -- genuinely unknown, excluded from both sides
    analyzed_ids.add(tid)
    if report.verdict == "FAILED":
        cat = report.localization.root_category
        if tid in KNOWN_NOT_CLEAN:
            excluded_flags.append((tid, cat))
        else:
            false_positives.append((tid, cat))

# Denominator must reflect what was actually evaluated, not the static list
# length -- a trace that failed to analyze is neither confirmed clean nor
# confirmed a false positive, it's unknown, and belongs in neither count.
known_not_clean_analyzed = len(KNOWN_NOT_CLEAN & analyzed_ids)
clean_passing = len(analyzed_ids) - known_not_clean_analyzed
print(f"\nFlagged FAILED on traces we know are NOT clean (correct catches, excluded from FP count): {len(excluded_flags)}")
for tid, cat in excluded_flags:
    print(f"    {tid}: {cat}")
print(f"\nFalse positives (flagged FAILED on traces with no known issue): {len(false_positives)} / {clean_passing}")
fp_cat_counts = Counter(cat for _, cat in false_positives)
for cat, n in fp_cat_counts.most_common():
    print(f"    {cat}: {n}")
print(f"\nPrecision (on the {clean_passing} traces we have no reason to doubt): "
      f"{1 - len(false_positives)/clean_passing:.1%}")

print(f"\n=== COVERAGE: {len(failing)} failing traces ===")
failing_results = run_batch(failing, "coverage")

covered = 0
silent = []
cov_cat_counts = Counter()
analyzed_failing = 0
for tid, report in failing_results:
    if report is None:
        continue  # failed to analyze -- excluded, not counted as either covered or missed
    analyzed_failing += 1
    if report.verdict == "FAILED":
        covered += 1
        cov_cat_counts[report.localization.root_category] += 1
    else:
        silent.append(tid)

print(f"\nSentinel produced a finding: {covered} / {analyzed_failing} ({covered/analyzed_failing:.1%})")
print(f"Sentinel stayed silent (missed): {len(silent)} / {analyzed_failing} ({len(silent)/analyzed_failing:.1%})")
print("\nFindings by category, across all flagged failing traces:")
for cat, n in cov_cat_counts.most_common():
    print(f"    {cat}: {n}")
