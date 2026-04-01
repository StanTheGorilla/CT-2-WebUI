# Validation Rework + Code Mode Fix — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the broken LLM fix cycle from ROUTE_CODE validation, always resolve UI validation state, and make code mode produce the correct file type for any language.

**Architecture:** Three independent changes: (1) formatter.py gains TypeScript/shell/SQL detection, (2) orchestrator.py removes the fix cycle for ROUTE_CODE and guards the HTML-specific retry loop, (3) +page.svelte unifies the download extension logic to one source of truth.

**Tech Stack:** Python (formatter, orchestrator), TypeScript/Svelte (frontend), pytest

---

### Task 1: Add TypeScript, shell, SQL detection to `detect_output_type`

**Files:**
- Modify: `ct1/core/formatter.py:97-136`
- Create: `tests/test_formatter_detection.py`

**Step 1: Write the failing tests**

Create `tests/test_formatter_detection.py`:

```python
import pytest
from ct1.core.formatter import detect_output_type


# ── Existing types must still pass ──────────────────────────────────

def test_detect_html_doctype():
    assert detect_output_type("<!DOCTYPE html><html>") == "html_page"

def test_detect_python_import():
    assert detect_output_type("import os\nprint('hi')") == "python_script"

def test_detect_cpp():
    assert detect_output_type("#include <stdio.h>\nint main() {}") == "cpp"

def test_detect_javascript_const():
    assert detect_output_type("const x = 1;\nconsole.log(x);") == "javascript"

def test_detect_go():
    assert detect_output_type("package main\nfunc main() {}") == "go"

def test_detect_rust():
    assert detect_output_type("fn main() {\n    println!(\"hi\");\n}") == "rust"


# ── New types ────────────────────────────────────────────────────────

def test_detect_typescript_interface():
    assert detect_output_type("interface User {\n  name: string;\n}") == "typescript"

def test_detect_typescript_type_alias():
    assert detect_output_type("type ID = string;\nconst x: ID = 'a';") == "typescript"

def test_detect_typescript_import_type():
    assert detect_output_type("import type { Foo } from './foo';") == "typescript"

def test_detect_shell_bash_shebang():
    assert detect_output_type("#!/bin/bash\necho hello") == "shell"

def test_detect_shell_sh_shebang():
    assert detect_output_type("#!/bin/sh\necho hello") == "shell"

def test_detect_shell_env_shebang():
    assert detect_output_type("#!/usr/bin/env bash\necho hi") == "shell"

def test_detect_sql_select():
    assert detect_output_type("SELECT * FROM users WHERE id = 1;") == "sql"

def test_detect_sql_create():
    assert detect_output_type("CREATE TABLE users (id INT PRIMARY KEY);") == "sql"

def test_detect_sql_insert():
    assert detect_output_type("INSERT INTO users (name) VALUES ('alice');") == "sql"

def test_detect_unknown_returns_other():
    assert detect_output_type("some random text with no code markers") == "other"
```

**Step 2: Run tests to verify they fail**

```bash
cd F:\AI_Workstation\web-ui
python -m pytest tests/test_formatter_detection.py -v
```

Expected: TypeScript, shell, SQL tests FAIL with "assert 'other' == 'typescript'" etc. Existing type tests should PASS.

**Step 3: Add detection in `ct1/core/formatter.py`**

In `detect_output_type`, replace lines 97-136 with the expanded version. Insert the new detections right after the existing `rust` block (after line 118), and before the content-based section:

