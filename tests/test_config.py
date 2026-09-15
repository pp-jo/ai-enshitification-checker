from pathlib import Path

import pytest

from aimeter.cli import main
from aimeter.config import ConfigError, load_watched_models
from aimeter.constants import WATCHED_MODELS


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    return home


def write_config(path: Path, content: str = 'watched_models = ["custom-model"]') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_missing_user_config_uses_defaults() -> None:
    assert load_watched_models() == WATCHED_MODELS


@pytest.mark.parametrize("xdg_value", [None, "", "relative/config"])
def test_home_config_replaces_defaults(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, xdg_value: str | None
) -> None:
    if xdg_value is not None:
        monkeypatch.setenv("XDG_CONFIG_HOME", xdg_value)
    write_config(
        isolated_home / ".config" / "aimeter" / "config.toml",
        '# Moje modele\nwatched_models = ["second-model", "first-model"]',
    )

    assert load_watched_models() == ["second-model", "first-model"]


@pytest.mark.parametrize("xdg_exists", [True, False])
def test_xdg_directory_replaces_home_config_location(
    tmp_path: Path,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    xdg_exists: bool,
) -> None:
    write_config(isolated_home / ".config" / "aimeter" / "config.toml")
    xdg_dir = tmp_path / "custom config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_dir))
    if xdg_exists:
        write_config(xdg_dir / "aimeter" / "config.toml", 'watched_models = ["xdg-model"]')

    assert load_watched_models() == (["xdg-model"] if xdg_exists else WATCHED_MODELS)


@pytest.mark.parametrize("path_style", ["absolute", "relative", "tilde"])
def test_explicit_config_takes_precedence(
    tmp_path: Path,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    path_style: str,
) -> None:
    xdg_dir = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_dir))
    write_config(xdg_dir / "aimeter" / "config.toml", "invalid TOML")
    path = write_config(isolated_home / "my models.toml")
    selected = {
        "absolute": str(path),
        "relative": "home/my models.toml",
        "tilde": "~/my models.toml",
    }[path_style]

    assert load_watched_models(selected) == ["custom-model"]


def test_current_directory_config_is_not_discovered(tmp_path: Path) -> None:
    write_config(tmp_path / "config.toml")

    assert load_watched_models() == WATCHED_MODELS


def test_missing_explicit_config_does_not_fall_back(isolated_home: Path) -> None:
    write_config(isolated_home / ".config" / "aimeter" / "config.toml")
    missing = isolated_home / "missing.toml"

    with pytest.raises(ConfigError, match="Nie znaleziono") as exc:
        load_watched_models(missing)
    assert str(missing) in str(exc.value)


def test_empty_list_replaces_defaults(tmp_path: Path) -> None:
    path = write_config(tmp_path / "empty.toml", "watched_models = []")

    assert load_watched_models(path) == []


@pytest.mark.parametrize(
    "content, message",
    [
        (b"watched_models = [", "TOML"),
        (b"\xff", "TOML"),
        (b"", "watched_models"),
        (b"models = []", "watched_models"),
        (b'watched_models = "gpt-5.5"', "watched_models"),
        (b"watched_models = {}", "watched_models"),
        (b'watched_models = ["gpt-5.5", 42]', "watched_models"),
        (b"watched_models = [true]", "watched_models"),
        (b'watched_models = [""]', "watched_models"),
        (b'watched_models = ["   "]', "watched_models"),
    ],
)
def test_invalid_user_config_is_an_error(
    isolated_home: Path, content: bytes, message: str
) -> None:
    path = write_config(isolated_home / ".config" / "aimeter" / "config.toml")
    path.write_bytes(content)

    with pytest.raises(ConfigError, match=message) as exc:
        load_watched_models()
    assert str(path) in str(exc.value)


def test_unreadable_user_config_is_an_error(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_config(isolated_home / ".config" / "aimeter" / "config.toml")
    original_open = Path.open

    def denied_open(self: Path, *args, **kwargs):
        if self == path:
            raise PermissionError(13, "Permission denied", str(path))
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied_open)
    with pytest.raises(ConfigError, match="Nie można odczytać") as exc:
        load_watched_models()
    assert str(path) in str(exc.value)


@pytest.mark.parametrize("explicit", [True, False])
def test_cli_config_error_exits_before_running(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    explicit: bool,
) -> None:
    if explicit:
        path = isolated_home / "missing.toml"
        args = ["aimeter", "--config", str(path)]
    else:
        path = write_config(
            isolated_home / ".config" / "aimeter" / "config.toml", "invalid TOML"
        )
        args = ["aimeter"]
    monkeypatch.setattr("sys.argv", args)
    monkeypatch.setattr("aimeter.cli.run", lambda **kwargs: pytest.fail("run was called"))

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert str(path) in output.err
    assert "Traceback" not in output.err
