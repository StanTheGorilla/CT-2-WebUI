import tempfile, os
from pathlib import Path
from ct2.memory.session_store import SessionStore

def test_write_and_read_latest():
    with tempfile.TemporaryDirectory() as d:
        store = SessionStore(d)
        store.write("We discussed quantum entanglement.")
        assert store.read_latest() == "We discussed quantum entanglement."

def test_read_latest_none_when_empty():
    with tempfile.TemporaryDirectory() as d:
        store = SessionStore(d)
        assert store.read_latest() is None

def test_multiple_writes_returns_latest():
    with tempfile.TemporaryDirectory() as d:
        store = SessionStore(d)
        store.write("First session.")
        store.write("Second session.")
        assert store.read_latest() == "Second session."
