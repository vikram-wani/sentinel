# Sentinel — Roadmap

A living checklist, not a snapshot. Update this file as items get done, get
scoped more precisely, or new ones get discovered, the same way `STUDY.md`
grew rules and sections mid-project instead of being written once and left
alone.

Last updated: Day 4, post-arithmetic-fix and Signal B redesign (both shipped, both verified at scale).

---

## Recently completed

- [x] **Signal B** — the continuation-cue completeness check, first version.
      Shipped, and the story is worth keeping, not just the checkbox. First
      live test caught two things at once: it correctly found a real
      omission (a gift card balance inquiry the user asked for, with no
      numeric ID at all, exactly the shape Signal A structurally can't
      catch), and it exposed that Signal A's earlier keyboard false
      positive fix hadn't actually been confirmed live before Signal B
      work started. The first fix attempt (an abstract instruction in the
      prompt) was present in the code but didn't reliably change the
      judge's behavior. A second attempt, adding a concrete worked example
      to the prompt instead of just restating the rule, did. Confirmed
      stable across 7 consecutive live runs, not just one good pass, a
      stronger bar than Signal A originally got. Zero regression on the
      14-trace benchmark.

- [x] **`fabricated_specifics`'s arithmetic gap, closed.** A correctly
      computed value (task21's $52.36 gift card balance, derived from
      86 - 268.77 + 235.13, three grounded numbers, not two) was being
      flagged as fabricated because it was never itself retrieved as a
      single value. Fixed by checking every 2- and 3-number signed
      combination of grounded values, not just direct matches. Stops at 3
      terms on purpose: real cost (30-120ms per trace, measured, not
      estimated), and going further would raise the risk of a coincidental
      match. Verified: zero regression on the 14-trace benchmark, `task21`
      now resolves cleanly with `fabricated_specifics` no longer firing at
      all, not just losing root selection.

