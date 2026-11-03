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
    return {k: {"es": v["es"], "en": v["en"], "es_def": v.get("es_def", v["es"].lower())} for k, v in r.items()}


def _country_en():
    data, _ = N._countries()
    return {k: v["en"] for k, v in data.items()}


def embed_html(index_html: str, tab: str = "series") -> str:
    """Dashboard HTML for embedding in another app: no header/tabs, opens on `tab`."""
    inject = f"window.EK_EMBED=true;window.EK_TAB={json.dumps(tab)};"
    return index_html.replace("const DATA =", inject + "const DATA =", 1)


def metrics_bundle(att, events) -> dict:
    """Cross-event metrics for everything, and for each series on its own."""
    if not len(att):
        return {"global": {}, "series": {}}
    from . import catalog as CAT
    out = {"global": store.series_metrics(att, events), "series": {}}
    sids = []
    for e in events:
        sid = e.get("series") or CAT.series_list()[0]["id"]
        e["series"] = sid
        if sid not in sids:
            sids.append(sid)
    for sid in sids:
        evs = [e for e in events if e["series"] == sid]
        ids = {e["id"] for e in evs}
        out["series"][sid] = store.series_metrics(att[att.event_id.isin(ids)], evs)
    a = att[(att.attended == 1) & (att.role.fillna("attendee").isin(["attendee", ""]))]
    smap = {e["id"]: e["series"] for e in events}
    k = a.assign(s=a.event_id.map(smap)).groupby("pid").s.nunique()
    out["global"]["multi_series"] = int((k >= 2).sum())
    return out


def build_site(out: Path | None = None) -> Path:
    from . import catalog as CAT
    out = out or paths.public_dir()
    events = store.load_events()
    att = store.load_attendance()
    for e in events:  # classification lives in meta.yml (it can change after processing)
        m = CAT.event_meta(e["id"])
        e["series"] = m.get("series") or e.get("series")
        e["type"] = m.get("type") or e.get("type") or "Webinar"
    mb = metrics_bundle(att, events)
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
        ev["sm"] = mb["series"].get(e.get("series"), {}).get("per_event", {}).get(e["id"], {})   # within its series
        ev["gm"] = mb["global"].get("per_event", {}).get(e["id"], {})                           # across all events
        payload_events.append(ev)

    cat = CAT.load()
    used = {e.get("series") for e in events}
    payload = {
        "config": {"title_es": cat["platform_title_es"], "title_en": cat["platform_title_en"]},
        "types": cat["types"],
        "series_list": [{"id": s["id"], "name": s["name_es"], "organizers": s.get("organizers_es", "")}
                        for s in CAT.series_list() if s["id"] in used],
        "events": payload_events,
        "global": {k: v for k, v in mb["global"].items() if k != "per_event"},
        "series_metrics": {sid: {k: v for k, v in m.items() if k != "per_event"} for sid, m in mb["series"].items()},
        "sectors": _labels(),
        "country_en": _country_en(),
    }
    html = paths.config_file("dashboard.html").read_text(encoding="utf-8").replace(
        "/*__DATA__*/null", json.dumps(payload, ensure_ascii=False, default=str).replace("</", "<\\/"))
    (out / "index.html").write_text(html, encoding="utf-8")
    print(f"  dashboard → {out / 'index.html'}")
    return out / "index.html"
