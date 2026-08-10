old = '''def judge_completeness(candidate) -> CompletenessVerdict | None:
    """Same fallback contract as judge_candidate: None means 'couldn't
    check' (no key, import failure, network/API error), never 'checked and
    it's fine.' Callers must treat None as 'fall back to the unconfirmed
    Tier 2 candidate.'"""
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
                    user_request=candidate.user_text,
                    action_taken=f"{candidate.call_args}",
                ),
            }],
        )
        text = response.content[0].text
    except Exception:
        return None'''

new = '''def judge_completeness(user_request: str, action_args: dict) -> CompletenessVerdict | None:
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
        return None'''

path = "src/sentinel/judge.py"
content = open(path).read()
if old not in content:
    print("OLD TEXT NOT FOUND -- stopping, paste your current judge.py so I can check.")
else:
    content = content.replace(old, new, 1)
    open(path, "w").write(content)
    print("judge.py patched successfully")
