
from evals.run_eval import score_response


def test_score_response_matches_expected_tokens():
    assert score_response("hello world", ["hello"]) is True
    assert score_response("hello world", ["missing"]) is False
