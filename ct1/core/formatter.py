"""CT-2 Formatter: Deterministic Python regex cleanup.

No LLM involvement. Strips <think> tags, markdown fences, preambles,
and wraps HTML fragments in complete document structure.
"""
import ast
import re


def clean_response(text: str, is_code: bool = False,
                   output_type: str = "html_page") -> str:
    """Master cleanup: strip thinking, extract code or clean text."""
    text = strip_think_tags(text)

    if is_code:
        text = extract_code(text)
        if output_type in ("python_script", "api"):
            text = strip_python_preamble(text)
        else:
            text = strip_preamble(text)
            text = strip_postamble(text)
            text = wrap_html_fragment(text)

    return text.strip()


def strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from model output."""
    return re.sub(r'<think>[\s\S]*?</think>', '', text).strip()


def extract_code(text: str) -> str:
    """Extract code from markdown fences if present."""
    fence = re.search(
        r'```(?:html|css|js|javascript|python|py)?\s*\n(.*?)```',
        text, re.DOTALL
    )
    if fence:
        return fence.group(1).strip()
    return text


def strip_preamble(text: str) -> str:
    """Remove conversational text before HTML code."""
    for marker in ("<!DOCTYPE", "<!doctype", "<html", "<HTML"):
        idx = text.find(marker)
        if idx > 0:
            return text[idx:]

    for marker in ("<!--", "<link", "<meta", "<style", "<head"):
        idx = text.find(marker)
        if idx > 0:
            return text[idx:]

    return text


def strip_python_preamble(text: str) -> str:
    """Remove conversational text before Python code."""
    for marker in ("import ", "from ", "def ", "class ", "#!", "#!/"):
        idx = text.find(marker)
        if 0 < idx < 300:
            return text[idx:]
    return text


def strip_postamble(text: str) -> str:
    """Remove commentary after </html>."""
    for end_tag in ("</html>", "</HTML>"):
        idx = text.find(end_tag)
        if idx != -1:
            return text[:idx + len(end_tag)]
    return text


def wrap_html_fragment(text: str) -> str:
    """If output is an HTML fragment, wrap in complete document structure."""
    t = text.lower().strip()
    if not t:
        return text

    if t.startswith("<!doctype") or t.startswith("<html"):
        return text

    has_html = any(tag in t for tag in
                   ("<style", "<div", "<section", "<link", "<!--",
                    "<header", "<main", "<footer", "<nav"))
    if not has_html:
        return text

    style = re.search(r'(<style[\s\S]*?</style>)', text, re.IGNORECASE)
    script = re.search(r'(<script[\s\S]*?</script>)', text, re.IGNORECASE)
    links = re.findall(r'(<link[^>]*>)', text, re.IGNORECASE)

    body = text
    if style:
        body = body.replace(style.group(1), '')
    if script:
        body = body.replace(script.group(1), '')
    for link in links:
        body = body.replace(link, '')
    body = body.strip()

    head_parts = "\n    ".join(links)
    if style:
        head_parts += ("\n    " if head_parts else "") + style.group(1)

    script_part = "\n" + script.group(1) if script else ""

    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '    <meta charset="UTF-8">\n'
        '    <meta name="viewport" content="width=device-width, '
        'initial-scale=1.0">\n'
        f'    <title>CT-2 Output</title>\n    {head_parts}\n'
        f'</head>\n<body>\n{body}{script_part}\n'
        '</body>\n</html>'
    )


# ── Validators ────────────────────────────────────────────────────────


def validate_html(html: str) -> list[str]:
    """Programmatic structural validation for HTML. Returns list of issues."""
    issues = []
    h = html.lower()

    if '<!doctype html>' not in h:
        issues.append("Missing <!DOCTYPE html> declaration")
    if '<html' not in h:
        issues.append("Missing <html> tag")
    if '<head' not in h:
        issues.append("Missing <head> section")
    if '<body' not in h:
        issues.append("Missing <body> section")
    if '</html>' not in h:
        issues.append("Missing closing </html>")
    if 'viewport' not in h:
        issues.append("Missing viewport meta tag")
    if '<title' not in h:
        issues.append("Missing <title> tag")
    if '<style' not in h and 'stylesheet' not in h:
        issues.append("No CSS styling found")
    if len(html.strip()) < 200:
        issues.append("Output too short — likely incomplete")

    return issues


def validate_python(code: str) -> list[str]:
    """Use Python's AST parser for real syntax checking."""
    if len(code.strip()) < 20:
        return ["Output too short — likely incomplete"]
    try:
        ast.parse(code)
        return []
    except SyntaxError as e:
        return [f"Python syntax error at line {e.lineno}: {e.msg}"]
    except Exception as e:
        return [f"Parse error: {e}"]


def validate_javascript(code: str) -> list[str]:
    """Basic structural checks for JavaScript."""
    issues = []
    if len(code.strip()) < 20:
        issues.append("Output too short — likely incomplete")
        return issues
    opens = code.count('{')
    closes = code.count('}')
    if abs(opens - closes) > 2:
        issues.append(f"Mismatched braces: {opens} open vs {closes} close")
    return issues


def validate_output(code: str, output_type: str) -> list[str]:
    """Route to the right validator based on output type."""
    if output_type in ("python_script", "api"):
        return validate_python(code)
    if output_type == "javascript":
        return validate_javascript(code)
    # Default: HTML validation
    return validate_html(code)
