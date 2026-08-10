"""Tier 3 — the caged LLM judge.

Opt-in. Only ever called on candidates Tier 2 already flagged — never on a
whole trace, never as a first pass. Scoped to exactly one falsifiable
question: does ANSWER contradict a specific claim in EVIDENCE? Not "is this
answer good." Not "rate this response." One question, two short text spans.

If ANTHROPIC_API_KEY isn't set, this module is inert: callers check
judge_available() and fall back to Tier 2's unconfirmed candidates. Sentinel's
core promise — zero setup, zero keys, `sentinel demo` just works — never
depends on this file executing successfully.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from .detectors.heuristic import ContradictionCandidate

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # judge extras not installed — judge_available() will correctly report False

SYSTEM_PROMPT = """You are a narrow contradiction checker for an AI reliability tool.
You will be given two things: EVIDENCE (text retrieved by an agent)
and ANSWER (the agent's final response to a user).

Your only job: does ANSWER state something that directly contradicts
a claim in EVIDENCE? Do not evaluate tone, completeness, or style.
Do not flag the answer for anything other than a direct factual
contradiction with the evidence provided.

Respond in this exact format:
VERDICT: [CONTRADICTS or CONSISTENT]
CONFIDENCE: [0.0-1.0]
EVIDENCE_CLAIM: [the specific claim in evidence, quoted or closely paraphrased]
ANSWER_CLAIM: [the specific claim in the answer that conflicts with it]
REASONING: [one sentence]

If ANSWER does not address the same topic as EVIDENCE, or if there is
no direct contradiction — including cases where the evidence states an
exception that the answer correctly applies — respond CONSISTENT."""

USER_TEMPLATE = """EVIDENCE:
{evidence}

ANSWER:
{answer}"""

_VERDICT_RE = re.compile(r"VERDICT:\s*(CONTRADICTS|CONSISTENT)", re.IGNORECASE)
_CONF_RE = re.compile(r"CONFIDENCE:\s*([0-9.]+)")
_REASON_RE = re.compile(r"REASONING:\s*(.+)")


@dataclass
class JudgeVerdict:
    contradicts: bool
    confidence: float
    reasoning: str
    raw: str


def judge_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def judge_candidate(candidate: ContradictionCandidate) -> JudgeVerdict | None:
    """Returns None if the judge is unavailable or the call fails — callers
    must treat None as 'fall back to the unconfirmed Tier 2 candidate',
    never as 'assume consistent'. Silence here means 'couldn't check', not
    'checked and fine'."""
    if not judge_available():
        return None

    try:
        import anthropic
    except ImportError:
        return None

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=200,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": USER_TEMPLATE.format(
                    evidence=candidate.evidence_sentence,
                    answer=candidate.answer_text,
                ),
            }],
        )
        text = response.content[0].text
    except Exception:
        # Network/API failure: fall back gracefully, don't crash the run.
        return None

    verdict_match = _VERDICT_RE.search(text)
    conf_match = _CONF_RE.search(text)
    reason_match = _REASON_RE.search(text)
    if not verdict_match:
        return None

    return JudgeVerdict(
        contradicts=verdict_match.group(1).upper() == "CONTRADICTS",
        confidence=float(conf_match.group(1)) if conf_match else 0.7,
        reasoning=reason_match.group(1).strip() if reason_match else "",
        raw=text,
    )

# ---------------------------------------------------------------------------
# Completeness checker. A second, separate narrow question -- not a rewrite
# of the contradiction checker above. Same discipline: one falsifiable
# question, two short inputs, opt-in, never a first pass. See
# completeness_heuristic.py for why this exists and what it deliberately
# does not try to check.

SYSTEM_PROMPT_COMPLETENESS = """You are a narrow completeness checker for an AI reliability tool.

You will be given USER_REQUEST (the full conversation, both the customer's
and the agent's turns, in order) and ACTION_TAKEN (every consequential
action the agent actually executed, as a list -- there may be one action or
several).

Your only job: does ACTION_TAKEN, taken together, address everything the
user asked for, or did the user ask for a change that no action in the list
reflects at all? A request can be fully satisfied by any single action in
the list -- check the whole list, not just the last entry.

The conversation may show a request being withdrawn, narrowed, or resolved
through dialogue alone, before any action was needed. If the agent
disclosed a constraint and the user accepted a narrower scope, or the agent
already investigated and reported a confirmed answer the user accepted
without objection, that request is settled. Do not flag it as incomplete
just because no corresponding action exists -- correctly resolved dialogue
is not an omission.

Important: retail items commonly have more than one valid identifier for the
same physical item (a product_id shared across variants, and a specific
item_id for the exact variant). The user may reference an item by either
one. A mismatch between which identifier the user typed and which identifier
appears in ACTION_TAKEN is NOT by itself evidence of an omission -- check
whether the outcome the user asked for (the item being changed TO, e.g. a
new_item_id, new address, or new value) is present in ACTION_TAKEN. If the
target value matches what the user requested, the item was addressed, even
if the specific source identifier they typed doesn't appear verbatim.

Worked example, read this before answering:
USER_REQUEST: "USER: change product 1656367028 to 1421289881"
ACTION_TAKEN: [{"item_ids": ["1340995114"], "new_item_ids": ["1421289881"]}]
The source number the user typed (1656367028) is absent. Check the target
instead: new_item_ids contains 1421289881, exactly what the user asked to
change TO. The request is satisfied. Correct verdict: COMPLETE. The absent
source number is a different valid identifier for the same item, not a
missing item.

Only flag INCOMPLETE when a distinct request -- a different item, a
different change -- has no representation at all in ACTION_TAKEN, and was
never resolved through dialogue either.

Respond in this exact format:
VERDICT: [INCOMPLETE or COMPLETE]
CONFIDENCE: [0.0-1.0]
MISSING_ITEM: [what the user asked for that the action does not address, or NONE]
REASONING: [one sentence]

If the number in question is unrelated to the request (a zip code fragment,
an already-resolved detail, or a different valid identifier for an item that
IS addressed elsewhere in the action), respond COMPLETE."""

USER_TEMPLATE_COMPLETENESS = """USER_REQUEST:
{user_request}

ACTION_TAKEN:
{action_taken}"""

_COMPLETENESS_VERDICT_RE = re.compile(r"VERDICT:\s*(INCOMPLETE|COMPLETE)", re.IGNORECASE)
_MISSING_ITEM_RE = re.compile(r"MISSING_ITEM:\s*(.+)")


@dataclass
class CompletenessVerdict:
    incomplete: bool
    confidence: float
    missing_item: str
    reasoning: str
    raw: str


def judge_completeness(user_request: str, action_args: dict) -> CompletenessVerdict | None:
    """Same fallback contract as judge_candidate: None means 'couldn't
    check' (no key, import failure, network/API error), never 'checked and
    it's fine.' Callers must treat None as 'fall back to the unconfirmed
    Tier 2 candidate.'

    Takes plain arguments rather than a specific candidate dataclass on
    purpose -- both completeness signals (a missing identifier, or a
    descriptive continuation cue) ask the judge the identical underlying
    question, just with a different shape of evidence assembled by their
    own Tier 2 scan. Decoupling this from either dataclass means adding a
    third signal later doesn't require touching this function at all."""
    if not judge_available():
        return None
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=200,
            system=SYSTEM_PROMPT_COMPLETENESS,
            messages=[{
                "role": "user",
                "content": USER_TEMPLATE_COMPLETENESS.format(
                    user_request=user_request,
                    action_taken=f"{action_args}",
                ),
            }],
        )
        text = response.content[0].text
    except Exception:
        return None

    verdict_match = _COMPLETENESS_VERDICT_RE.search(text)
    conf_match = _CONF_RE.search(text)
    missing_match = _MISSING_ITEM_RE.search(text)
    reason_match = _REASON_RE.search(text)
    if not verdict_match:
        return None

    return CompletenessVerdict(
        incomplete=verdict_match.group(1).upper() == "INCOMPLETE",
        confidence=float(conf_match.group(1)) if conf_match else 0.7,
        missing_item=missing_match.group(1).strip() if missing_match else "",
        reasoning=reason_match.group(1).strip() if reason_match else "",
        raw=text,
    )
