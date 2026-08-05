"""Label helper for τ-bench trajectories.

Renders a trajectory in a form a human can actually label in ~5 minutes, and
emits a label stub to paste into the labels file.

This is a *viewer*, not an adapter. It deliberately does not import Sentinel
or run any detector — you must be able to label without the tool's output
visible, per the rubric.

Usage:
  python label_helper.py --file retail.json --stats
  python label_helper.py --file retail.json --sample 35 --seed 7 --list
  python label_helper.py --file retail.json --task 5 --trial 0
  python label_helper.py --file retail.json --task 5 --trial 0 --stub

  # Full, untruncated, readable in a browser instead of a terminal:
  python label_helper.py --file retail.json --task 5 --trial 0 --html
  python label_helper.py --file retail.json --sample 35 --seed 7 --html-out labeling_html
"""
from __future__ import annotations

import argparse
import html as htmlmod
import json
import random
import textwrap
from pathlib import Path

BOLD, DIM, YEL, GRN, RED, CYN, RESET = (
    "\033[1m", "\033[2m", "\033[33m", "\033[32m", "\033[31m", "\033[36m", "\033[0m"
)


def expected_actions(rec) -> list[dict]:
    ri = rec["info"].get("reward_info") or {}
    return ri.get("actions") or (rec["info"].get("task") or {}).get("actions") or []


def actual_tool_calls(rec) -> list[tuple[int, str, str]]:
    out = []
    for i, m in enumerate(rec["traj"]):
        for tc in (m.get("tool_calls") or []):
            out.append((i, tc["function"]["name"], tc["function"].get("arguments", "")))
    return out


def stratum_of(rec) -> str:
    exp = {a["name"] for a in expected_actions(rec)}
    act = {n for _, n, _ in actual_tool_calls(rec)}
    miss, extra = exp - act, act - exp
    if miss and extra:
        return "both"
    if miss:
        return "missing_only"
    if extra:
        return "extra_only"
    return "toolset_correct"


def render(rec, policy_chars: int = 600) -> str:
    L = []
    L.append(f"\n{BOLD}{'='*78}{RESET}")
    L.append(f"{BOLD}task_id={rec['task_id']}  trial={rec['trial']}  reward={rec['reward']}  "
             f"stratum={stratum_of(rec)}{RESET}")
    L.append(f"{BOLD}{'='*78}{RESET}\n")

    sys_msg = next((m for m in rec["traj"] if m.get("role") == "system"), None)
    if sys_msg:
        pol = (sys_msg.get("content") or "")[:policy_chars]
        L.append(f"{CYN}--- DOMAIN POLICY (first {policy_chars} chars — read this first) ---{RESET}")
        L.append(textwrap.fill(pol, 76, initial_indent="  ", subsequent_indent="  "))
        L.append(f"{DIM}  ...[truncated; use --policy-full for all of it, or --html for the full page]{RESET}\n")

    exp = expected_actions(rec)
    L.append(f"{GRN}--- EXPECTED ACTIONS (Sierra's ground truth) ---{RESET}")
    for i, a in enumerate(exp):
        kw = json.dumps(a.get("kwargs", {}))
        L.append(f"  {i+1}. {a['name']}({kw[:70]})")
    if not exp:
        L.append("  (none recorded)")
    L.append("")

    act = actual_tool_calls(rec)
    exp_names = {a["name"] for a in exp}
    L.append(f"{YEL}--- ACTUAL TOOL CALLS ---{RESET}")
    for idx, name, args in act:
        flag = "" if name in exp_names else f"  {RED}<- not in expected set{RESET}"
        L.append(f"  [step {idx}] {name}({args[:60]}){flag}")
    missing = exp_names - {n for _, n, _ in act}
    if missing:
        L.append(f"  {RED}NEVER CALLED: {sorted(missing)}{RESET}")
    L.append("")

    L.append(f"{BOLD}--- MESSAGE SEQUENCE (truncated per-line; use --html for full text) ---{RESET}")
    for i, m in enumerate(rec["traj"]):
        role = m.get("role")
        if role == "system":
            L.append(f"{DIM}[{i:>2}] system    (policy — shown above){RESET}")
            continue
        content = (m.get("content") or "").replace("\n", " ").strip()
        tcs = m.get("tool_calls") or []
        if tcs:
            for tc in tcs:
                fn = tc["function"]
                L.append(f"[{i:>2}] {YEL}TOOL_CALL{RESET} {fn['name']}({fn.get('arguments','')[:80]})")
            if content:
                L.append(f"      {DIM}(+ text: {content[:70]}){RESET}")
        elif role == "tool":
            err = content.lower().startswith("error")
            mark = f"{RED}ERROR{RESET} " if err else ""
            L.append(f"[{i:>2}] tool_res  {mark}{content[:90]}")
        else:
            label = "USER     " if role == "user" else "assistant"
            color = CYN if role == "user" else ""
            L.append(f"[{i:>2}] {color}{label}{RESET} {content[:100]}")
    L.append("")
    return "\n".join(L)


