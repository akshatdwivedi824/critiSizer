import json

from critisizer.scoring.citations import resolve_citations
from critisizer.scoring.contract import SourceExcerpt
from critisizer.scoring.sentences import split_sentences
from critisizer.scoring.verifier import verify_answer

TEXT = (
    "Headline of the article about the policy\n"
    "The central bank said nearly all banned notes had come back to banks. "
    "Short one. "
    "Traders reported weeks of lost sales after the sudden announcement."
)
EXCERPTS = [SourceExcerpt(1, "Hindustan Times", TEXT, 2, "https://x/1", "T")]


def answer(evidence):
    item = {
        "aspect": "outcome_failure",
        "name": "Notes returned",
        "score": 60,
        "description": "Almost all banned notes were returned.",
        "evidence": evidence,
    }
    return json.dumps({"indicators": [item]})


def test_sentences_are_whole_and_within_limits():
    sentences = split_sentences(TEXT)
    assert "Short one." not in sentences  # too short to cite
    assert all(30 <= len(s) <= 300 for s in sentences)
    assert all(s in " ".join(TEXT.split()) for s in sentences)


def test_a_sentence_number_becomes_an_accepted_verbatim_quote():
    raw = answer([{"source_id": 1, "sentence": 2}])
    resolved = resolve_citations(raw, EXCERPTS)
    result = verify_answer(resolved, EXCERPTS)
    assert len(result.accepted) == 1
    quote = json.loads(resolved)["indicators"][0]["evidence"][0]["quote"]
    assert quote in " ".join(TEXT.split())


def test_a_bad_sentence_number_is_rejected_not_guessed():
    for bad in (0, 99, "2", True):
        raw = answer([{"source_id": 1, "sentence": bad}])
        result = verify_answer(resolve_citations(raw, EXCERPTS), EXCERPTS)
        assert result.accepted == []


def test_a_bad_source_number_is_rejected():
    raw = answer([{"source_id": 7, "sentence": 1}])
    result = verify_answer(resolve_citations(raw, EXCERPTS), EXCERPTS)
    assert result.accepted == []


def test_existing_quotes_pass_through_untouched():
    quote = "The central bank said nearly all banned notes had come back to banks."
    raw = answer([{"source_id": 1, "quote": quote}])
    assert json.loads(resolve_citations(raw, EXCERPTS)) == json.loads(raw)


def test_garbage_input_is_returned_unchanged():
    assert resolve_citations("not json", EXCERPTS) == "not json"