import math

import pytest

from aimeter.parsing import (
    PayloadError,
    parse_finite_number,
    parse_history,
    parse_leaderboard,
    parse_stale_hours,
)


@pytest.mark.parametrize("value", [0, 47, -12.5, 1e308])
def test_finite_numbers_are_floats(value: int | float) -> None:
    result = parse_finite_number(value)
    assert isinstance(result, float)
    assert result == value


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        "47",
        "",
        [],
        {},
        float("nan"),
        float("inf"),
        -float("inf"),
        pytest.param(10**400, id="integer-too-large-for-float"),
    ],
)
def test_invalid_numbers_are_missing(value: object) -> None:
    assert parse_finite_number(value) is None


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, 0),
        (6, 6),
        (6.9, 6),
        ("6", 6),
        ("6h", 6),
        (" 6.5H ", 6),
        ("0h", 0),
        ("1e2h", 100),
    ],
)
def test_stale_hours_accepts_supported_formats(value: object, expected: int) -> None:
    assert parse_stale_hours(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        "",
        "h",
        "6hh",
        "six",
        -1,
        -0.5,
        "-6h",
        "NaN",
        "Infinity",
        "-Infinity",
        "1e400h",
        "NaNh",
        float("nan"),
        float("inf"),
        -float("inf"),
        [],
        {},
        pytest.param(10**400, id="integer-too-large-for-float"),
    ],
)
def test_invalid_stale_hours_are_missing(value: object) -> None:
    assert parse_stale_hours(value) is None


def test_leaderboard_normalizes_fields_and_preserves_zero() -> None:
    parsed = parse_leaderboard(
        {
            "success": True,
            "data": [
                {
                    "name": " example ",
                    "id": 123,
                    "currentScore": 0,
                    "trend": "stable",
                    "isStale": False,
                    "staleDuration": "0h",
                    "stability": 0,
                }
            ],
        }
    )
    entry = parsed.by_name["example"]
    assert entry.name == "example"
    assert entry.model_id == "123"
    assert entry.current_score == 0.0
    assert isinstance(entry.current_score, float)
    assert entry.trend == "stable"
    assert entry.is_stale is False
    assert entry.stale_hours == 0
    assert entry.stability == 0.0
    assert parsed.warnings == []


@pytest.mark.parametrize("null_fields", [False, True])
def test_optional_fields_can_be_absent_or_null(null_fields: bool) -> None:
    entry: dict[str, object] = {"name": "example"}
    if null_fields:
        entry.update(
            dict.fromkeys(
                [
                    "id",
                    "currentScore",
                    "trend",
                    "isStale",
                    "staleDuration",
                    "stability",
                ]
            )
        )
    parsed = parse_leaderboard({"success": True, "data": [entry]})
    result = parsed.by_name["example"]
    assert result.current_score is None
    assert result.model_id is None
    assert result.trend is None
    assert result.is_stale is None
    assert result.stale_hours is None
    assert result.stability is None
    assert parsed.warnings == []


@pytest.mark.parametrize(
    "field,value,attribute",
    [
        ("currentScore", True, "current_score"),
        ("currentScore", "47", "current_score"),
        ("currentScore", float("nan"), "current_score"),
        ("currentScore", float("inf"), "current_score"),
        ("id", True, "model_id"),
        ("id", 1.5, "model_id"),
        ("id", [], "model_id"),
        ("id", "   ", "model_id"),
        ("trend", "sideways", "trend"),
        ("trend", [], "trend"),
        ("isStale", "false", "is_stale"),
        ("isStale", 1, "is_stale"),
        ("staleDuration", "Infinity", "stale_hours"),
        ("stability", "78", "stability"),
        ("stability", False, "stability"),
    ],
)
def test_bad_optional_fields_record_warnings(
    field: str, value: object, attribute: str, capsys: pytest.CaptureFixture[str]
) -> None:
    parsed = parse_leaderboard(
        {
            "success": True,
            "data": [{"name": "example", field: value}],
        }
    )
    assert getattr(parsed.by_name["example"], attribute) is None
    assert len(parsed.warnings) == 1
    assert "example" in parsed.warnings[0]
    assert field in parsed.warnings[0]
    output = capsys.readouterr()
    assert output.out == output.err == ""


