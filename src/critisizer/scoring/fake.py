import json

from critisizer.scoring.contract import ASPECT_CODES, ScoringRequest


class FakeScorer:
    """Deterministic scorer for tests and offline work. Costs nothing."""

    name = "fake"

    def score(self, request: ScoringRequest) -> str:
        indicators = []
        for index, excerpt in enumerate(request.excerpts[: len(ASPECT_CODES)]):
            indicators.append(
                {
                    "aspect": ASPECT_CODES[index],
                    "name": f"Fake finding {index + 1}",
                    "score": 20 + 10 * index,
                    "description": "A fixed finding from the fake scorer.",
                    "evidence": [
                        {
                            "source_id": excerpt.id,
                            "quote": " ".join(excerpt.text.split())[:80],
                        }
                    ],
                }
            )
        return json.dumps({"indicators": indicators})