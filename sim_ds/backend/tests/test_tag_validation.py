import pytest
from backend.domain.models import ScenarioCreate, ScenarioSource
from backend.tests.helpers import scenario_payload
from pydantic import ValidationError


def make_tags(tags: list[str]) -> ScenarioCreate:
    data = scenario_payload().model_dump()
    data["tags"] = tags
    return ScenarioCreate.model_validate(data)


@pytest.mark.parametrize(
    "tag",
    ["A&B", "A|B", "A(B)", "AND", "or", "with space", "a,b", "a/b", "标签！"],
)
def test_rejects_reserved_or_special_tags(tag: str) -> None:
    with pytest.raises(ValidationError):
        make_tags([tag])


def test_accepts_chinese_letters_numbers_dash_underscore() -> None:
    created = make_tags(["雨天-夜间", "cut-in", "v2_demo", "场景01"])
    assert created.tags == ["雨天-夜间", "cut-in", "v2_demo", "场景01"]


def test_scenario_source_defaults_to_rsclbag() -> None:
    assert ScenarioSource().format == "rsclbag"


def test_scenario_source_drops_legacy_extract() -> None:
    source = ScenarioSource.model_validate(
        {"type": "record", "log_id": "log-1", "format": "rsclbag", "extract": {"clip_start_ts": 1}}
    )
    assert "extract" not in source.model_dump()
