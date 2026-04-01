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
