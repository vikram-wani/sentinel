"""Tier 2 — code-based contradiction heuristic.

Design role: a candidate generator, not a verdict. Tier 1's seven detectors
check facts (did a tool get called, is a value grounded). This tier is the
first step into *semantic* territory: does the evidence contain restrictive
language that the final answer seems to contradict?

It is deliberately recall-oriented, not precision-oriented. A restrictive
phrase near an affirmative answer about the same topic is a CANDIDATE for
review, not a confirmed finding. What happens to a candidate next depends on
whether Tier 3 (the LLM judge) is available:

  - Judge available:  candidate is sent for confirmation. CONTRADICTS becomes
    a Finding at the judge's own confidence. CONSISTENT is correctly
    suppressed  — this is how the tool avoids false-positiving on legitimate
    exceptions ("final sale, except defective items...").
  - Judge unavailable: the candidate surfaces directly as a Finding, but at
    confidence well below 1.0 and explicitly labeled unconfirmed, so a keyless
    run still gets signal without overclaiming certainty it doesn't have.

This module never calls a model. It only ever produces candidates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..schema import Step, StepType, Trace

RESTRICTIVE_PHRASES = [
    "final sale", "not eligible", "not covered", "does not cover", "excluded",
    "cannot be", "can not be", "no refunds", "not refundable", "non-refundable",
    "not transferable", "non-transferable",
    "void if", "voided if", "not valid", "only valid for", "restricted to",
    "prohibited", "not permitted", "not allowed", "ineligible", "does not apply",
    "not applicable", "expired", "no longer valid", "not accepted", "excludes",
]

AFFIRMATIVE_PATTERNS = [
    "yes", "you can", "you're able", "you are able", "we can", "is eligible",
    "is covered", "approved", "is fine", "is allowed", "no problem",
    "certainly", "is possible", "you may", "sure,", "go ahead",
]

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "for", "and", "or", "but", "if", "it",
    "this", "that", "your", "you", "we", "our", "can", "will", "as", "with",
    "not", "no",
}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _topic_tokens(sentence: str, exclude_substrings: tuple[str, ...] = ()) -> set[str]:
    cleaned = sentence.lower()
    for sub in exclude_substrings:
        cleaned = cleaned.replace(sub, " ")
    words = re.findall(r"[a-zA-Z']+", cleaned)
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _text(x) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, (list, tuple)):
        return " ".join(_text(item) for item in x)
    return str(x)


@dataclass
class ContradictionCandidate:
    step_index: int              # the evidence step
    evidence_sentence: str
    answer_step_index: int
    answer_text: str
    topic_overlap: set[str]


def find_candidates(trace: Trace) -> list[ContradictionCandidate]:
    """Pure, deterministic scan. No model calls. Returns [] on no signal."""
    final = trace.final_answer
    if final is None:
        return []
    answer_text = _text(final.output)
    answer_lower = answer_text.lower()

    has_affirmative = any(p in answer_lower for p in AFFIRMATIVE_PATTERNS)
    if not has_affirmative:
        return []

    answer_topics = _topic_tokens(answer_text)

    candidates: list[ContradictionCandidate] = []
    for step in trace.steps:
        if step.type not in (StepType.RETRIEVAL, StepType.TOOL_RESULT):
            continue
        evidence_text = _text(step.output)
        for sentence in _sentences(evidence_text):
            sentence_lower = sentence.lower()
            if not any(p in sentence_lower for p in RESTRICTIVE_PHRASES):
                continue
            # Skip if the answer itself repeats the restriction (i.e. agent
            # correctly refused / cited the same restriction back) — that's
            # not a contradiction, that's the answer working correctly.
            if any(p in answer_lower for p in RESTRICTIVE_PHRASES):
                continue
            sentence_topics = _topic_tokens(sentence, exclude_substrings=tuple(RESTRICTIVE_PHRASES))
            overlap = sentence_topics & answer_topics
            if len(overlap) >= 2:  # require real topical overlap, not one stray word
                candidates.append(ContradictionCandidate(
                    step_index=step.index,
                    evidence_sentence=sentence,
                    answer_step_index=final.index,
                    answer_text=answer_text,
                    topic_overlap=overlap,
                ))
    return candidates
