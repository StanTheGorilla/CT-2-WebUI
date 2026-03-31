"""CT-2 Formatter: Deterministic cleanup for all output types.

No LLM involvement. Strips <think> tags, markdown fences, preambles,
detects output language, applies language-appropriate cleanup,
and deterministic CSS polish.
"""
import ast
import re


# ── Deterministic CSS Post-Processor ─────────────────────────────────


def deterministic_css_polish(css: str) -> str:
    """Lightweight CSS safety net. No AI involved.
    Only fixes structural omissions — never overrides design choices."""

    # 1. Inject box-sizing reset if missing (structural necessity)
    if 'box-sizing' not in css:
        css = '*, *::before, *::after { box-sizing: border-box; }\n' + css

    # 2. Add transitions to interactive elements missing them
    def _ensure_transition(css_text):
        """Add transition to button/a/card selectors that lack one."""
        rules = _split_css_rules(css_text)
        patched = []
        interactive_selectors = ('button', 'a ', 'a:', 'a{', '.btn', '.card',
                                 'input', 'select', '[role="button"]')
        for sel, body in rules:
            sel_lower = sel.lower().strip()
            is_interactive = any(s in sel_lower for s in interactive_selectors)
            is_hover = ':hover' in sel_lower or ':focus' in sel_lower
            if is_interactive and not is_hover and 'transition' not in body:
                body = body.rstrip()
                if body.endswith('}'):
                    body = body[:-1].rstrip() + '\n    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);\n}'
            patched.append(sel + body)
        return '\n'.join(patched)

    css = _ensure_transition(css)

    # 3. Ensure smooth scrolling if missing
    if 'scroll-behavior' not in css:
        css = 'html { scroll-behavior: smooth; }\n' + css

    return css


def _split_css_rules(css: str) -> list[tuple[str, str]]:
    """Split CSS into (selector, body-including-braces) pairs.
    Simple brace-counting parser — not a full CSS parser."""
    rules = []
    i = 0
    while i < len(css):
        # Find next opening brace
        brace = css.find('{', i)
        if brace == -1:
            break
        selector = css[i:brace]
        # Count braces to find matching close
        depth = 0
        j = brace
        while j < len(css):
            if css[j] == '{':
                depth += 1
            elif css[j] == '}':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = css[brace:j + 1]
        rules.append((selector, body))
        i = j + 1
    return rules


def polish_html_css(html: str) -> str:
    """Extract CSS from HTML, apply deterministic polish, reassemble."""
    style_match = re.search(
        r'(<style[^>]*>)(.*?)(</style>)', html,
        re.DOTALL | re.IGNORECASE
    )
    if not style_match:
        return html
    css = style_match.group(2)
    if len(css.strip()) < 30:
        return html
    polished = deterministic_css_polish(css)
    return (html[:style_match.start(2)]
            + polished
            + html[style_match.end(2):])


# ── Language detection ────────────────────────────────────────────────


def detect_output_type(text: str) -> str:
    """Auto-detect the output type from code content.

    Returns: 'html_page', 'python_script', 'javascript', 'cpp', 'other'.
    Used when planner is unavailable (solo mode) or plan is None.
    """
    t = text.strip()
    lower = t[:500].lower()

    if lower.startswith(("<!doctype", "<html")):
        return "html_page"
    if lower.startswith(("import ", "from ", "def ", "class ", "#!", "#!/")):
        return "python_script"
    if lower.startswith(("#include", "using namespace", "int main")):
        return "cpp"
    if lower.startswith(("const ", "let ", "var ", "function ",
                         "import {", "import '", "import \"")):
        return "javascript"
    if lower.startswith(("package ", "func ")):
        return "go"
    if lower.startswith(("use ", "fn ", "mod ", "pub ")):
        return "rust"

    # Content-based detection for cases where preamble obscures the start
    if "<html" in lower or "<!doctype" in lower:
        return "html_page"
    if "def " in lower and ("import " in lower or "print(" in lower):
        return "python_script"
    if "#include" in lower and ("int main" in lower or "void " in lower):
        return "cpp"
    if "function " in lower and ("const " in lower or "let " in lower):
        return "javascript"

    # Simple Python heuristics: scripts that start with print() or use
    # the standard __main__ guard but have no leading import/def
    if ("<html" not in lower and "<!doctype" not in lower
            and ("print(" in lower or "if __name__" in lower)):
        return "python_script"

    return "other"


# ── Core cleanup ──────────────────────────────────────────────────────