```python
def detect_output_type(text: str) -> str:
    """Auto-detect the output type from code content.

    Returns: 'html_page', 'python_script', 'javascript', 'typescript',
             'cpp', 'go', 'rust', 'shell', 'sql', 'other'.
    Used when planner is unavailable (solo mode) or plan is None.
    """
    t = text.strip()
    lower = t[:500].lower()

    if lower.startswith(("<!doctype", "<html")):
        return "html_page"
    if lower.startswith(("import ", "from ", "def ", "class ", "#!", "#!/")):
        # Disambiguate: shebang lines are shell, not Python
        if lower.startswith(("#!/bin/bash", "#!/bin/sh", "#!/usr/bin/env bash",
                              "#!/usr/bin/env sh")):
            return "shell"
        return "python_script"
    if lower.startswith(("#include", "using namespace", "int main")):
        return "cpp"
    if lower.startswith(("const ", "let ", "var ", "function ",
                         "import {", "import '", "import \"")):
        # Disambiguate TypeScript: look for type annotations
        if ": string" in lower or ": number" in lower or ": boolean" in lower \
                or "interface " in lower or "type " in lower:
            return "typescript"
        return "javascript"
    if lower.startswith(("package ", "func ")):
        return "go"
    if lower.startswith(("use ", "fn ", "mod ", "pub ")):
        return "rust"
    if lower.startswith(("interface ", "type ")):
        return "typescript"
    if lower.startswith(("select ", "create ", "insert ", "drop ", "alter ",
                         "update ", "delete ")):
        return "sql"

    # Content-based detection for cases where preamble obscures the start
    if "<html" in lower or "<!doctype" in lower:
        return "html_page"
    if "def " in lower and ("import " in lower or "print(" in lower):
        return "python_script"
    if "#include" in lower and ("int main" in lower or "void " in lower):
        return "cpp"
    if "function " in lower and ("const " in lower or "let " in lower):
        return "javascript"
    if "import type" in lower or (": string" in lower and "interface " in lower):
        return "typescript"

    # Simple Python heuristics: scripts that start with print() or use
    # the standard __main__ guard but have no leading import/def
    if ("<html" not in lower and "<!doctype" not in lower
            and ("print(" in lower or "if __name__" in lower)):
        return "python_script"

    return "other"
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_formatter_detection.py -v
```

Expected: ALL PASS

**Step 5: Run full test suite to confirm no regression**

```bash
python -m pytest tests/ -v
```

Expected: All existing tests still pass.

**Step 6: Commit**

```bash
git add ct1/core/formatter.py tests/test_formatter_detection.py
git commit -m "feat: add TypeScript, shell, SQL detection to detect_output_type"
```

---

### Task 2: Expand the planner type list in `_SOLO_PLAN_SYSTEM`

**Files:**
- Modify: `ct1/core/orchestrator.py:666-694`

No new tests needed — this is a prompt/config change. The existing test suite covers the plan normalization path.

**Step 1: Update `_SOLO_PLAN_SYSTEM` and `valid_types`**

In `ct1/core/orchestrator.py`, replace lines 666-694:

```python
    _SOLO_PLAN_SYSTEM = (
        "Analyze this request and output ONLY a JSON object. No other text.\n"
        '{"output_type":"html_page"|"python_script"|"javascript"|"typescript"'
        '|"cpp"|"go"|"rust"|"shell"|"sql"|"other",'
        '"components":[{"id":1,"name":"short name","description":"what it does"}],'
        '"complexity":"simple"|"moderate"|"complex"}\n'
        "Max 5 components. Be concise."
    )
```

And in `_solo_plan`, replace the `valid_types` tuple:

```python
                valid_types = ("html_page", "python_script", "javascript",
                               "typescript", "cpp", "go", "rust", "shell",
                               "sql", "api", "other")
```

**Step 2: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: All pass.

**Step 3: Commit**

```bash
git add ct1/core/orchestrator.py
git commit -m "feat: expand planner output_type to include typescript, shell, sql"
```

---

### Task 3: Remove fix cycle for ROUTE_CODE, always emit `validated`

This is the core validation fix. The `elif is_code and not is_edit:` block at
`orchestrator.py:1354` currently runs a LLM fix cycle and never emits `validated` when
issues exist. Replace it so validation is observe-only and `validated` always fires.

**Files:**
- Modify: `ct1/core/orchestrator.py:1354-1408`

**Step 1: Write a failing test**

In `tests/test_orchestrator_deep.py` (or a new file `tests/test_validation_state.py`), add:

