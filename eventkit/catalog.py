"""Series and event types.

config/catalog.yml (in the data folder) lists the series and the event types:

    platform_title_es: Eventos y webinars
    series:
      - id: cepal-unu-merit
        name_es: "Innovación y desarrollo productivo: de la investigación a la política pública"
        name_en: "Innovation and productive development: from research to public policy"
        organizers_es: CEPAL y UNU-MERIT
        organizers_en: ECLAC and UNU-MERIT
      - id: individuales
        name_es: Eventos individuales
    types: [Webinar, Seminario presencial, Híbrido, Taller, Conferencia, Otro]

Each event stores its own classification in events/<id>/meta.yml (series, type), so moving
an event to another series is a one-line change and survives rebuilds.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from unidecode import unidecode

from . import paths

STANDALONE = "individuales"
DEFAULT_TYPES = ["Webinar", "Seminario presencial", "Híbrido", "Taller", "Conferencia", "Otro"]
_STANDALONE_ENTRY = {"id": STANDALONE, "name_es": "Eventos individuales", "name_en": "Standalone events",
                     "organizers_es": "CEPAL", "organizers_en": "ECLAC"}


def _file() -> Path:
    return paths.series_config_dir() / "catalog.yml"


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", unidecode(text or "").lower()).strip("-")
    return s[:40].strip("-") or "serie"


def load() -> dict:
    f = _file()
    cat = yaml.safe_load(f.read_text(encoding="utf-8")) if f.exists() else {}
    cat = cat or {}
    cat.setdefault("platform_title_es", "Eventos y webinars")
    cat.setdefault("platform_title_en", "Events and webinars")
    cat.setdefault("series", [])
    cat.setdefault("types", list(DEFAULT_TYPES))
    if not any(s["id"] == STANDALONE for s in cat["series"]):
        cat["series"].append(dict(_STANDALONE_ENTRY))
    return cat


def save(cat: dict):
    _file().parent.mkdir(parents=True, exist_ok=True)
    _file().write_text(yaml.safe_dump(cat, allow_unicode=True, sort_keys=False), encoding="utf-8")


def series_list() -> list[dict]:
    """Named series first (in catalog order), standalone events last."""
    ss = load()["series"]
    return [s for s in ss if s["id"] != STANDALONE] + [s for s in ss if s["id"] == STANDALONE]


def get_series(sid: str | None) -> dict:
    for s in load()["series"]:
        if s["id"] == sid:
            return s
    return dict(_STANDALONE_ENTRY)


def add_series(name_es: str, name_en: str = "", organizers_es: str = "", organizers_en: str = "") -> str:
    cat = load()
    base = slug(name_es)
    sid, n = base, 2
    ids = {s["id"] for s in cat["series"]}
    while sid in ids:
        sid, n = f"{base}-{n}", n + 1
    entry = {"id": sid, "name_es": name_es.strip(), "name_en": (name_en or name_es).strip(),
             "organizers_es": organizers_es.strip() or "CEPAL", "organizers_en": organizers_en.strip() or "ECLAC"}
    named = [s for s in cat["series"] if s["id"] != STANDALONE]
    cat["series"] = named + [entry] + [s for s in cat["series"] if s["id"] == STANDALONE]
    save(cat)
    return sid


def update_series(sid: str, **fields):
    cat = load()
    for s in cat["series"]:
        if s["id"] == sid:
            s.update({k: v for k, v in fields.items() if v is not None})
    save(cat)


def add_type(name: str):
    cat = load()
    if name and name not in cat["types"]:
        cat["types"].insert(max(0, len(cat["types"]) - 1), name)   # keep "Otro" last
        save(cat)


# ------------------------------------------------------------- per event
def _meta_file(eid: str) -> Path:
    return paths.events_dir() / eid / "meta.yml"


def event_meta(eid: str) -> dict:
    f = _meta_file(eid)
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.exists() else {}


def set_event_meta(eid: str, **fields):
    m = event_meta(eid)
    m.update({k: v for k, v in fields.items() if v is not None})
    _meta_file(eid).parent.mkdir(parents=True, exist_ok=True)
    _meta_file(eid).write_text(yaml.safe_dump(m, allow_unicode=True, sort_keys=False), encoding="utf-8")


def style_example_path(sid: str | None) -> Path:
    """A published article that the writer should imitate: per series, else the shared one."""
    own = paths.series_config_dir() / "styles" / f"{sid}.md"
    return own if own.exists() else paths.config_file("style_example_es.md")


def save_style_example(sid: str, text: str):
    f = paths.series_config_dir() / "styles" / f"{sid}.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text.strip() + "\n", encoding="utf-8")


# ------------------------------------------------------------- migration
def ensure() -> bool:
    """Create catalog.yml on first run and file every unclassified event.

    Old single-series folders (config/series.yml) become the first series; their events are
    marked as webinars of that series. Returns True if anything changed."""
    changed = False
    if not _file().exists():
        old = paths.series_config_dir() / "series.yml"
        cat = load()
        if old.exists():
            o = yaml.safe_load(old.read_text(encoding="utf-8")) or {}
            first = {"id": slug(o.get("dashboard_title_es") or o.get("series_name_es") or "serie"),
                     "name_es": o.get("series_name_es") or o.get("dashboard_title_es") or "Serie",
                     "name_en": o.get("series_name_en") or o.get("series_name_es") or "Series",
                     "organizers_es": o.get("organizers_es", "CEPAL"),
                     "organizers_en": o.get("organizers_en", "ECLAC")}
            cat["series"] = [first] + [s for s in cat["series"] if s["id"] != first["id"]]
        save(cat)
        changed = True
    ed = paths.events_dir()
    if ed.exists():
        default = series_list()[0]["id"]
        for d in sorted(p for p in ed.iterdir() if (p / "raw").is_dir()):
            if not event_meta(d.name).get("series"):
                set_event_meta(d.name, series=default, type=event_meta(d.name).get("type") or "Webinar")
                changed = True
    return changed
