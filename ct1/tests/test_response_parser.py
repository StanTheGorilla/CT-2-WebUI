from ct1.core.response_parser import parse_thinking_response

def test_parse_with_think_tags():
    raw = "<think>\nStep 1: Consider X.\nStep 2: Therefore Y.\n</think>\n\nThe answer is Y."
    result = parse_thinking_response(raw)
    assert result["reasoning"] == "Step 1: Consider X.\nStep 2: Therefore Y."
    assert result["conclusion"] == "The answer is Y."

def test_parse_without_think_tags():
    raw = "Just a plain answer with no thinking."
    result = parse_thinking_response(raw)
    assert result["reasoning"] == ""
    assert result["conclusion"] == "Just a plain answer with no thinking."

def test_parse_empty_think_tags():
    raw = "<think>\n</think>\n\nDirect answer."
    result = parse_thinking_response(raw)
    assert result["reasoning"] == ""
    assert result["conclusion"] == "Direct answer."

def test_parse_multiline_conclusion():
    raw = "<think>\nReasoning here.\n</think>\n\nLine 1.\nLine 2."
    result = parse_thinking_response(raw)
    assert result["conclusion"] == "Line 1.\nLine 2."

def test_parse_strips_whitespace():
    raw = "  <think>  \n  reasoning  \n  </think>  \n\n  conclusion  "
    result = parse_thinking_response(raw)
    assert result["reasoning"] == "reasoning"
    assert result["conclusion"] == "conclusion"
