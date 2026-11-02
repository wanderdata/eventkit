"""Build the static dashboard (public/) published by GitLab Pages.

The page holds aggregate numbers only (no names, no e-mails). Summaries are
embedded as markdown and offered as Word downloads.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import normalize as N
from . import store
from .summarize import series_config

from . import paths


def _labels():
    r = N.sector_rules()["labels"]
    return {k: {"es": v["es"], "en": v["en"]} for k, v in r.items()}


def _country_en():
    data, _ = N._countries()
    return {k: v["en"] for k, v in data.items()}


def build_site(out: Path | None = None) -> Path:
    out = out or paths.public_dir()
    events = store.load_events()
    att = store.load_attendance()
    series = store.series_metrics(att, events) if len(att) else {}
    out.mkdir(parents=True, exist_ok=True)
    payload_events = []
    for e in events:
        edir = paths.events_dir() / e["id"]
        files = {}
        texts = {}
        for lang in ("es", "en"):
            md = edir / f"summary_{lang}.md"
            dx = edir / f"summary_{lang}.docx"
            if md.exists():
                texts[lang] = md.read_text(encoding="utf-8")
            if dx.exists():
                dest = out / "events" / e["id"]
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dx, dest / dx.name)
                files[lang] = f"events/{e['id']}/{dx.name}"
        review = (edir / "review.md").read_text(encoding="utf-8") if (edir / "review.md").exists() else ""
        ev = {k: v for k, v in e.items() if k not in ("chat",)}
        ev["chat"] = {k: v for k, v in e.get("chat", {}).items() if k != "links"}
        ev["summary"] = texts
        ev["docx"] = files
        ev["review"] = review
        ev["series"] = series.get("per_event", {}).get(e["id"], {})
        payload_events.append(ev)

    cfg = series_config()
    payload = {
        "config": {k: cfg.get(k) for k in ("dashboard_title_es", "dashboard_title_en", "series_name_es", "series_name_en")},
        "events": payload_events,
        "series": {k: v for k, v in series.items() if k != "per_event"},
        "sectors": _labels(),
        "country_en": _country_en(),
    }
    html = paths.config_file("dashboard.html").read_text(encoding="utf-8").replace(
        "/*__DATA__*/null", json.dumps(payload, ensure_ascii=False, default=str).replace("</", "<\\/"))
    (out / "index.html").write_text(html, encoding="utf-8")
    print(f"  dashboard → {out / 'index.html'}")
    return out / "index.html"