- [x] **Signal B's real design gap, found and fixed.** The arithmetic fix
      unmasked a second, bigger problem: precision on the full 274-trace
      passing set dropped to 71.2% with 53 false positives from
      `incomplete_arguments`, all traced to two structural gaps in Signal
      B. It only ever checked the *last* consequential call in a trace
      (wrong when a task has several independent, separately-executed
      requests, like `task23`'s helmet/luggage/grill), and it only ever
      showed the judge the user's turns, never the agent's (wrong when a
      request gets resolved through dialogue alone, like `task2`'s
      withdrawn cleaner request or `task3`'s narrowed "all orders"). Fixed
      by aggregating every consequential call across the trace and handing
      the judge the full transcript, both sides, plus an explicit
      instruction that correctly-resolved dialogue isn't an omission.
      Verified directly against `task21`, `task23`, `task2`, and `task3`
      before trusting it, then confirmed at scale: precision recovered to
      82.5-83.6% (small variation is expected Tier 3 run-to-run noise, not
      a bug), coverage held at 73.1%.

- [x] **Batch scoring parallelized.** The original script analyzed one
      trace at a time; with two live completeness signals now making real
      judge calls, a full run had gotten slow enough to look hung. Rebuilt
      with a thread pool (8 concurrent workers, adjustable), since every
      judge call is I/O-bound waiting on network, not CPU-bound. Confirmed
      against a sequential baseline (~2.5x speedup on a mocked test) and
      confirmed producing consistent real results, 24 seconds for the full
      182-trace coverage section with live progress, versus a sequential
      run long enough to prompt an attempted cancel. Also fixed a real bug
      caught during testing, not assumed away: a single trace failing to
      analyze was correctly excluded from the false-positive count but the
      denominator wasn't shrinking to match, which would have quietly
      under-reported precision if anything failed mid-run.

## In progress / open

- [ ] **~19-22 remaining `incomplete_arguments` false positives, not yet
      diagnosed.** The Signal B redesign fixed the three found cases
      (`task2`, `task3`, `task23`) and cut false positives roughly in half,
      but didn't reach zero. At least one more distinct pattern is still
      producing false positives on the passing set. Next real diagnostic
      step: pull fresh examples from the current false-positive list the
      same way the first three were found, don't assume it's the same bug
      recurring until checked.

- [ ] **Entity resolution, the other Tier 3 extension** (`task102`'s
      shape). "Of these observed candidates, is this the one the user
      meant." Completeness detection (`task21`'s shape) is done; this is
      the other half of the same original plan, not started.

## Open design questions, bigger than a single fix

- [ ] **The root-priority rule.** A correct, judge-confirmed Tier 3 finding
      lost to a deterministic false positive on `task21`, purely because
      deterministic findings always outrank probabilistic ones regardless
      of step order. That's the architecture working as designed, but now
      that Tier 3 findings can carry real confirmed reasoning, is that
      still the right rule? Flagged explicitly in `STUDY.md` as unresolved.
      Deserves a dedicated look, not a reactive fix made mid-debug. Now
      moot for `task21` specifically since `fabricated_specifics` no
      longer fires there at all, but the underlying architectural question
      is still open and will resurface on some other trace eventually.
- [ ] **Does any of this generalize past retail?** Every fix, every number
      from Day 4 came from tau-bench's retail domain. Airline data exists
      in the same benchmark, never touched. Open question: is
      `ignored_tool_error`'s fix tuned to retail's specific patterns, or
      general in a way that would hold up elsewhere.
- [ ] **Stratified sample vs. random sample.** The 35 labels were
      stratified by failure type on purpose, not randomly drawn. Coverage
      and precision on a fully random sample could differ from what's been
      measured. Named explicitly as unmeasured in `STUDY.md`.

## Permanent, documented limits (not fixable, just known)

- `context_overflow` — can't be tested against tau-bench at all; the data
  reports no token counts.
- `wrong_tool` via `forbidden_tools` inference — inferring "this tool is
  wrong given this order's status" was never attempted; the adapter leaves
  `forbidden_tools` empty on purpose.

These aren't bugs to chase. They're documented so nobody rediscovers them
and burns time before checking here first.

## Bigger roadmap, not urgent

- [ ] LangSmith / OpenTelemetry / OpenAI Responses trace adapters — the
      other trace formats the README has committed to as "next milestone"
      since Day 1. Tau-bench is the first real adapter built; the pattern
      (one `raw -> Trace` function per source) should make the next ones
      faster, but none are started.

## Content, lower priority than the engineering, still part of the cadence

- [ ] Signal A's and Signal B's own writeup. The four-fix post covered
      earlier work; the live completeness-detector validation, the shoe
      catch, the keyboard false positive, the task23/task2/task3 false
      positives and the transcript redesign that fixed them, is a good,
      concrete story that hasn't been told publicly yet.

---

## Suggested order, as of this update

1. Diagnose the ~19-22 remaining `incomplete_arguments` false positives —
   the freshest, most concrete open item, and the one most likely to have
   another real, fixable pattern underneath it
2. Entity resolution, the other Tier 3 extension (`task102`'s shape) —
   the remaining half of the original two-gap plan, not started at all
3. Root-priority question and retail-generalization question — real, but
   bigger than a coding session; scheduled on purpose, not squeezed in
4. Everything else, as it comes up

---

## Notes

- The `patch_*.py` and `study_insert_*.py` scripts in the repo root are
  kept on purpose, not clutter, they're a record of exactly how each fix
  landed (safe find-and-replace with a check-first guard, same pattern
  every time). Skip them when reading the codebase; they're process
  history, not part of the running tool.

This file reflects the real, current state of the repo, not a plan.
`sentinel bench` at 14/14, precision at 82.5-83.6% and coverage at 73.1% on
the full tau-bench batch, all code committed. Read this file first at the
start of any new session rather than reconstructing status from memory.