@pytest.mark.parametrize("value,expected", [(" 123 ", "123"), ("a/b?c=d", "a/b?c=d")])
def test_string_ids_are_preserved(value: str, expected: str) -> None:
    parsed = parse_leaderboard(
        {
            "success": True,
            "data": [{"name": "example", "id": value}],
        }
    )
    assert parsed.by_name["example"].model_id == expected
    assert not parsed.warnings


@pytest.mark.parametrize("entry", [None, 4, [], {}, {"name": []}, {"name": "  "}])
def test_invalid_entries_are_skipped_without_losing_valid_models(entry: object) -> None:
    parsed = parse_leaderboard(
        {
            "success": True,
            "data": [entry, {"name": "example", "currentScore": 50}],
        }
    )
    assert list(parsed.by_name) == ["example"]
    assert len(parsed.warnings) == 1


def test_duplicate_names_keep_last_entry_with_warning() -> None:
    parsed = parse_leaderboard(
        {
            "success": True,
            "data": [
                {"name": "example", "currentScore": 40},
                {"name": " example ", "currentScore": 60},
            ],
        }
    )
    assert parsed.by_name["example"].current_score == 60
    assert len(parsed.warnings) == 1
    assert "example" in parsed.warnings[0]
    assert "duplicate" in parsed.warnings[0]


@pytest.mark.parametrize(
    "first,last,expected_score,expected_field_warnings",
    [("invalid", 60, 60, 0), (40, "invalid", None, 1)],
)
def test_duplicate_field_warnings_describe_only_the_selected_entry(
    first: object,
    last: object,
    expected_score: float | None,
    expected_field_warnings: int,
) -> None:
    parsed = parse_leaderboard(
        {
            "success": True,
            "data": [
                {"name": "example", "currentScore": first},
                {"name": "other", "stability": "invalid"},
                {"name": "example", "currentScore": last},
            ],
        }
    )
    assert parsed.by_name["example"].current_score == expected_score
    assert sum("duplicate" in warning for warning in parsed.warnings) == 1
    field_warnings = [
        warning for warning in parsed.warnings if "currentScore" in warning
    ]
    assert len(field_warnings) == expected_field_warnings
    assert any("other: invalid stability" in warning for warning in parsed.warnings)


def test_empty_leaderboard_differs_from_unreadable_entries() -> None:
    assert parse_leaderboard({"success": True, "data": []}).by_name == {}
    with pytest.raises(PayloadError, match="no entries"):
        parse_leaderboard({"success": True, "data": [{}, {"name": []}]})


@pytest.mark.parametrize("parser", [parse_leaderboard, parse_history])
@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        5,
        {},
        {"data": []},
        {"success": False, "data": []},
        {"success": 1, "data": []},
        {"success": "true", "data": []},
        {"success": "false", "data": []},
        {"success": None, "data": []},
        {"success": True},
        {"success": True, "data": None},
        {"success": True, "data": {}},
    ],
)
def test_both_endpoints_require_valid_envelopes(parser, payload: object) -> None:
    with pytest.raises(PayloadError):
        parser(payload)


def test_history_filters_points_and_counts_discarded_values() -> None:
    history = parse_history(
        {
            "success": True,
            "data": [
                {"score": 40},
                {"score": True},
                {"score": "50"},
                {"score": 60},
                {"score": float("nan")},
                {"score": float("inf")},
                {"score": 10**400},
                {"score": None},
                {},
                50,
                [],
                None,
            ],
        }
    )
    assert history.scores == [40.0, 60.0]
    assert all(math.isfinite(score) for score in history.scores)
    assert history.discarded_points == 10


def test_empty_and_entirely_invalid_histories_remain_distinguishable() -> None:
    empty = parse_history({"success": True, "data": []})
    invalid = parse_history({"success": True, "data": [{"score": False}]})
    assert empty.scores == invalid.scores == []
    assert empty.discarded_points == 0
    assert invalid.discarded_points == 1


def test_parse_stale_hours_rejects_bool() -> None:
    assert parse_stale_hours(True) is None
    assert parse_stale_hours(False) is None
    assert parse_stale_hours(6) == 6
    assert parse_stale_hours("6h") == 6
    assert parse_stale_hours(None) is None
