import tempfile
from ct1.memory.journal import Journal
from ct1.memory.journal_reader import JournalReader

def test_journal_writes_and_reads_entry():
    with tempfile.TemporaryDirectory() as tmpdir:
        j = Journal(tmpdir)
        entry = {
            "goal": "test task",
            "rounds": 1,
            "mind_contributions": {
                "alpha": {"useful": True, "summary": "helped"},
                "beta": {"useful": False, "summary": "stalled"},
                "gamma": {"useful": True, "summary": "challenged"},
            },
            "outcome": "solved",
            "lesson": "alpha+gamma work well together",
            "self_score": 0.8
        }
        j.write(entry)
        entries = j.read_all()
        assert len(entries) == 1
        assert entries[0]["goal"] == "test task"
        assert entries[0]["lesson"] == "alpha+gamma work well together"

def test_journal_count():
    with tempfile.TemporaryDirectory() as tmpdir:
        j = Journal(tmpdir)
        for i in range(3):
            j.write({"goal": f"g{i}", "rounds": 1, "mind_contributions": {},
                     "outcome": "ok", "lesson": f"lesson {i}", "self_score": 0.7})
        assert j.count() == 3

def test_journal_reader_extracts_lessons():
    with tempfile.TemporaryDirectory() as tmpdir:
        j = Journal(tmpdir)
        j.write({"goal": "g1", "rounds": 1, "mind_contributions": {}, "outcome": "o1",
                 "lesson": "alpha is great for creativity", "self_score": 0.9})
        j.write({"goal": "g2", "rounds": 2, "mind_contributions": {}, "outcome": "o2",
                 "lesson": "don't over-deliberate on facts", "self_score": 0.6})
        reader = JournalReader(tmpdir)
        lessons = reader.get_recent_lessons(n=5)
        assert "alpha is great for creativity" in lessons
        assert "don't over-deliberate on facts" in lessons

def test_journal_reader_stats():
    with tempfile.TemporaryDirectory() as tmpdir:
        j = Journal(tmpdir)
        j.write({"goal": "g1", "rounds": 1, "mind_contributions": {"alpha": {"useful": True}},
                 "outcome": "ok", "lesson": "l1", "self_score": 0.8})
        j.write({"goal": "g2", "rounds": 3, "mind_contributions": {"alpha": {"useful": False}},
                 "outcome": "ok", "lesson": "l2", "self_score": 0.4})
        reader = JournalReader(tmpdir)
        stats = reader.get_stats()
        assert stats["total"] == 2
        assert "avg_self_score" in stats
        assert "avg_rounds" in stats
