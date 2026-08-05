"""Adapter: raw tau-bench trajectory record -> Sentinel's normalized Trace.

The one constraint that overrides every other design choice here: Step.index
must equal the message's original position in tau-bench's raw `traj` list,
exactly. All 35 hand-labeled ground-truth entries in this project reference
specific tau-bench step numbers (e.g. "root_step_index: 16" means literally
raw_record["traj"][16]). If this adapter renumbers steps, every one of those
labels silently stops meaning what it says, and the whole day's labeling work
becomes unscoreable. Every other decision below is negotiable; this one isn't.

Known, deliberate simplifications (see STUDY.md for the reasoning):
- expected_tools is populated from reward_info["actions"] filtered to a
  whitelist of consequential (state-mutating) tool names, not the full
  action list. Read-only calls (auth, lookups) are excluded on purpose:
  including them would flag reasonable variation in HOW an agent gathers
  information as if it were a missing required action, which is exactly the
  false-positive shape found and rejected during labeling (see task32,
  task33-trial0 notes). Duplicates are preserved, so a tool required twice
  (e.g. cancel_pending_order for two different orders) is listed twice,
  matching the Counter-based comparison in detect_missing_tool.
- forbidden_tools is left empty. Inferring "this tool is wrong given this
  order's status" requires cross-referencing tool arguments against
  retrieved state, which this adapter does not attempt. wrong_tool will not
  fire on tau-bench data as a result -- a known, documented gap, not a bug.
- context_overflow's token budget is left unset; tau-bench does not report
  token counts, so this detector cannot apply to this data at all.
- retrieval-based detectors (empty_retrieval, ungrounded_answer) will rarely
  or never fire: tau-bench retail is tool-calling, not RAG, so there are no
  StepType.RETRIEVAL steps in adapted traces.
"""
from __future__ import annotations

import json

from ..schema import Expectations, Step, StepType, Trace

CONSEQUENTIAL_TOOLS = {
    "cancel_pending_order",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "exchange_delivered_order_items",
    "return_delivered_order_items",
    "transfer_to_human_agents",
}


def _try_json(text):
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def load_taubench_trace(record: dict) -> Trace:
    trace_id = f"taubench-retail-task{record['task_id']}-trial{record['trial']}"
    steps: list[Step] = []

    # Map tool_call_id -> tool name, so TOOL_RESULT steps can be named even
    # when the tau-bench tool message itself omits an explicit "name" field.
    call_id_to_name: dict[str, str] = {}

    for i, msg in enumerate(record["traj"]):
        role = msg.get("role")

        if role == "system":
            continue  # policy text; no Sentinel step type fits, and no
                       # ground-truth label in this project ever targets it

        elif role == "user":
            steps.append(Step(index=i, type=StepType.USER, input=msg.get("content")))

        elif role == "assistant":
            tool_calls = msg.get("tool_calls") or []
            for tc in tool_calls:
                fn = tc["function"]
                name = fn["name"]
                args = _try_json(fn.get("arguments", "{}"))
                call_id_to_name[tc.get("id", "")] = name
                steps.append(Step(index=i, type=StepType.TOOL_CALL, name=name, input=args))
            content = msg.get("content")
            if content:  # combined tool-call + text turns get both steps, same index
                steps.append(Step(index=i, type=StepType.ASSISTANT, output=content))

        elif role == "tool":
            name = msg.get("name") or call_id_to_name.get(msg.get("tool_call_id", ""))
            raw = msg.get("content")
            parsed = _try_json(raw)
            error = raw if isinstance(raw, str) and raw.strip().lower().startswith("error") else None
            steps.append(Step(index=i, type=StepType.TOOL_RESULT, name=name, output=parsed, error=error))

    # Ground truth for expectations: filter to consequential tools only,
    # preserving multiplicity (a tool needed twice must appear twice).
    reward_info = record.get("info", {}).get("reward_info") or {}
    gt_actions = reward_info.get("actions") or (record.get("info", {}).get("task") or {}).get("actions") or []
    expected_tools = [a["name"] for a in gt_actions if a["name"] in CONSEQUENTIAL_TOOLS]

    return Trace(
        trace_id=trace_id,
        app="taubench-retail",
        steps=steps,
        expectations=Expectations(
            expected_tools=expected_tools,
            forbidden_tools=[],
            must_be_grounded=True,
        ),
        meta={
            "task_id": record["task_id"],
            "trial": record["trial"],
            "tau_reward": record.get("reward"),
        },
    )
