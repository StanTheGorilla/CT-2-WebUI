"""Precision-Design Page Assembler.

Stitches validated components into the final HTML page using the static
wrapper template. Handles script injection and component patching.
"""
from pathlib import Path
from bs4 import BeautifulSoup
from ct1.templates.snippets import get_snippets

_WRAPPER_PATH = Path(__file__).parent.parent / "templates" / "wrapper.html"
_WRAPPER = _WRAPPER_PATH.read_text(encoding="utf-8")


def assemble_page(
    page_title: str,
    component_html: dict[str, str],
    layout_order: list[str],
    spec: dict,
) -> str:
    """Assemble final HTML page from validated components.

    1. Concatenate component HTML in layout_order
    2. Collect all interaction snippet IDs from spec
    3. Load + deduplicate snippets
    4. Replace {{PAGE_TITLE}}, {{COMPONENTS}}, {{SCRIPTS}} in wrapper

    Args:
        page_title: Page title from spec.
        component_html: Mapping of component id → validated HTML string.
        layout_order: Ordered list of component IDs.
        spec: Full spec dict (used to collect interaction IDs).

    Returns:
        Complete HTML page string.
    """
    # Concatenate components in order
    components_str = "\n".join(
        component_html[cid]
        for cid in layout_order
        if cid in component_html
    )

    # Collect all interaction snippet IDs from spec
    all_interactions: list[str] = []
    seen: set[str] = set()
    for comp in spec.get("components", []):
        for interaction in comp.get("interactions", []):
            if interaction not in seen:
                all_interactions.append(interaction)
                seen.add(interaction)

    # Load scripts (empty string if no interactions)
    scripts_str = get_snippets(all_interactions) if all_interactions else ""

    # Assemble
    html = _WRAPPER
    html = html.replace("{{PAGE_TITLE}}", page_title)
    html = html.replace("{{COMPONENTS}}", components_str)
    html = html.replace("{{SCRIPTS}}", scripts_str)

    return html


def patch_component(
    assembled_html: str,
    component_id: str,
    new_html: str,
) -> str:
    """Replace a single component in the assembled page by matching root element id.

    Finds the element with id=component_id in the assembled HTML and replaces
    the entire element (including children) with new_html.

    Args:
        assembled_html: The full page HTML.
        component_id: The id of the component to replace.
        new_html: The new component HTML to insert.

    Returns:
        Updated page HTML with the component replaced.
    """
    soup = BeautifulSoup(assembled_html, "html.parser")
    old_el = soup.find(id=component_id)

    if old_el is None:
        # Component not found — append before </body> as fallback
        body = soup.find("body")
        if body:
            new_soup = BeautifulSoup(new_html, "html.parser")
            body.append(new_soup)
        return str(soup)

    # Replace old element with new HTML
    new_soup = BeautifulSoup(new_html, "html.parser")
    old_el.replace_with(new_soup)

    return str(soup)


if __name__ == "__main__":
    print("=== Assembler self-test ===\n")

    # Test 1: Basic assembly
    spec = {
        "page_title": "Test Page",
        "color_theme": {},
        "layout_order": ["nav", "hero"],
        "components": [
            {"id": "nav", "type": "navbar", "interactions": ["hamburger-toggle"]},
            {"id": "hero", "type": "hero", "interactions": []},
        ],
    }
    html_map = {
        "nav": '<nav id="nav">Navigation</nav>',
        "hero": '<section id="hero"><h1>Hello</h1></section>',
    }

    result = assemble_page("Test Page", html_map, spec["layout_order"], spec)

    assert "<title>Test Page</title>" in result, "Title not injected"
    assert '<nav id="nav">Navigation</nav>' in result, "Nav component missing"
    assert '<section id="hero">' in result, "Hero component missing"
    assert result.index("nav") < result.index("hero"), "Order wrong"
    assert 'data-toggle="hamburger"' in result, "Hamburger snippet missing"
    print("PASS  basic assembly")

    # Test 2: No interactions
    spec_no_js = {
        "page_title": "Static",
        "layout_order": ["hero"],
        "components": [{"id": "hero", "type": "hero"}],
    }
    result2 = assemble_page("Static", {"hero": '<section id="hero">Hi</section>'}, ["hero"], spec_no_js)
    assert "<script>" not in result2, "Scripts should be absent"
    print("PASS  no interactions = no scripts")

    # Test 3: Patch component
    page = '<html><body><nav id="nav">Old</nav><section id="hero">Old</section></body></html>'
    patched = patch_component(page, "hero", '<section id="hero">NEW</section>')
    assert "NEW" in patched, "Patch not applied"
    assert "Old" in patched, "Other component should remain"
    print("PASS  patch_component")

    # Test 4: Patch non-existent component (append)
    patched2 = patch_component(page, "footer", '<footer id="footer">Foot</footer>')
    assert "Foot" in patched2, "New component should be appended"
    print("PASS  patch_component (append to body)")

    print("\n=== All assembler tests passed ===")
