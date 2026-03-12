import re

class TensionDetector:
    NEGATION_WORDS = {"not", "no", "never", "wrong", "incorrect", "false",
                      "disagree", "contrary", "instead", "however", "but",
                      "actually", "flawed", "irrelevant", "opposite"}

    def quick_check(self, alpha: str, beta: str, gamma: str) -> dict:
        responses = [alpha.lower(), beta.lower(), gamma.lower()]

        negations = sum(
            1 for r in responses
            if any(word in r.split() for word in self.NEGATION_WORDS)
        )

        word_sets = [set(re.findall(r'\b[a-z]{4,}\b', r)) for r in responses]
        if word_sets[0] and word_sets[1] and word_sets[2]:
            overlap_ab = len(word_sets[0] & word_sets[1]) / max(len(word_sets[0] | word_sets[1]), 1)
            overlap_ac = len(word_sets[0] & word_sets[2]) / max(len(word_sets[0] | word_sets[2]), 1)
            overlap_bc = len(word_sets[1] & word_sets[2]) / max(len(word_sets[1] | word_sets[2]), 1)
            avg_overlap = (overlap_ab + overlap_ac + overlap_bc) / 3
        else:
            avg_overlap = 1.0

        has_tension = negations >= 2 or avg_overlap < 0.15
        tension_score = (negations / 3) * 0.5 + (1 - avg_overlap) * 0.5

        return {
            "has_tension": has_tension,
            "tension_score": round(tension_score, 3),
            "negation_count": negations,
            "avg_word_overlap": round(avg_overlap, 3)
        }