def stub(rec) -> str:
    key = f"taubench-retail-task{rec['task_id']}-trial{rec['trial']}"
    return json.dumps({key: {
        "root_category": "TODO",
        "root_step_index": -999,
        "rubric_code": "TODO",
        "fault_owner": "agent",
        "sentinel_has_detector": None,
        "labeler_confidence": "TODO",
        "notes": "",
        "alternative_considered": "",
    }}, indent=2)


# ---------------------------------------------------------------- HTML mode

_HTML_HEAD = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    --bg: #f7f8fa; --card: #ffffff; --ink: #1b2430; --muted: #5b6472;
    --border: #dde2e9; --green: #1f8a5f; --red: #cf3b3b; --amber: #c98a1f;
    --mono: 'Consolas','Menlo','Monaco',monospace;
  }}
  * {{ box-sizing: border-box; }}
  body {{ background: var(--bg); color: var(--ink); font-family: -apple-system,Segoe UI,Helvetica,Arial,sans-serif;
          max-width: 900px; margin: 0 auto; padding: 32px 24px 100px; line-height: 1.55; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .meta {{ font-family: var(--mono); font-size: 13px; color: var(--muted); margin-bottom: 24px; }}
  .stratum {{ display:inline-block; padding: 2px 10px; border-radius: 12px; background:#eef1f5; font-weight:600; }}
  section {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px;
             padding: 18px 22px; margin-bottom: 20px; }}
  section h2 {{ font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted);
                margin: 0 0 12px; }}
  .policy {{ white-space: pre-wrap; font-size: 14px; }}
  .action-row {{ font-family: var(--mono); font-size: 13.5px; padding: 4px 0; }}
  .missing {{ color: var(--red); font-weight: 600; }}
  .flag {{ color: var(--red); font-weight: 600; }}
  ol {{ margin: 0; padding-left: 22px; }}
  .msg {{ border-bottom: 1px solid var(--border); padding: 10px 0; display: flex; gap: 12px; }}
  .msg:last-child {{ border-bottom: none; }}
  .idx {{ font-family: var(--mono); color: var(--muted); font-size: 12px; width: 30px; flex-shrink:0; padding-top:3px; }}
  .role {{ font-family: var(--mono); font-size: 12px; font-weight: 700; width: 90px; flex-shrink:0; padding-top: 3px; }}
  .role-user {{ color: #2451d6; }}
  .role-assistant {{ color: var(--ink); }}
  .role-tool {{ color: var(--muted); }}
  .role-tool_call {{ color: var(--amber); }}
  .content {{ white-space: pre-wrap; font-size: 14px; flex: 1; }}
  .content.mono {{ font-family: var(--mono); font-size: 13px; }}
  .error {{ color: var(--red); font-weight: 700; }}
  .toolcall-badge {{ display:inline-block; background:#faf3e6; color:var(--amber); border:1px solid #c98a1f44;
                      border-radius: 6px; padding: 1px 8px; font-family: var(--mono); font-size:12.5px; margin-bottom:4px;}}
  .navbar {{ position: sticky; top: 0; background: var(--bg); padding: 10px 0; margin-bottom: 8px;
             border-bottom: 1px solid var(--border); font-family: var(--mono); font-size: 13px; }}
  .navbar a {{ color: #2451d6; text-decoration: none; margin-right: 16px; }}
  .stub {{ font-family: var(--mono); font-size: 12.5px; white-space: pre-wrap; background:#161b22; color:#c9d1d9;
           padding: 16px; border-radius: 8px; overflow-x:auto; }}
</style></head><body>
"""


def render_html(rec, nav_html: str = "") -> str:
    title = f"task {rec['task_id']} / trial {rec['trial']}"
    out = [_HTML_HEAD.format(title=htmlmod.escape(title))]
    if nav_html:
        out.append(nav_html)

    out.append(f"<h1>Task {rec['task_id']}, trial {rec['trial']}</h1>")
    out.append(f'<div class="meta">reward={rec["reward"]} &nbsp; '
               f'<span class="stratum">{stratum_of(rec)}</span></div>')

    sys_msg = next((m for m in rec["traj"] if m.get("role") == "system"), None)
    if sys_msg:
        pol = htmlmod.escape(sys_msg.get("content") or "")
        out.append(f'<section><h2>Domain policy (full text)</h2><div class="policy">{pol}</div></section>')

    exp = expected_actions(rec)
    out.append('<section><h2>Expected actions (Sierra\'s ground truth)</h2>')
    if exp:
        out.append("<ol>")
        for a in exp:
            kw = htmlmod.escape(json.dumps(a.get("kwargs", {})))
            out.append(f'<li class="action-row">{htmlmod.escape(a["name"])}({kw})</li>')
        out.append("</ol>")
    else:
        out.append("<div>(none recorded)</div>")
    out.append("</section>")

    act = actual_tool_calls(rec)
    exp_names = {a["name"] for a in exp}
    out.append('<section><h2>Actual tool calls</h2>')
    for idx, name, args in act:
        flag = "" if name in exp_names else ' <span class="flag">&larr; not in expected set</span>'
        out.append(f'<div class="action-row">[step {idx}] {htmlmod.escape(name)}'
                   f'({htmlmod.escape(args)}){flag}</div>')
    missing = exp_names - {n for _, n, _ in act}
    if missing:
        out.append(f'<div class="action-row missing">NEVER CALLED: {htmlmod.escape(str(sorted(missing)))}</div>')
    out.append("</section>")

    out.append('<section><h2>Full message sequence (nothing truncated)</h2>')
    for i, m in enumerate(rec["traj"]):
        role = m.get("role")
        if role == "system":
            out.append(f'<div class="msg"><div class="idx">{i}</div><div class="role role-tool">system</div>'
                       f'<div class="content">(policy shown above)</div></div>')
            continue
        content = htmlmod.escape(m.get("content") or "")
        tcs = m.get("tool_calls") or []
        if tcs:
            pieces = []
            for tc in tcs:
                fn = tc["function"]
                args = htmlmod.escape(fn.get("arguments", ""))
                pieces.append(f'<span class="toolcall-badge">{htmlmod.escape(fn["name"])}</span>'
                             f'<div class="content mono">{args}</div>')
            extra_text = f'<div class="content" style="margin-top:6px;color:var(--muted)">{content}</div>' if content else ""
            out.append(f'<div class="msg"><div class="idx">{i}</div><div class="role role-tool_call">TOOL_CALL</div>'
                       f'<div style="flex:1">{"".join(pieces)}{extra_text}</div></div>')
        elif role == "tool":
            err = content.lower().startswith("error")
            cls = "content mono error" if err else "content mono"
            out.append(f'<div class="msg"><div class="idx">{i}</div><div class="role role-tool">tool_res</div>'
                       f'<div class="{cls}">{content}</div></div>')
        else:
            rcls = "role-user" if role == "user" else "role-assistant"
            rlabel = "USER" if role == "user" else "assistant"
            out.append(f'<div class="msg"><div class="idx">{i}</div><div class="role {rcls}">{rlabel}</div>'
                       f'<div class="content">{content}</div></div>')
    out.append("</section>")

    out.append(f'<section><h2>Label stub (fill in, then paste into your labels file)</h2>'
               f'<div class="stub">{htmlmod.escape(stub(rec))}</div></section>')

    out.append("</body></html>")
    return "\n".join(out)


def generate_html_batch(records: list, out_dir: str):
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)

    files = []
    for r in records:
        tag = "PASS" if r["reward"] == 1 else stratum_of(r)
        fname = f"task{r['task_id']}_trial{r['trial']}.html"
        files.append((fname, r, tag))

    nav_links = " &nbsp;|&nbsp; ".join(
        f'<a href="{fn}">{r["task_id"]}/{r["trial"]} <span style="color:#999">[{tag}]</span></a>'
        for fn, r, tag in files
    )
    navbar = f'<div class="navbar">{nav_links} &nbsp;|&nbsp; <a href="index.html">index</a></div>'

    for fname, r, tag in files:
        html_out = render_html(r, nav_html=navbar)
        (d / fname).write_text(html_out, encoding="utf-8")

    index = [_HTML_HEAD.format(title="Labeling sample index")]
    index.append("<h1>Sample to label (35 traces)</h1>")
    index.append('<div class="meta">Click through in order. Read policy + expected actions + full message '
                 "sequence, decide root_category and root_step_index yourself, THEN paste the filled stub "
                 "into your labels file. Do not run Sentinel until all are labeled.</div>")
    index.append("<section><h2>Traces</h2><ol>")
    for fname, r, tag in files:
        index.append(f'<li class="action-row"><a href="{fname}">task {r["task_id"]}, trial {r["trial"]}</a>'
                    f' &nbsp; <span class="stratum">{tag}</span></li>')
    index.append("</ol></section></body></html>")
    (d / "index.html").write_text("\n".join(index), encoding="utf-8")

    return d / "index.html", len(files)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True)
    p.add_argument("--task", type=int)
    p.add_argument("--trial", type=int, default=0)
    p.add_argument("--sample", type=int, help="draw a stratified sample of N")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--list", action="store_true", help="list the sample only")
    p.add_argument("--stub", action="store_true", help="print label stub")
    p.add_argument("--stats", action="store_true")
    p.add_argument("--policy-full", action="store_true")
    p.add_argument("--html", action="store_true", help="write one full untruncated HTML file for --task/--trial")
    p.add_argument("--html-out", metavar="DIR", help="write the whole --sample as HTML files into DIR, plus an index")
    p.add_argument("--find", metavar="TEXT", help="search message text, tool call arguments, AND "
                   "reward_info.actions for an identifier -- covers cases where it only appears in "
                   "ground truth, never spoken in the conversation itself")
    a = p.parse_args()

    data = json.load(open(a.file))

    if a.find:
        needle = a.find
        hits = []
        for r in data:
            found_in = set()
            for m in r["traj"]:
                c = m.get("content") or ""
                if isinstance(c, str) and needle in c:
                    found_in.add("message text")
                for tc in (m.get("tool_calls") or []):
                    if needle in tc["function"].get("arguments", ""):
                        found_in.add("tool call args")
            ri = r["info"].get("reward_info") or {}
            for act in (ri.get("actions") or []):
                if needle in json.dumps(act):
                    found_in.add("reward_info.actions (ground truth only)")
            if found_in:
                hits.append((r["task_id"], r["trial"], r["reward"], sorted(found_in)))
        print(f"\n{BOLD}Search for {needle!r}: {len(hits)} match(es){RESET}\n")
        for tid, trial, reward, where in hits:
            print(f"  task_id={tid} trial={trial} reward={reward}  found in: {', '.join(where)}")
        print()
        return

    if a.stats:
        fails = [r for r in data if r["reward"] == 0]
        passes = [r for r in data if r["reward"] == 1]
        from collections import Counter
        strata = Counter(stratum_of(r) for r in fails)
        print(f"\n{BOLD}{a.file}{RESET}")
        print(f"  total trajectories : {len(data)}")
        print(f"  passed (reward=1)  : {len(passes)}   <- free false-positive check")
        print(f"  failed (reward=0)  : {len(fails)}   <- free coverage check")
        print(f"\n  {BOLD}failure strata:{RESET}")
        for k, v in strata.most_common():
            print(f"    {k:<18} {v:>4}  ({v/len(fails):.0%})")
        print()
        return

    if a.sample:
        fails = [r for r in data if r["reward"] == 0]
        passes = [r for r in data if r["reward"] == 1]
        rng = random.Random(a.seed)
        plan = {"extra_only": 10, "missing_only": 5, "both": 5, "toolset_correct": 10}
        picked = []
        for stratum, n in plan.items():
            pool = [r for r in fails if stratum_of(r) == stratum]
            picked += rng.sample(pool, min(n, len(pool)))
        picked += rng.sample(passes, min(5, len(passes)))

        if a.html_out:
            index_path, n = generate_html_batch(picked, a.html_out)
            abs_path = index_path.resolve()
            print(f"\n{BOLD}Wrote {n} HTML files + index to {a.html_out}/{RESET}")
            print(f"Full path: {abs_path}")
            print(f"Open in Windows Explorer or a browser address bar:")
            print(f"  \\\\wsl$\\Ubuntu{str(abs_path).replace('/', chr(92))}")
            print(f"{DIM}(if that doesn't resolve, try \\\\wsl.localhost\\Ubuntu instead of \\\\wsl$\\Ubuntu){RESET}\n")
            return

        print(f"\n{BOLD}Stratified sample (seed={a.seed}, n={len(picked)}){RESET}\n")
        for r in picked:
            tag = "PASS" if r["reward"] == 1 else stratum_of(r)
            print(f"  --task {r['task_id']} --trial {r['trial']}   [{tag}]")
        print(f"\n{DIM}Label these in order. Do not run Sentinel until all are labeled.{RESET}\n")
        return

    if a.task is None:
        p.error("provide --task, or use --sample / --stats")

    rec = next((r for r in data if r["task_id"] == a.task and r["trial"] == a.trial), None)
    if rec is None:
        raise SystemExit(f"no trajectory with task_id={a.task} trial={a.trial}")

    if a.html:
        out_path = Path(f"task{a.task}_trial{a.trial}.html")
        out_path.write_text(render_html(rec), encoding="utf-8")
        print(f"\n{BOLD}Wrote {out_path}{RESET} — open it in a browser for the full, untruncated trace.\n")
        return

    print(render(rec, 100_000 if a.policy_full else 600))
    if a.stub:
        print(f"{BOLD}--- label stub ---{RESET}")
        print(stub(rec))


if __name__ == "__main__":
    main()
