import json
import tempfile
from ct1.memory.journal import Journal
from ct1.evolution.preference_extractor import PreferenceExtractor
from ct1.evolution.adapter_manager import AdapterManager

def _make_journal(tmpdir, entries):
    j = Journal(tmpdir)
    for e in entries:
        j.write(e)
    return j

def test_preference_extractor_finds_pairs():
    with tempfile.TemporaryDirectory() as tmpdir:
        j = _make_journal(tmpdir, [
            {"goal": "explain gravity physics", "rounds": 1,
             "mind_contributions": {}, "outcome": "gravity is a force",
             "lesson": "good", "self_score": 0.9},
            {"goal": "explain gravity physics well", "rounds": 3,
             "mind_contributions": {}, "outcome": "gravity maybe is a force",
             "lesson": "bad", "self_score": 0.2},
        ])
        extractor = PreferenceExtractor(tmpdir)
        pairs = extractor.extract_pairs(min_score_gap=0.3)
        assert len(pairs) >= 1
        assert "prompt" in pairs[0]
        assert "chosen" in pairs[0]
        assert "rejected" in pairs[0]

def test_preference_extractor_empty_journal():
    with tempfile.TemporaryDirectory() as tmpdir:
        extractor = PreferenceExtractor(tmpdir)
        pairs = extractor.extract_pairs()
        assert pairs == []

def test_adapter_manager_promote_and_rollback():
    with tempfile.TemporaryDirectory() as tmpdir:
        import os
        manager = AdapterManager(tmpdir)

        # Create a fake adapter file
        fake_adapter = os.path.join(tmpdir, "fake_brain.bin")
        with open(fake_adapter, "w") as f:
            f.write("fake weights")

        promoted = manager.promote("brain", fake_adapter)
        assert "brain_v" in promoted

        rolled = manager.rollback("brain")
        assert rolled == True

def test_adapter_manager_no_rollback_when_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AdapterManager(tmpdir)
        result = manager.rollback("brain")
        assert result == False
