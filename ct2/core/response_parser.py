import re

def parse_thinking_response(raw: str) -> dict:
    """Parse a response that may contain <think>...</think> blocks.

    Returns dict with 'reasoning' (content inside think tags)
    and 'conclusion' (content after think tags, or full text if no tags).
    If conclusion is empty but reasoning exists, use reasoning as conclusion.
    """
    match = re.search(r"<think>(.*?)</think>(.*)", raw, re.DOTALL)
    if match:
        reasoning = match.group(1).strip()
        conclusion = match.group(2).strip()
        # If model put everything in thinking block, use reasoning as fallback
        if not conclusion and reasoning:
            conclusion = reasoning
    else:
        reasoning = ""
        conclusion = raw.strip()
    return {"reasoning": reasoning, "conclusion": conclusion}
