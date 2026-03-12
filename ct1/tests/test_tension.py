from ct1.core.tension_detector import TensionDetector

def test_detects_disagreement():
    td = TensionDetector()
    alpha = "The answer is clearly A because of X."
    beta = "No, the answer is B. X is wrong and irrelevant."
    gamma = "There is no answer. The question is flawed and incorrect."
    result = td.quick_check(alpha, beta, gamma)
    assert result["has_tension"] == True
    assert "tension_score" in result

def test_detects_agreement():
    td = TensionDetector()
    alpha = "Python is the right choice for this task."
    beta = "Python is great here, good choice."
    gamma = "Use Python, definitely."
    result = td.quick_check(alpha, beta, gamma)
    assert result["has_tension"] == False

def test_returns_required_keys():
    td = TensionDetector()
    result = td.quick_check("a", "b", "c")
    assert "has_tension" in result
    assert "tension_score" in result
    assert "negation_count" in result
    assert "avg_word_overlap" in result
