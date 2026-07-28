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