def clean_response(text: str, is_code: bool = False,
                   output_type: str = "html_page") -> str:
    """Master cleanup: strip thinking, extract code, apply language-aware cleanup."""
    text = strip_think_tags(text)

    if is_code:
        text = extract_code(text)

        # Auto-detect if output_type is wrong or default
        if output_type in ("html_page", "other"):
            detected = detect_output_type(text)
            if detected != "html_page" and detected != "other":
                output_type = detected

        if output_type in ("python_script", "api"):
            text = strip_code_preamble(text, "python")
            text = strip_code_postamble(text, "python")
        elif output_type in ("javascript",):
            text = strip_code_preamble(text, "javascript")
            text = strip_code_postamble(text, "javascript")
        elif output_type in ("cpp", "go", "rust"):
            text = strip_code_preamble(text, output_type)
            text = strip_code_postamble(text, output_type)
        else:
            text = strip_preamble(text)
            text = strip_postamble(text)
            text = wrap_html_fragment(text)

    return text.strip()


def strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from model output."""
    return re.sub(r'<think>[\s\S]*?</think>', '', text).strip()


def extract_code(text: str) -> str:
    """Extract code from markdown fences. Handles multiple fences and
    various language labels that 4B models produce."""
    # Try to find the largest fenced block (models sometimes wrap entire output)
    fences = list(re.finditer(
        r'```(?:html|css|js|javascript|python|py|cpp|c\+\+|c|rust|go|java|sh|bash|typescript|ts)?\s*\n(.*?)```',
        text, re.DOTALL
    ))
    if fences:
        # Use the largest block — that's the actual code
        largest = max(fences, key=lambda m: len(m.group(1)))
        return largest.group(1).strip()
    # Handle unclosed fence (model cut off before closing ```)
    unclosed = re.match(
        r'```(?:html|css|js|javascript|python|py|cpp|c\+\+|c|rust|go|java|sh|bash|typescript|ts)?\s*\n(.*)',
        text, re.DOTALL
    )
    if unclosed:
        return unclosed.group(1).strip()
    return text


# ── Language-aware preamble/postamble stripping ──────────────────────


_CODE_START_MARKERS = {
    "python": ("import ", "from ", "def ", "class ", "#!", "#!/",
               '"""', "'''", "# "),
    "javascript": ("const ", "let ", "var ", "function ", "import ",
                   "export ", "class ", "'use strict'", '"use strict"', "//"),
    "cpp": ("#include", "using ", "namespace ", "int ", "void ",
            "class ", "struct ", "//", "/*"),
    "go": ("package ", "import ", "func ", "type ", "var ", "const ", "//"),
    "rust": ("use ", "fn ", "mod ", "pub ", "struct ", "enum ",
             "impl ", "trait ", "//", "#["),
}

_CONVERSATIONAL_PREFIXES = (
    "here's", "here is", "here are", "below is", "i've created",
    "i have created", "sure,", "sure!", "certainly", "of course",
    "let me", "this is", "the following", "i'll", "okay,",
    "this code", "this script", "this program",
)


def strip_code_preamble(text: str, lang: str) -> str:
    """Remove conversational text before code for any language."""
    markers = _CODE_START_MARKERS.get(lang, ())
    for marker in markers:
        idx = text.find(marker)
        if 0 < idx < 500:
            # Check that the text before is conversational, not code
            before = text[:idx].strip().lower()
            if any(before.startswith(p) for p in _CONVERSATIONAL_PREFIXES) or len(before) < 100:
                return text[idx:]
    return text


def strip_code_postamble(text: str, lang: str) -> str:
    """Remove conversational commentary after code ends."""
    lines = text.rstrip().split('\n')
    # Walk backwards from the end, stripping non-code lines
    while lines:
        last = lines[-1].strip().lower()
        if not last:
            lines.pop()
            continue
        # Conversational endings
        if any(last.startswith(p) for p in (
            "this ", "the ", "you can", "note:", "note that",
            "i hope", "let me know", "feel free", "this code",
            "this script", "this program", "to run", "to use",
            "explanation:", "output:", "---",
        )):
            lines.pop()
            continue
        break
    return '\n'.join(lines)


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
    """Remove conversational text before Python code. (Legacy alias)"""
    return strip_code_preamble(text, "python")


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


# ── Defensive file-marker enforcement ─────────────────────────────────