```python
"""Tests that ROUTE_CODE validation never fires a fix cycle and always emits validated."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ct1.core.formatter import validate_python


def test_validate_python_flags_syntax_error():
    """validate_python returns an issue for bad syntax."""
    issues = validate_python("def foo(\n    x =\n")
    assert len(issues) == 1
    assert "syntax error" in issues[0].lower()


def test_validate_python_passes_good_code():
    """validate_python returns no issues for valid Python."""
    issues = validate_python("def foo(x):\n    return x + 1\n")
    assert issues == []
```

Run:
```bash
python -m pytest tests/test_validation_state.py -v
```
Expected: PASS (these test the existing validator, confirming it works).

**Step 2: Replace the ROUTE_CODE validation block**

In `ct1/core/orchestrator.py`, replace lines 1354-1405 (the `elif is_code and not is_edit:` block through the `else: emit("validated", ...)`) with:

```python
        elif is_code and not is_edit:
            # Non-computer code: auto-detect output type for proper validation
            output_type = plan.get("output_type", "other") if plan else "other"
            if output_type in ("other", "html_page"):
                detected = detect_output_type(draft)
                if detected != "other":
                    output_type = detected

            # Extract code from markdown fences before validating.
            # Models often wrap output in explanation text + ```lang ... ``` fences.
            # Running ast.parse / HTML checks on raw markdown causes spurious errors.
            _validate_target = extract_code(strip_think_tags(final_response))

            # HTML: fix missing boilerplate deterministically (no AI)
            if output_type in ("html_page", "other") and detect_output_type(_validate_target) == "html_page":
                final_response = fix_html_structure(final_response)

            # Programmatic validation — informational only for ROUTE_CODE.
            # No LLM fix cycle: the model rarely fixes syntax errors correctly and
            # the UI gets stuck in a permanent "validation failed" state.
            issues = validate_output(_validate_target, output_type)

            if route == "ROUTE_CODE":
                # Soft validation: always resolve, never trigger a fix cycle.
                emit("validated", issues=issues,
                     review={"pass": True, "critical_issues": [],
                             "fix_instructions": ""})
            elif issues:
                emit("validating", issues=issues,
                     review={"pass": False, "critical_issues": issues,
                             "fix_instructions": ""})
                emit("fixing")

                fix_prompt = (
                    f"Fix ALL these issues in the code:\n"
                    + "\n".join(f"- {i}" for i in issues)
                    + f"\n\nOriginal code:\n{_validate_target}"
                )

                def on_fix_token(token, kind):
                    emit("token", text=token, kind=kind)

                fix_ovr = {**task_ovr}
                if "thinking_budget" in fix_ovr:
                    fix_ovr["thinking_budget"] = min(fix_ovr["thinking_budget"], 2048)
                fix_result = await self.engine.generate(
                    fix_prompt, route,
                    specialist_data=specialist_data,
                    plan=None,
                    conversation=conversation,
                    on_token=on_fix_token,
                    task_overrides=fix_ovr,
                )
                final_response = fix_result["text"]
                final_thinking = fix_result.get("thinking", "")
            else:
                emit("validated", issues=[],
                     review={"pass": True, "critical_issues": [],
                             "fix_instructions": ""})
```

**Step 3: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: All pass.

**Step 4: Commit**

```bash
git add ct1/core/orchestrator.py
git commit -m "fix: ROUTE_CODE validation is now observe-only — no fix cycle, always emits validated"
```

---

### Task 4: Guard HTML broken-section retry loop against ROUTE_CODE

The auto-retry loop at `orchestrator.py:1464-1469` runs for `output_type in ("html_page", "other")`. When `ROUTE_CODE` outputs "other" (unknown language), this triggers HTML section splitting on non-HTML code. Add an explicit route guard.

**Files:**
- Modify: `ct1/core/orchestrator.py:1467-1469`

**Step 1: Update the guard condition**

Replace lines 1467-1469:

