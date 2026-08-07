# Sentinel — Roadmap

A living checklist, not a snapshot. Update this file as items get done, get
scoped more precisely, or new ones get discovered, the same way `STUDY.md`
grew rules and sections mid-project instead of being written once and left
alone.

Last updated: Day 4, post-Signal-B (shipped, stability-confirmed).

---

## Recently completed

- [x] **Signal B** — the continuation-cue completeness check. Shipped, and
      the story behind it is worth keeping, not just the checkbox. First
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

## In progress

*(nothing right now)*

## Scoped, known, not started

- [ ] **`fabricated_specifics`'s arithmetic gap.** A correctly *computed*
      value (the $52.36 gift card balance) gets flagged as fabricated
      because it was never grounded in a single retrieved number, only in
      arithmetic the agent did correctly without calling `calculate()`.
      Logged in `STUDY.md`, not fixed. Distinct from the sign-flip bug
      already fixed earlier Day 4. Currently blocking Signal A's own
      correct finding from winning root on `task21`.
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
      Deserves a dedicated look, not a reactive fix made mid-debug.
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

- [ ] Signal A's own writeup. The four-fix post covered the earlier work;
      the live completeness-detector validation, the shoe catch, the
      keyboard false positive, the same-day fix, is a good story that
      hasn't been told publicly yet.

---

## Suggested order, as of this update

1. `fabricated_specifics` arithmetic gap — still actively costing both
   Signal A and Signal B a correct root selection on `task21`, not just a
   documented gap anymore, now blocking two shipped detectors instead of one
2. Entity resolution, the other Tier 3 extension (`task102`'s shape) —
   Signal A and B closed out the completeness half of the original plan;
   this is the remaining half, not started at all
3. Root-priority question and retail-generalization question — real, but
   bigger than a coding session; scheduled on purpose, not squeezed in
4. Everything else, as it comes up
