import pytest

from aimeter.cli import main


def test_help_copy_is_english(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["aimeter", "-h"])

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 0
    output = capsys.readouterr()
    help_text = output.out
    assert output.err == ""
    assert "check AI model trends" in help_text
    assert "Examples:" in help_text
    assert "--config FILE" in help_text
    assert "repeatable" in help_text
    for phrase in (
        "PLIK",
        "Przykłady",
        "sprawdź trendy",
        "standardowy output",
        "własna lista",
        "Więcej szczegółów",
    ):
        assert phrase not in help_text