def enforce_file_markers(text: str, route: str) -> str:
    """If computer mode output has code but no [FILE:] markers, wrap it.

    Small models sometimes ignore the [FILE:] format instruction.
    This prevents silent failures where parseable code has no file marker.
    """
    if route != "ROUTE_COMPUTER":
        return text
    if "[FILE:" in text or "[FILE :" in text:
        return text  # Already has markers

    # Detect language and wrap in default marker
    stripped = text.strip()
    if not stripped:
        return text

    ext_map = [
        ("<!DOCTYPE", "index.html"),
        ("<html", "index.html"),
        ("import React", "App.jsx"),
        ("from flask", "app.py"),
        ("from fastapi", "main.py"),
        ("def ", "main.py"),
        ("class ", "main.py"),
        ("function ", "index.js"),
        ("const ", "index.js"),
        ("import ", "main.py"),
    ]
    for pattern, filename in ext_map:
        if pattern in stripped:
            return f"[FILE: {filename}]\n{stripped}"
    return text


# ── Section splitting for targeted edits ──────────────────────────────


def split_html_sections(html: str) -> dict[str, str]:
    """Split an HTML document into named sections for targeted editing.

    Returns dict with keys: 'head', 'style', 'body', 'script'.
    Each value is the inner content of that section (no wrapping tags).
    """
    sections = {}

    style_match = re.search(
        r'<style[^>]*>(.*?)</style>', html, re.DOTALL | re.IGNORECASE
    )
    if style_match:
        sections['style'] = style_match.group(1).strip()

    script_match = re.search(
        r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE
    )
    if script_match:
        sections['script'] = script_match.group(1).strip()

    body_match = re.search(
        r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE
    )
    if body_match:
        body = body_match.group(1)
        body = re.sub(
            r'<script[^>]*>.*?</script>', '', body,
            flags=re.DOTALL | re.IGNORECASE
        ).strip()
        sections['body'] = body

    head_match = re.search(
        r'<head[^>]*>(.*?)</head>', html, re.DOTALL | re.IGNORECASE
    )
    if head_match:
        head = head_match.group(1)
        head = re.sub(
            r'<style[^>]*>.*?</style>', '', head,
            flags=re.DOTALL | re.IGNORECASE
        ).strip()
        sections['head'] = head

    return sections


def reassemble_html_section(original_html: str, section: str,
                            new_content: str) -> str:
    """Replace a specific section's inner content in the original HTML."""
    if section == 'style':
        return re.sub(
            r'(<style[^>]*>).*?(</style>)',
            lambda m: f"{m.group(1)}\n{new_content}\n{m.group(2)}",
            original_html, count=1, flags=re.DOTALL | re.IGNORECASE,
        )
    if section == 'script':
        return re.sub(
            r'(<script[^>]*>).*?(</script>)',
            lambda m: f"{m.group(1)}\n{new_content}\n{m.group(2)}",
            original_html, count=1, flags=re.DOTALL | re.IGNORECASE,
        )
    if section == 'body':
        # Preserve <script> tags that live inside <body>
        script_match = re.search(
            r'<script[^>]*>.*?</script>', original_html,
            re.DOTALL | re.IGNORECASE,
        )
        script_part = f"\n{script_match.group(0)}" if script_match else ""
        return re.sub(
            r'(<body[^>]*>).*?(</body>)',
            lambda m: f"{m.group(1)}\n{new_content}{script_part}\n{m.group(2)}",
            original_html, count=1, flags=re.DOTALL | re.IGNORECASE,
        )
    if section == 'head':
        # Preserve <style> tags that live inside <head>
        style_match = re.search(
            r'<style[^>]*>.*?</style>', original_html,
            re.DOTALL | re.IGNORECASE,
        )
        style_part = f"\n    {style_match.group(0)}" if style_match else ""
        return re.sub(
            r'(<head[^>]*>).*?(</head>)',
            lambda m: f"{m.group(1)}\n{new_content}{style_part}\n{m.group(2)}",
            original_html, count=1, flags=re.DOTALL | re.IGNORECASE,
        )
    return original_html


# ── Validators ────────────────────────────────────────────────────────


def validate_html(html: str) -> list[str]:
    """Programmatic structural validation for HTML.

    Returns only CRITICAL issues that indicate genuinely broken output
    (truncated, empty body, unparseable). Non-critical gaps like missing
    viewport/title/doctype are fixed deterministically by fix_html_structure()
    — never sent back to the LLM, which would rewrite the whole thing.
    """
    issues = []
    h = html.lower()

    if len(html.strip()) < 200:
        issues.append("Output too short — likely incomplete")
    if '</html>' not in h and '<html' in h:
        issues.append("Truncated output — missing closing </html>")

    # Body exists but is empty (after stripping scripts)
    body_match = re.search(r'<body[^>]*>(.*?)</body>', html,
                           re.DOTALL | re.IGNORECASE)
    if body_match:
        body_content = re.sub(r'<script[^>]*>.*?</script>', '',
                              body_match.group(1),
                              flags=re.DOTALL | re.IGNORECASE).strip()
        if len(body_content) < 20:
            issues.append("Empty <body> — no visible content")

    return issues


