import pytest
from pydantic import ValidationError
from research_app.research_contract import MeaningReview, NarrativeReview, QuestionCoverageReview


def checked_finding():
    return {
        "finding_id": "f",
        "inference_audit": "This claim was checked against its original evidence.",
        "violations": [],
    }


@pytest.mark.parametrize("encoding", ["array", "singleton", "keyed", "keyed_with_id"])
def test_equivalent_check_encodings_keep_exact_verdict(encoding):
    row = checked_finding()
    rows = {
        "array": [row],
        "singleton": row,
        "keyed": {"f": {k: v for k, v in row.items() if k != "finding_id"}},
        "keyed_with_id": {"f": row},
    }
    result = MeaningReview.model_validate({"checks": rows[encoding]})
    assert result.model_dump() == {"checks": [row]}


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"f": {}},
        {"f": "supported"},
        {"other": checked_finding()},
        {"finding_id": "f", "violations": []},
        {**checked_finding(), "approved": True},
    ],
)
def test_normalization_never_creates_a_verdict_or_ignores_conflicts(invalid):
    with pytest.raises(ValidationError):
        MeaningReview.model_validate({"checks": invalid})


def test_source_rejection_and_unanswered_question_survive_shape_normalization():
    result = NarrativeReview.model_validate(
        {
            "claims": {"f": {"verdict": "unsupported", "reason": "Missing source", "repair": "retrieve"}},
            "questions": {"q": {"answered": False, "reason": "Required paper date missing"}},
        }
    )
    assert result.claims[0].verdict == "unsupported"
    coverage = QuestionCoverageReview.model_validate({"questions": result.questions[0].model_dump()})
    assert not coverage.questions[0].answered and not coverage.questions[0].resolved_gaps


def test_only_well_formed_double_encoded_review_rows_are_decoded():
    """Fixture saved verbatim from gold/BTC run a361de1e: `checks` arrived as a string."""
    import json
    from pathlib import Path

    import pytest
    from pydantic import ValidationError
    from research_app.research_contract import MeaningReview

    raw = json.loads((Path(__file__).parent / "fixtures/meaning-review-double-encoded.json").read_text())
    # The real string also contains unescaped quotes, so it is not valid JSON; guessing a
    # repair would invent reviewer output. It must still fail and trigger a schema retry.
    with pytest.raises(ValidationError):
        MeaningReview.model_validate(raw)
    check = {"finding_id": "f", "inference_audit": "只描述样本内指标，未外推", "violations": []}
    review = MeaningReview.model_validate({"checks": json.dumps([check], ensure_ascii=False)})
    assert review.checks[0].finding_id == "f"
    for bad in ["checks look fine", '[{"finding_id": "f"']:
        with pytest.raises(ValidationError):
            MeaningReview.model_validate({"checks": bad})