```python
        _retry_output_type = plan.get("output_type", "other") if plan else "other"
        if (is_code and not is_edit and route not in ("ROUTE_COMPUTER", "ROUTE_CODE")
                and _retry_output_type in ("html_page", "other")):
```

(Only change: `route != "ROUTE_COMPUTER"` → `route not in ("ROUTE_COMPUTER", "ROUTE_CODE")`)

**Step 2: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: All pass.

**Step 3: Commit**

```bash
git add ct1/core/orchestrator.py
git commit -m "fix: exclude ROUTE_CODE from HTML broken-section retry loop"
```

---

### Task 5: Fix frontend file extension and download logic

**Files:**
- Modify: `ct1/web/src/routes/+page.svelte:112-128, 254-264`

No Python tests for frontend. Verify manually after change.

**Step 1: Expand `planTypeToExt`**

Replace lines 254-264 in `+page.svelte`:

```typescript
    function planTypeToExt(type: string | undefined | null): string {
        switch (type) {
            case 'html_page':     return 'html';
            case 'python_script': return 'py';
            case 'javascript':    return 'js';
            case 'typescript':    return 'ts';
            case 'cpp':           return 'cpp';
            case 'go':            return 'go';
            case 'rust':          return 'rs';
            case 'shell':         return 'sh';
            case 'sql':           return 'sql';
            default:              return 'txt';
        }
    }
```

**Step 2: Fix `downloadBlob` MIME map and `downloadCode`**

Replace lines 112-128:

```typescript
    function downloadBlob(code: string, ext: string = 'txt') {
        if (!code) return;
        const mimeMap: Record<string, string> = {
            html: 'text/html', htm: 'text/html',
            py:   'text/x-python',
            js:   'text/javascript', ts: 'text/typescript',
            sh:   'text/x-sh',
            sql:  'text/x-sql',
            cpp:  'text/x-c++src', go: 'text/x-go', rs: 'text/x-rustsrc',
        };
        const mime = mimeMap[ext] || 'text/plain';
        const blob = new Blob([code], { type: mime });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `output.${ext}`;
        a.click();
        URL.revokeObjectURL(url);
    }

    function downloadCode() {
        downloadBlob($chat.response, planTypeToExt($chat.plan?.output_type));
    }
```

**Step 3: Manual smoke test**

Start the app and verify:
- Ask "write a Python script that prints hello" → code badge shows `.py`, download saves as `output.py`
- Ask "write a TypeScript interface for a User" → badge shows `.ts`, download saves `output.ts`
- Ask "write a bash script to list files" → badge shows `.sh`
- Ask for HTML page → still shows `.html`, preview still works

**Step 4: Commit**

```bash
git add ct1/web/src/routes/+page.svelte
git commit -m "fix: unify download ext to planTypeToExt; add typescript/shell/sql types"
```

---

### Task 6: Run full regression suite and verify

**Step 1: Run all tests**

```bash
cd F:\AI_Workstation\web-ui
python -m pytest tests/ -v
```

Expected: All pass.

**Step 2: Manual end-to-end spot check**

- Python request: no fix cycle fires, no validation warning, `.py` download
- HTML design request: design pipeline unchanged, preview works
- Computer mode: unchanged, file tree works

**Step 3: Final commit if any loose ends**

```bash
git add -p   # stage only what changed
git commit -m "chore: post-validation-rework cleanup"
```

---

## Summary of changes

| Task | File | What changes |
|------|------|-------------|
| 1 | `ct1/core/formatter.py` | Add TypeScript / shell / SQL detection |
| 1 | `tests/test_formatter_detection.py` | New: detection unit tests |
| 2 | `ct1/core/orchestrator.py:666-694` | Expand planner type list |
| 3 | `ct1/core/orchestrator.py:1354-1405` | ROUTE_CODE: soft validation, always emit validated |
| 4 | `ct1/core/orchestrator.py:1468` | Guard broken-section retry from ROUTE_CODE |
| 5 | `ct1/web/src/routes/+page.svelte:112-128,254-264` | Fix download ext + MIME map |
