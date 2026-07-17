"""Shared language maps and small helpers for the orchestrator pipeline."""
import re


_EXT_TO_LANG = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".html": "html", ".htm": "html", ".css": "css", ".cpp": "cpp",
    ".c": "c", ".go": "go", ".rs": "rust", ".json": "json", ".sh": "bash",
}

# Maps detect_output_type() strings → canonical fence/lang name used in prompts & metadata
_OUTPUT_TYPE_TO_LANG = {
    "javascript": "javascript", "typescript": "typescript",
    "python_script": "python", "api": "python",
    "html_page": "html", "cpp": "cpp", "go": "go",
    "rust": "rust", "bash": "bash", "css": "css", "json": "json",
}

# Human-readable label per fence name (for edit prompts)
_LANG_TO_LABEL = {
    "javascript": "JavaScript", "typescript": "TypeScript",
    "python": "Python", "html": "HTML", "cpp": "C++",
    "go": "Go", "rust": "Rust", "bash": "Bash/Shell",
    "css": "CSS", "json": "JSON",
}


def _detect_lang_from_response(text: str) -> str:
    """Extract primary language from first fenced code block tag."""
    m = re.search(r'^```([\w+]+)', text, re.MULTILINE)
    if m:
        lang = m.group(1).lower()
        _ALIASES = {"py": "python", "js": "javascript", "ts": "typescript",
                    "sh": "bash", "shell": "bash", "c++": "cpp", "rs": "rust"}
        return _ALIASES.get(lang, lang)
    return "text"
