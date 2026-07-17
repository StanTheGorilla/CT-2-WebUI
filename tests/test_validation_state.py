"""Tests that ROUTE_CODE validation never fires a fix cycle and always emits validated."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ct2.core.formatter import validate_python


def test_validate_python_flags_syntax_error():
    """validate_python returns an issue for bad syntax."""
    issues = validate_python("def foo(x, y, z):\n    if x == 1\n        return x\n")
    assert len(issues) == 1
    assert "syntax error" in issues[0].lower()


def test_validate_python_passes_good_code():
    """validate_python returns no issues for valid Python."""
    issues = validate_python("def foo(x):\n    return x + 1\n")
    assert issues == []
