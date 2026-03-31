"""CT-2 Mechanical Validator — zero-AI structural validation.

Uses BeautifulSoup4 for HTML parsing and jsonschema for spec validation.
All functions return (passed: bool, errors: list[str]).
"""

import json
import re
from pathlib import Path
from bs4 import BeautifulSoup, Comment

# ── Schema path ──────────────────────────────────────────────────
_SCHEMA_PATH = Path(__file__).parent / "spec_schema.json"

# ── Interaction → required data-attribute mapping ────────────────
_INTERACTION_CHECKS: dict[str, list[str]] = {
    "hamburger-toggle": [
        '[data-toggle="hamburger"]',
        "[data-hamburger-menu]",
    ],
    "smooth-scroll":      ["[data-smooth-scroll]"],
    "accordion":          ["[data-accordion-trigger]", "[data-accordion-content]"],
    "form-validation":    ["[data-validate]"],
    "dark-mode-toggle":   ['[data-toggle="darkmode"]'],
    "carousel":           ["[data-carousel]"],
    "modal":              ["[data-modal-open]"],
    "scroll-reveal":      ["[data-scroll-reveal]"],
}

# Inline event handler attributes to strip
_INLINE_HANDLERS = re.compile(
    r'\s+on(?:click|dblclick|mouse(?:down|up|over|out|move|enter|leave)'
    r'|key(?:down|up|press)|focus|blur|change|input|submit|reset'
    r'|load|unload|error|resize|scroll|select|abort'
    r'|drag(?:start|end|enter|leave|over|drop)|contextmenu'
    r'|touch(?:start|end|move|cancel)|pointer(?:down|up|move|enter|leave|cancel|over|out))'
    r'\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)',
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════════
# Helper functions
# ═══════════════════════════════════════════════════════════════════

def strip_style_tags(html: str) -> str:
    """Remove <style> blocks from component HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("style"):
        tag.decompose()
    return str(soup)


def strip_script_tags(html: str) -> str:
    """Remove <script> tags and inline event handlers from component HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script"):
        tag.decompose()
    # Strip inline handlers from all elements
    result = str(soup)
    result = _INLINE_HANDLERS.sub("", result)
    return result


def sanitize_component(html: str) -> str:
    """Apply both strip_style_tags and strip_script_tags.

    Called automatically during validate_component.
    """
    return strip_script_tags(strip_style_tags(html))


# ═══════════════════════════════════════════════════════════════════
# 1. validate_spec
# ═══════════════════════════════════════════════════════════════════

def validate_spec(spec: dict) -> tuple[bool, list[str]]:
    """Validate the Director's JSON spec output.

    Uses jsonschema when available; falls back to manual checks otherwise.
    Also enforces cross-field invariants that JSON Schema cannot express:
      - every component id appears in layout_order (and vice-versa)
      - no duplicate ids
      - every component has at least one required_element
    """
    errors: list[str] = []

    # ── JSON Schema validation ───────────────────────────────────
    try:
        import jsonschema as _js

        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = _js.Draft7Validator(schema)
        for err in sorted(validator.iter_errors(spec), key=lambda e: list(e.path)):
            path = ".".join(str(p) for p in err.absolute_path) or "(root)"
            errors.append(f"schema: {path} — {err.message}")
    except ImportError:
        # Fallback: manual structural checks
        errors.extend(_manual_schema_check(spec))

    # ── Cross-field invariants ───────────────────────────────────
    components = spec.get("components", [])
    layout_order = spec.get("layout_order", [])

    comp_ids = [c.get("id") for c in components if isinstance(c, dict)]

    # Duplicate ids
    seen: set[str] = set()
    for cid in comp_ids:
        if cid in seen:
            errors.append(f"duplicate component id: '{cid}'")
        if cid is not None:
            seen.add(cid)

    # layout_order ↔ component id symmetry
    comp_id_set = set(comp_ids)
    layout_set = set(layout_order)

    for cid in comp_id_set - layout_set:
        errors.append(f"component '{cid}' missing from layout_order")
    for lid in layout_set - comp_id_set:
        errors.append(f"layout_order entry '{lid}' has no matching component")

    # Every component needs at least one required_element
    for comp in components:
        if not isinstance(comp, dict):
            continue
        cid = comp.get("id", "<unknown>")
        req_els = comp.get("required_elements", [])
        if not req_els:
            errors.append(f"component '{cid}' has no required_elements")

    return (len(errors) == 0, errors)


def _manual_schema_check(spec: dict) -> list[str]:
    """Fallback validation when jsonschema is not importable."""
    errors: list[str] = []

    # Top-level required keys
    for key in ("page_title", "color_theme", "layout_order", "components"):
        if key not in spec:
            errors.append(f"missing required key: '{key}'")

    # page_title type
    if "page_title" in spec and not isinstance(spec["page_title"], str):
        errors.append("page_title must be a string")

    # color_theme
    ct = spec.get("color_theme")
    if ct is not None:
        if not isinstance(ct, dict):
            errors.append("color_theme must be an object")
        else:
            for ck in ("primary", "secondary", "accent", "background", "text"):
                if ck not in ct:
                    errors.append(f"color_theme missing key: '{ck}'")
                elif not isinstance(ct[ck], str):
                    errors.append(f"color_theme.{ck} must be a string")

    # layout_order
    lo = spec.get("layout_order")
    if lo is not None:
        if not isinstance(lo, list) or len(lo) == 0:
            errors.append("layout_order must be a non-empty array")

    # components
    comps = spec.get("components")
    if comps is not None:
        if not isinstance(comps, list):
            errors.append("components must be an array")
        else:
            valid_types = {
                "navbar", "hero", "features", "testimonials", "cta",
                "pricing", "contact", "footer", "gallery", "stats",
                "team", "faq", "custom",
            }
            for i, comp in enumerate(comps):
                if not isinstance(comp, dict):
                    errors.append(f"components[{i}] must be an object")
                    continue
                for rk in ("id", "type", "required_elements", "content", "style_hints"):
                    if rk not in comp:
                        errors.append(f"components[{i}] missing key: '{rk}'")
                ctype = comp.get("type")
                if ctype is not None and ctype not in valid_types:
                    errors.append(
                        f"components[{i}].type '{ctype}' not in allowed types"
                    )

    return errors


# ═══════════════════════════════════════════════════════════════════
# 2. validate_component
# ═══════════════════════════════════════════════════════════════════

def validate_component(
    html: str, component_spec: dict,
) -> tuple[bool, list[str], list[str]]:
    """Validate a single generated HTML component.

    Automatically sanitizes (strips <style>/<script>/inline handlers) before
    structural checks.

    Returns:
        (passed, hard_errors, soft_warnings)
        - hard_errors: unparseable HTML, missing/wrong root ID → triggers patching
        - soft_warnings: missing required elements, missing interaction attrs → logged only
    """
    hard: list[str] = []
    soft: list[str] = []
    cid = component_spec.get("id", "<unknown>")

    # Sanitize first
    html = sanitize_component(html)

    # Parse
    soup = BeautifulSoup(html, "html.parser")
    top_level = [el for el in soup.children if el.name is not None]

    if not top_level:
        hard.append(f"[{cid}] HTML parse produced no elements")
        return (False, hard, soft)

    # Root element id check — HARD failure
    root = top_level[0]
    root_id = root.get("id")
    if root_id != cid:
        hard.append(
            f"[{cid}] root element id mismatch: expected '{cid}', got '{root_id}'"
        )

    # Required elements — SOFT (2B models can't reliably hit exact identifiers)
    for req in component_spec.get("required_elements", []):
        tag = req.get("tag", "")
        identifier = req.get("identifier", "")
        if not tag or not identifier:
            continue
        found = _find_required_element(soup, tag, identifier)
        if not found:
            soft.append(
                f"[{cid}] missing required element: <{tag}> with identifier '{identifier}'"
            )

    # Interaction data attributes — SOFT
    for interaction in component_spec.get("interactions", []):
        selectors = _INTERACTION_CHECKS.get(interaction, [])
        for selector in selectors:
            if not soup.select(selector):
                soft.append(
                    f"[{cid}] interaction '{interaction}': missing element matching '{selector}'"
                )

    return (len(hard) == 0, hard, soft)


def _find_required_element(soup: BeautifulSoup, tag: str, identifier: str) -> bool:
    """Check if an element with the given tag and identifier exists.

    Identifier is checked as: id attribute, class name, or data-* attribute.
    """
    # By id
    el = soup.find(tag, id=identifier)
    if el:
        return True

    # By class
    el = soup.find(tag, class_=identifier)
    if el:
        return True

    # By data attribute (data-<identifier> present on the tag)
    el = soup.find(tag, attrs={f"data-{identifier}": True})
    if el:
        return True

    # Also check if identifier itself looks like a data attr value
    # e.g. identifier = "nav-links" might be id="nav-links" (already checked)
    # or a bare attribute match
    for found_tag in soup.find_all(tag):
        for attr_name, attr_val in found_tag.attrs.items():
            if attr_name.startswith("data-") and attr_val == identifier:
                return True
            # Check if identifier is among class list
            if attr_name == "class" and identifier in attr_val:
                return True

    return False


# ═══════════════════════════════════════════════════════════════════
# 3. validate_page
# ═══════════════════════════════════════════════════════════════════

def validate_page(assembled_html: str, spec: dict) -> tuple[bool, list[str]]:
    """Validate the fully assembled page.

    Checks:
      - No duplicate IDs across the entire page
      - All component IDs from spec are present
      - Component order in DOM matches layout_order
    """
    errors: list[str] = []
    soup = BeautifulSoup(assembled_html, "html.parser")

    # ── Duplicate IDs ────────────────────────────────────────────
    all_ids: dict[str, int] = {}
    for el in soup.find_all(True, id=True):
        eid = el["id"]
        all_ids[eid] = all_ids.get(eid, 0) + 1

    for eid, count in all_ids.items():
        if count > 1:
            errors.append(f"duplicate id '{eid}' appears {count} times in page")

    # ── Component IDs present ────────────────────────────────────
    layout_order = spec.get("layout_order", [])
    for cid in layout_order:
        if not soup.find(id=cid):
            errors.append(f"component '{cid}' from layout_order not found in page")

    # ── DOM order matches layout_order ───────────────────────────
    # Collect positions of component root elements in document order
    found_order: list[str] = []
    for el in soup.find_all(True, id=True):
        if el["id"] in layout_order:
            if el["id"] not in found_order:
                found_order.append(el["id"])

    if found_order != layout_order:
        errors.append(
            f"component order mismatch: DOM has {found_order}, "
            f"spec expects {layout_order}"
        )

    return (len(errors) == 0, errors)


# ═══════════════════════════════════════════════════════════════════
# Self-test
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    _passed = 0
    _failed = 0

    def _check(label: str, condition: bool, detail: str = ""):
        global _passed, _failed
        if condition:
            _passed += 1
            print(f"  PASS  {label}")
        else:
            _failed += 1
            print(f"  FAIL  {label}  {detail}")

    # ── Valid spec ───────────────────────────────────────────────
    print("\n=== validate_spec ===")
    good_spec = {
        "page_title": "Test Page",
        "color_theme": {
            "primary": "blue-600",
            "secondary": "gray-200",
            "accent": "amber-400",
            "background": "white-50",
            "text": "gray-900",
        },
        "layout_order": ["hero-section", "features-grid"],
        "components": [
            {
                "id": "hero-section",
                "type": "hero",
                "required_elements": [
                    {"tag": "h1", "identifier": "hero-title"},
                    {"tag": "p", "identifier": "hero-subtitle"},
                ],
                "content": {"heading": "Welcome"},
                "style_hints": "full-width centered",
                "interactions": ["smooth-scroll"],
            },
            {
                "id": "features-grid",
                "type": "features",
                "required_elements": [
                    {"tag": "div", "identifier": "feature-cards"},
                ],
                "content": {"heading": "Features"},
                "style_hints": "3-col grid",
            },
        ],
    }
    ok, errs = validate_spec(good_spec)
    _check("valid spec passes", ok, str(errs))

    # Duplicate id
    bad_spec_dup = json.loads(json.dumps(good_spec))
    bad_spec_dup["components"][1]["id"] = "hero-section"
    bad_spec_dup["layout_order"] = ["hero-section"]
    ok, errs = validate_spec(bad_spec_dup)
    _check("duplicate id caught", not ok and any("duplicate" in e for e in errs), str(errs))

    # Missing from layout_order
    bad_spec_layout = json.loads(json.dumps(good_spec))
    bad_spec_layout["layout_order"] = ["hero-section"]
    ok, errs = validate_spec(bad_spec_layout)
    _check(
        "missing layout_order entry caught",
        not ok and any("missing from layout_order" in e for e in errs),
        str(errs),
    )

    # Extra in layout_order
    bad_spec_extra = json.loads(json.dumps(good_spec))
    bad_spec_extra["layout_order"].append("ghost-section")
    ok, errs = validate_spec(bad_spec_extra)
    _check(
        "orphan layout_order entry caught",
        not ok and any("no matching component" in e for e in errs),
        str(errs),
    )

    # Empty required_elements
    bad_spec_noreq = json.loads(json.dumps(good_spec))
    bad_spec_noreq["components"][0]["required_elements"] = []
    ok, errs = validate_spec(bad_spec_noreq)
    _check(
        "empty required_elements caught",
        not ok and any("no required_elements" in e for e in errs),
        str(errs),
    )

    # ── validate_component ───────────────────────────────────────
    print("\n=== validate_component ===")
    good_html = """
    <section id="hero-section">
        <h1 id="hero-title">Welcome</h1>
        <p id="hero-subtitle">Sub text</p>
        <a data-smooth-scroll href="#features">Go</a>
        <style>.x{color:red}</style>
        <script>alert('xss')</script>
    </section>
    """
    comp_spec = good_spec["components"][0]
    ok, hard, soft = validate_component(good_html, comp_spec)
    _check("valid component passes", ok, str(hard + soft))

    # Missing root id (HARD error)
    bad_html_id = '<section id="wrong"><h1 id="hero-title">X</h1></section>'
    ok, hard, soft = validate_component(bad_html_id, comp_spec)
    _check(
        "wrong root id caught (hard)",
        not ok and any("mismatch" in e for e in hard),
        str(hard),
    )

    # Missing required element (SOFT warning — still passes)
    bad_html_req = '<section id="hero-section"><h1 id="hero-title">X</h1></section>'
    ok, hard, soft = validate_component(bad_html_req, comp_spec)
    _check(
        "missing required element is soft warning",
        ok and any("hero-subtitle" in e for e in soft),
        f"ok={ok} soft={soft}",
    )

    # Missing interaction data attr (SOFT warning — still passes)
    html_no_scroll = """
    <section id="hero-section">
        <h1 id="hero-title">X</h1>
        <p id="hero-subtitle">Y</p>
    </section>
    """
    ok, hard, soft = validate_component(html_no_scroll, comp_spec)
    _check(
        "missing interaction data-attr is soft warning",
        ok and any("smooth-scroll" in e for e in soft),
        f"ok={ok} soft={soft}",
    )

    # Hamburger interaction check (needs two selectors)
    hamburger_spec = {
        "id": "nav",
        "type": "navbar",
        "required_elements": [{"tag": "nav", "identifier": "main-nav"}],
        "content": {},
        "style_hints": "",
        "interactions": ["hamburger-toggle"],
    }
    html_hamburger_ok = """
    <nav id="nav">
        <nav id="main-nav">
            <button data-toggle="hamburger">Menu</button>
            <div data-hamburger-menu>Links</div>
        </nav>
    </nav>
    """
    ok, hard, soft = validate_component(html_hamburger_ok, hamburger_spec)
    _check("hamburger interaction valid", ok, str(hard + soft))

    html_hamburger_partial = """
    <nav id="nav">
        <nav id="main-nav">
            <button data-toggle="hamburger">Menu</button>
        </nav>
    </nav>
    """
    ok, hard, soft = validate_component(html_hamburger_partial, hamburger_spec)
    _check(
        "hamburger missing menu element is soft",
        ok and any("data-hamburger-menu" in e for e in soft),
        f"ok={ok} soft={soft}",
    )

    # Parse failure (HARD error)
    ok, hard, soft = validate_component("", {"id": "x"})
    _check("empty html caught (hard)", not ok and any("no elements" in e for e in hard), str(hard))

    # ── validate_page ────────────────────────────────────────────
    print("\n=== validate_page ===")
    good_page = """
    <!DOCTYPE html>
    <html>
    <body>
        <section id="hero-section"><h1>Hello</h1></section>
        <section id="features-grid"><div>Features</div></section>
    </body>
    </html>
    """
    ok, errs = validate_page(good_page, good_spec)
    _check("valid page passes", ok, str(errs))

    # Duplicate IDs
    dup_page = """
    <html><body>
        <section id="hero-section"><h1 id="hero-section">X</h1></section>
        <section id="features-grid"></section>
    </body></html>
    """
    ok, errs = validate_page(dup_page, good_spec)
    _check(
        "duplicate page ids caught",
        not ok and any("duplicate" in e for e in errs),
        str(errs),
    )

    # Missing component
    missing_page = """
    <html><body>
        <section id="hero-section"></section>
    </body></html>
    """
    ok, errs = validate_page(missing_page, good_spec)
    _check(
        "missing component caught",
        not ok and any("not found" in e for e in errs),
        str(errs),
    )

    # Wrong order
    wrong_order_page = """
    <html><body>
        <section id="features-grid"></section>
        <section id="hero-section"></section>
    </body></html>
    """
    ok, errs = validate_page(wrong_order_page, good_spec)
    _check(
        "wrong component order caught",
        not ok and any("order mismatch" in e for e in errs),
        str(errs),
    )

    # ── Helper functions ─────────────────────────────────────────
    print("\n=== helpers ===")

    html_with_style = '<div><style>.a{color:red}</style><p>hi</p></div>'
    stripped = strip_style_tags(html_with_style)
    _check("strip_style_tags removes style", "<style>" not in stripped and "<p>hi</p>" in stripped)

    html_with_script = '<div><script>alert(1)</script><p onclick="evil()">hi</p></div>'
    stripped = strip_script_tags(html_with_script)
    _check(
        "strip_script_tags removes script + onclick",
        "<script>" not in stripped and "onclick" not in stripped and "<p" in stripped,
        stripped,
    )

    combined = sanitize_component(
        '<div><style>.x{}</style><script>bad</script><p onmouseover="y">ok</p></div>'
    )
    _check(
        "sanitize_component strips both",
        "<style>" not in combined
        and "<script>" not in combined
        and "onmouseover" not in combined,
        combined,
    )

    # ── Summary ──────────────────────────────────────────────────
    print(f"\n{'='*50}")
    print(f"  {_passed} passed, {_failed} failed")
    if _failed:
        print("  SOME TESTS FAILED")
        raise SystemExit(1)
    else:
        print("  ALL TESTS PASSED")