def fix_html_structure(html: str) -> str:
    """Deterministically patch missing HTML boilerplate.

    Adds DOCTYPE, <html>, <head>, viewport, <title> if absent.
    No LLM call — pure string surgery. Returns the patched HTML.
    """
    h = html.lower()

    # Already a full document — just patch missing pieces
    if '<html' in h:
        # Add DOCTYPE if missing
        if '<!doctype' not in h:
            html = '<!DOCTYPE html>\n' + html

        # Add viewport if missing
        if 'viewport' not in h:
            head_end = re.search(r'(<head[^>]*>)', html, re.IGNORECASE)
            if head_end:
                insert_at = head_end.end()
                html = (html[:insert_at]
                        + '\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">'
                        + html[insert_at:])

        # Add title if missing
        if '<title' not in h:
            head_end = re.search(r'(<head[^>]*>)', html, re.IGNORECASE)
            if head_end:
                insert_at = head_end.end()
                html = (html[:insert_at]
                        + '\n    <title>Page</title>'
                        + html[insert_at:])

        return html

    # Fragment — wrap_html_fragment already handles this case
    return html


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
    parens_open = code.count('(')
    parens_close = code.count(')')
    if abs(parens_open - parens_close) > 2:
        issues.append(f"Mismatched parentheses: {parens_open} open vs {parens_close} close")
    return issues


def validate_cpp(code: str) -> list[str]:
    """Structural checks for C/C++."""
    issues = []
    if len(code.strip()) < 20:
        issues.append("Output too short — likely incomplete")
        return issues
    if "#include" not in code:
        issues.append("Missing #include directives")
    opens = code.count('{')
    closes = code.count('}')
    if abs(opens - closes) > 1:
        issues.append(f"Mismatched braces: {opens} open vs {closes} close")
    # Check for main() in standalone programs
    if "int main" not in code and "void main" not in code:
        # Only flag if it looks like a standalone program (not a library)
        if "#include" in code and "class " not in code:
            issues.append("Missing main() function")
    return issues


def validate_output(code: str, output_type: str) -> list[str]:
    """Route to the right validator based on output type."""
    if output_type in ("python_script", "api"):
        return validate_python(code)
    if output_type == "javascript":
        return validate_javascript(code)
    if output_type == "cpp":
        return validate_cpp(code)
    if output_type == "other":
        # Auto-detect and validate
        detected = detect_output_type(code)
        if detected == "python_script":
            return validate_python(code)
        if detected == "javascript":
            return validate_javascript(code)
        if detected == "cpp":
            return validate_cpp(code)
    # Default: HTML validation
    return validate_html(code)


# ── Computer mode file validation ────────────────────────────────────


def validate_file(path: str, content: str) -> list[str]:
    """Validate a single file from computer mode output.
    Returns list of issues (empty = valid)."""
    if not content or len(content.strip()) < 5:
        return [f"{path}: File is empty or too short"]

    ext = path.rsplit('.', 1)[-1].lower() if '.' in path else ''
    if ext == 'py':
        return [f"{path}: {i}" for i in validate_python(content)]
    if ext in ('js', 'jsx', 'ts', 'tsx'):
        return [f"{path}: {i}" for i in validate_javascript(content)]
    if ext in ('cpp', 'c', 'h', 'hpp'):
        return [f"{path}: {i}" for i in validate_cpp(content)]
    if ext in ('html', 'htm'):
        return [f"{path}: {i}" for i in validate_html(content)]
    return []


# ── Broken output detection (for auto-retry) ────────────────────────


def detect_broken_sections(html: str) -> list[str]:
    """Detect blank or broken HTML sections that need regeneration.

    Returns list of broken section names (e.g. ['body', 'style'])
    or empty list if output looks OK.
    """
    if not html or len(html.strip()) < 100:
        return ["body", "style"]

    broken = []
    h = html.lower()

    # Empty or whitespace-only body
    body_match = re.search(
        r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE
    )
    if body_match:
        body_content = body_match.group(1).strip()
        # Remove scripts before checking emptiness
        body_no_script = re.sub(
            r'<script[^>]*>.*?</script>', '', body_content,
            flags=re.DOTALL | re.IGNORECASE
        ).strip()
        if len(body_no_script) < 20:
            broken.append("body")
    elif '<body' in h:
        # <body> tag exists but no closing tag — truncated
        broken.append("body")

    # Missing style entirely when the document has structure
    if '<style' not in h and 'stylesheet' not in h:
        if '<body' in h and '<div' in h:
            broken.append("style")
    else:
        # Style tag exists but empty
        style_match = re.search(
            r'<style[^>]*>(.*?)</style>', html, re.DOTALL | re.IGNORECASE
        )
        if style_match and len(style_match.group(1).strip()) < 10:
            broken.append("style")

    # Head present but body missing entirely
    if '<head' in h and '<body' not in h:
        broken.append("body")

    return broken


