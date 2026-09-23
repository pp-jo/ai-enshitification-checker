import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from aimeter.constants import DEFAULT_WATCHED_MODELS


class ConfigError(Exception):
    """Configuration could not be read or contains invalid settings."""


@dataclass(frozen=True)
class LoadedConfig:
    watched_models: list[str]
    source: Path


def default_config_path() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home and Path(xdg_config_home).is_absolute():
        base = Path(xdg_config_home)
    else:
        base = Path.home() / ".config"
    return base / "aimeter" / "config.toml"


def builtin_config_source() -> Path:
    """Return the file containing the built-in model list."""
    return Path(__file__).with_name("constants.py").resolve()


def load_config(config_path: str | Path | None = None) -> LoadedConfig:
    """Load the selected file, using built-in models only if no user file exists."""
    path = (
        default_config_path() if config_path is None else Path(config_path).expanduser()
    )
    try:
        with path.open("rb") as config_file:
            config = tomllib.load(config_file)
    except FileNotFoundError as exc:
        if config_path is None:
            return LoadedConfig(
                watched_models=DEFAULT_WATCHED_MODELS.copy(),
                source=builtin_config_source(),
            )
        raise ConfigError(f"Configuration file not found: {path}") from exc
    except OSError as exc:
        raise ConfigError(
            f"Cannot read configuration {path}: {exc.strerror or exc}"
        ) from exc
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Invalid TOML file {path}: {exc}") from exc

    models = config.get("watched_models")
    if not isinstance(models, list) or any(
        not isinstance(name, str) or not name.strip() for name in models
    ):
        raise ConfigError(
            f"Invalid configuration {path}: watched_models must be a list "
            'of non-empty model names (e.g. watched_models = ["gpt-5.5"]).'
        )
    return LoadedConfig(
        watched_models=[name.strip() for name in models], source=path.resolve()
    )


def load_watched_models(config_path: str | Path | None = None) -> list[str]:
    """Load only the watched model names from the selected configuration."""
    return load_config(config_path).watched_models
