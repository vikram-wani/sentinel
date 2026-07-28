"""Sentinel CLI.

  sentinel analyze <trace.json>   Localize root cause, emit report + regression test + eval spec
  sentinel demo                   Run analysis on the bundled labeled traces (no keys, no config)
  sentinel bench                  Score Sentinel's localization accuracy against ground-truth labels

`bench` is not an afterthought — it is the tool evaluating itself. A root-cause
tool that can't report its own localization accuracy is exactly the kind of
unmeasured judge it exists to replace.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .parser import load_trace
from .localizer import analyze
from .generators import render_markdown, render_pytest, render_eval_spec

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"

BOLD, DIM, RED, GREEN, YELLOW, RESET = "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[0m"


def _analyze_one(path: Path, outdir: Path | None, quiet: bool = False):
    trace = load_trace(path)
    report = analyze(trace)
    if not quiet:
        _print_console(report, trace)
    if outdir:
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / f"{trace.trace_id}.report.md").write_text(render_markdown(report, trace))
        (outdir / f"test_{trace.trace_id.replace('-', '_')}.py").write_text(render_pytest(report, trace))
        (outdir / f"{trace.trace_id}.eval.yaml").write_text(render_eval_spec(report, trace))
        if not quiet:
            print(f"{DIM}artifacts -> {outdir}/{RESET}\n")
    return report


def _print_console(report, trace):
    color = RED if report.verdict == "FAILED" else GREEN
    print(f"\n{BOLD}{trace.trace_id}{RESET}  {color}{report.verdict}{RESET}")
    if report.localization:
        loc = report.localization
        print(f"  {BOLD}Root cause:{RESET} step {loc.root_step_index} — {loc.root_category} "
              f"{DIM}({loc.root_finding.detector}, conf {loc.root_finding.confidence:.2f}){RESET}")
        print(f"    {loc.root_finding.evidence[0]}")
        print(f"  {BOLD}Fix location:{RESET} {loc.fix_location}")
        if loc.do_not_modify:
            print(f"  {BOLD}Do not modify:{RESET} {', '.join(loc.do_not_modify)}")
        if loc.propagation:
            print(f"  {DIM}Propagation: " + " -> ".join(f.category for f in loc.propagation) + RESET)
    else:
        print(f"  {DIM}No deterministic findings.{RESET}")


def cmd_analyze(args):
    _analyze_one(Path(args.trace), Path(args.out) if args.out else None)


def _tier_status_line() -> str:
    from .judge import judge_available
    if judge_available():
        return f"{GREEN}Tier 3 (LLM judge) active{RESET} — ANTHROPIC_API_KEY detected"
    return f"{DIM}Tier 3 (LLM judge) inactive{RESET} — running Tiers 1-2 only (deterministic + heuristic, zero keys)"


def cmd_demo(args):
    traces = sorted((EXAMPLES / "traces").glob("*.json"))
    print(f"\n{BOLD}Sentinel demo — {len(traces)} bundled traces{RESET}")
    print(f"  {_tier_status_line()}\n")
    for t in traces:
        _analyze_one(t, Path(args.out) if args.out else None)


def cmd_bench(args):
    """Localization accuracy vs hand-written ground truth labels."""
    traces = sorted((EXAMPLES / "traces").glob("*.json"))
    labels = json.loads((EXAMPLES / "labels" / "ground_truth.json").read_text())
    total = cat_hits = step_hits = 0
    rows = []
    for t in traces:
        trace = load_trace(t)
        gt = labels.get(trace.trace_id)
        if gt is None:
            continue
        report = analyze(trace)
        pred_cat = report.localization.root_category if report.localization else "none"
        pred_step = report.localization.root_step_index if report.localization else -1
        cat_ok = pred_cat == gt["root_category"]
        step_ok = pred_step == gt["root_step_index"]
        total += 1
        cat_hits += cat_ok
        step_hits += step_ok
        rows.append((trace.trace_id, gt["root_category"], pred_cat, cat_ok, gt["root_step_index"], pred_step, step_ok))

    print(f"\n{BOLD}Sentinel self-benchmark: localization vs ground truth ({total} labeled traces){RESET}")
    print(f"  {_tier_status_line()}\n")
    for tid, gcat, pcat, cok, gstep, pstep, sok in rows:
        mark = f"{GREEN}✓{RESET}" if (cok and sok) else f"{RED}✗{RESET}"
        print(f"  {mark} {tid:<34} category: {gcat:<20} -> {pcat:<20} "
              f"step: {gstep} -> {pstep}")
    print(f"\n  Root-cause category accuracy : {BOLD}{cat_hits}/{total}{RESET}")
    print(f"  Root-cause step accuracy     : {BOLD}{step_hits}/{total}{RESET}")
    print(f"\n{DIM}Deterministic detectors (Tiers 1-2) cannot flip on identical input.")
    print(f"Tier 3, when active, is a model call and may vary run to run.{RESET}\n")
    if args.fail_under and total and (cat_hits / total) < args.fail_under:
        sys.exit(1)


def main(argv=None):
    if os.name == "nt":
        os.system("")  # enable ANSI escape codes in legacy Windows consoles
    p = argparse.ArgumentParser(prog="sentinel", description="AI Reliability Engineer: root-cause localization for agent failures.")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="Analyze a single trace")
    a.add_argument("trace")
    a.add_argument("--out", help="Directory for report/test/eval artifacts")
    a.set_defaults(func=cmd_analyze)

    d = sub.add_parser("demo", help="Analyze bundled labeled traces (no keys needed)")
    d.add_argument("--out", help="Directory for artifacts")
    d.set_defaults(func=cmd_demo)

    b = sub.add_parser("bench", help="Score localization accuracy against ground truth")
    b.add_argument("--fail-under", type=float, default=None, help="Exit 1 if category accuracy below this fraction")
    b.set_defaults(func=cmd_bench)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
