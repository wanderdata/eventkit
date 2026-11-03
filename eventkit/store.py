"""Series-wide store: one JSON with per-event stats + one anonymised attendance table.

No names or e-mails are written here. Each person is represented by a salted
SHA-256 of their e-mail, so the same person can be recognised across events
without storing who they are. The salt comes from the EVENTKIT_SALT environment
variable (a masked CI/CD variable in GitLab); keep it secret and never change it,
or returning-attendee counts will reset.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

import pandas as pd

from . import paths


def _events_json():
    return paths.data_dir() / "events.json"


def _attendance():
    return paths.data_dir() / "attendance.csv"


def _local_salt():
    return paths.home() / ".eventkit_salt"   # git-ignored fallback for local runs


def _salt() -> str:
    s = os.environ.get("EVENTKIT_SALT")
    if s:
        return s
    if _local_salt().exists():
        return _local_salt().read_text().strip()
    s = secrets.token_hex(32)
    _local_salt().write_text(s)
    print(f"[eventkit] No EVENTKIT_SALT set; created {_local_salt()}. "
          "Use the SAME value as the GitLab variable or IDs won't match across runs.", file=sys.stderr)
    return s


def pid(email: str) -> str:
    return hashlib.sha256((_salt() + email.strip().lower()).encode()).hexdigest()[:16]


def load_events() -> list[dict]:
    if _events_json().exists():
        return json.loads(_events_json().read_text(encoding="utf-8"))
    return []


def save_event(record: dict):
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    evs = [e for e in load_events() if e["id"] != record["id"]]
    evs.append(record)
    evs.sort(key=lambda e: e.get("date") or e["id"])
    _events_json().write_text(json.dumps(evs, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def load_attendance() -> pd.DataFrame:
    if _attendance().exists():
        return pd.read_csv(_attendance(), dtype={"pid": str, "event_id": str})
    return pd.DataFrame(columns=["pid", "event_id", "registered", "attended", "role",
                                 "minutes", "country", "gender", "sector"])


def save_attendance(event_id: str, people: pd.DataFrame, regp: pd.DataFrame | None):
    """people: enriched participants; regp: enriched registrants (or None)."""
    rows = {}
    if regp is not None:
        for r in regp.itertuples():
            rows[r.email] = dict(registered=1, attended=0, role="", minutes=0,
                                 country=r.country, gender=r.gender, sector=r.sector)
    for r in people.itertuples():
        base = rows.get(r.email, dict(registered=0, country=r.country, gender=r.gender, sector=r.sector))
        base.update(attended=1, role=r.role, minutes=r.minutes)
        rows[r.email] = base
    new = pd.DataFrame([{"pid": pid(e), "event_id": event_id, **v}
                        for e, v in rows.items() if not e.startswith("noemail:")])
    old = load_attendance()
    old = old[old.event_id != event_id]
    out = pd.concat([old, new], ignore_index=True).sort_values(["event_id", "pid"])
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    out.to_csv(_attendance(), index=False)
    return out


def series_metrics(att: pd.DataFrame, events: list[dict]) -> dict:
    """Cross-event metrics recomputed from the anonymised table."""
    order = [e["id"] for e in events]
    a = att[(att.attended == 1) & (att.role.fillna("attendee").isin(["attendee", ""]))].copy()
    a["k"] = a.event_id.map({e: i for i, e in enumerate(order)})
    first_seen = a.groupby("pid").k.min()
    per_event = {}
    for i, eid in enumerate(order):
        cur = a[a.k == i]
        ret = cur.pid.map(first_seen).lt(i).sum()
        per_event[eid] = {"returning": int(ret), "new": int(len(cur) - ret),
                          "returning_pct": round(float(100 * ret / len(cur)), 1) if len(cur) else None}
    counts = a.groupby("pid").event_id.nunique()
    reg = att[att.registered == 1]
    return {
        "events": len(order),
        "unique_attendees": int(a.pid.nunique()),
        "unique_registrants": int(reg.pid.nunique()),
        "attended_2plus": int((counts >= 2).sum()),
        "attendance_frequency": {str(k): int(v) for k, v in counts.value_counts().sort_index().items()},
        "per_event": per_event,
    }


def delete_event(event_id: str):
    """Remove an event everywhere (folder, events.json, attendance)."""
    import shutil
    evs = [e for e in load_events() if e["id"] != event_id]
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    _events_json().write_text(json.dumps(evs, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    att = load_attendance()
    att[att.event_id != event_id].to_csv(_attendance(), index=False)
    d = paths.events_dir() / event_id
    if d.exists():
        shutil.rmtree(d)
