import re

def parse_thinking_response(raw: str) -> dict:
    """Parse a response that may contain <think>...</think> blocks.

    Returns dict with 'reasoning' (content inside think tags)
    and 'conclusion' (content after think tags, or full text if no tags).
    """
    match = re.search(r"<think>(.*?)</think>(.*)", raw, re.DOTALL)
    if match:
        reasoning = match.group(1).strip()
        conclusion = match.group(2).strip()
    else:
        reasoning = ""
        conclusion = raw.strip()
    return {"reasoning": reasoning, "conclusion": conclusion}
