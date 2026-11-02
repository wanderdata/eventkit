"""Where things live.

The *series folder* (a private repository per webinar series) holds the data:

    <home>/inbox/    uploads waiting to be processed
    <home>/events/   one folder per event (raw exports + outputs)
    <home>/data/     anonymised series-wide tables
    <home>/config/   series settings and optional overrides
    <home>/public/   the generated dashboard

<home> is the --home option, else $EVENTKIT_HOME, else the current directory.
Files in <home>/config/ override the package defaults with the same name.
"""
from __future__ import annotations

import os
from pathlib import Path

PKG = Path(__file__).resolve().parent
DEFAULTS = PKG / "defaults"
TEMPLATES = PKG / "templates"

_home: Path | None = None


def set_home(p: str | Path | None):
    global _home
    _home = Path(p).resolve() if p else None


def home() -> Path:
    if _home is not None:
        return _home
    env = os.environ.get("EVENTKIT_HOME")
    return Path(env).resolve() if env else Path.cwd()


def config_file(name: str) -> Path:
    """Series override if present, else the packaged default (may not exist)."""
    p = home() / "config" / name
    return p if p.exists() else DEFAULTS / name


def series_config_dir() -> Path:
    return home() / "config"


def events_dir() -> Path:
    return home() / "events"


def data_dir() -> Path:
    return home() / "data"


def inbox_dir() -> Path:
    return home() / "inbox"


def public_dir() -> Path:
    return home() / "public"