# ── Completeness checker (decomposition → output verification) ──────

# Keywords that signal a section exists in the HTML
_SECTION_KEYWORDS = {
    "hero": ["min-h-screen", "min-h-[", "hero"],
    "header": ["<header", "header"],
    "nav": ["<nav", "navbar", "navigation"],
    "navigation": ["<nav", "navbar", "navigation"],
    "features": ["feature", "grid", "card"],
    "about": ["about", "story", "who we"],
    "services": ["service", "what we"],
    "testimonials": ["testimonial", "review", "quote", "said"],
    "pricing": ["pricing", "price", "plan", "/mo", "/month"],
    "cta": ["get started", "sign up", "join", "try", "contact us"],
    "contact": ["contact", "form", "email", "message"],
    "footer": ["<footer", "footer"],
    "gallery": ["gallery", "portfolio", "showcase"],
    "team": ["team", "member", "founder"],
    "faq": ["faq", "question", "accordion"],
    "blog": ["blog", "article", "post"],
    "menu": ["menu", "dish", "cuisine", "appetizer"],
    "reservation": ["reserv", "book", "table"],
    "experience": ["experience", "journey"],
}

# Structural checks for design output
_DESIGN_STRUCTURAL_CHECKS = [
    ("Body colors", lambda h: "bg-" in h and ("text-" in h or "color:" in h)),
    ("Hover states", lambda h: "hover:" in h or ":hover" in h),
    ("Responsive", lambda h: any(bp in h for bp in ["sm:", "md:", "lg:"])),
    ("Google Fonts", lambda h: "fonts.googleapis" in h or "font-family" in h),
    ("Animations", lambda h: "transition" in h or "animation" in h),
]


def check_completeness(output: str, decomposition: dict) -> list[dict]:
    """Check generated output against decomposition requirements.

    Returns list of {item: str, done: bool} dicts.
    Pure string matching — no LLM involved.
    """
    if not output or not decomposition:
        return []

    route = decomposition.get("_route", "")
    lower = output.lower()
    results = []

    if route == "ROUTE_DESIGN":
        # Gate: if there's no actual HTML body, fail everything —
        # a bare <script> config block is not a website
        has_body = "<body" in lower or ("</section>" in lower) or ("</main>" in lower)
        has_content = len(output) > 500 and has_body

        # Check each planned section
        for section in decomposition.get("sections", []):
            sec_lower = section.lower().strip()
            keywords = _SECTION_KEYWORDS.get(sec_lower, [sec_lower])
            found = has_content and any(kw in lower for kw in keywords)
            results.append({"item": section, "done": found})

        # Structural checks — also gated on having actual HTML
        for name, check_fn in _DESIGN_STRUCTURAL_CHECKS:
            results.append({"item": name, "done": has_content and check_fn(lower)})

    elif route == "ROUTE_CODE":
        for req in decomposition.get("requirements", []):
            # Extract significant words (4+ chars) from the requirement
            words = [w for w in re.findall(r'[a-zA-Z]{4,}', req.lower())
                     if w not in {"must", "should", "make", "with", "that",
                                  "this", "from", "have", "each", "when",
                                  "into", "also", "will", "does", "been"}]
            if words:
                matches = sum(1 for w in words if w in lower)
                found = matches >= max(1, len(words) // 3)
            else:
                found = True  # can't check, assume done
            results.append({"item": req, "done": found})

    elif route == "ROUTE_COMPUTER":
        for f in decomposition.get("files", []):
            # Check if the [FILE: path] marker exists
            found = f.lower() in lower or f"[file: {f.lower()}" in lower
            results.append({"item": f, "done": found})
        for req in decomposition.get("requirements", []):
            words = [w for w in re.findall(r'[a-zA-Z]{4,}', req.lower())
                     if w not in {"must", "should", "make", "with", "that",
                                  "this", "from", "have", "each", "when"}]
            if words:
                matches = sum(1 for w in words if w in lower)
                found = matches >= max(1, len(words) // 3)
            else:
                found = True
            results.append({"item": req, "done": found})

    return results
