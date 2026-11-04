"""Participation statistics for one event (pure code, no AI)."""
from __future__ import annotations

import pandas as pd

from . import normalize as N
from .parsers import ChatMsg, EventMeta, is_question

# Bump when event_stats() gains or changes fields; the app then recomputes older events.
STATS_VERSION = 3


def enrich(people: pd.DataFrame, reg: pd.DataFrame | None) -> pd.DataFrame:
    """Add country / gender / sector to a frame with an `email` column, using registration data."""
    p = people.copy()
    if reg is not None and len(reg):
        p = p.merge(reg[["email", "name", "country_raw", "gender_raw", "organization", "job_title"]],
                    on="email", how="left")
    else:
        for c in ("name", "country_raw", "gender_raw", "organization", "job_title"):
            p[c] = None
    p["country"] = p["country_raw"].map(N.country)
    p["country_note"] = None
    # Webex registration forms pre-select "United States": only trust it with a US-looking e-mail.
    if reg is not None and reg.attrs.get("source") == "webex":
        us = p["country"] == "Estados Unidos"
        us_mail = p["email"].str.contains(r"\.(?:us|edu|gov)$", regex=True, na=False)
        sus = us & ~us_mail
        inferred = p.loc[sus, "email"].map(N.country_from_email)
        p.loc[sus, "country"] = inferred
        p.loc[sus, "country_note"] = inferred.map(lambda x: "inferred_from_email" if pd.notna(x) else "us_default_discarded")
    p["gender"] = p["gender_raw"].map(N.gender)
    sec = [N.sector(o, e, t) for o, e, t in zip(p["organization"], p["email"], p["job_title"])]
    p["sector"] = [s for s, _ in sec]
    p["sector_method"] = [m for _, m in sec]
    return p


def _shares(series: pd.Series, top=None) -> list[dict]:
    s = series.dropna()
    n = len(s)
    if not n:
        return []
    vc = s.value_counts()
    if top:
        vc = vc.head(top)
    return [{"key": k, "n": int(v), "pct": round(100 * v / n, 1)} for k, v in vc.items()]


def demographics(p: pd.DataFrame) -> dict:
    known_c = p["country"].dropna()
    lac = known_c.map(lambda c: N.country_meta(c).get("lac", False))
    g = p["gender"].dropna()
    sec = p.loc[p["sector"] != "sin_clasificar", "sector"]
    return {
        "n": int(len(p)),
        "with_profile": int(p["country_raw"].notna().sum()),
        "countries_n": int(known_c.nunique()),
        "countries": _shares(p["country"]),
        "lac_pct": round(100 * lac.mean(), 1) if len(lac) else None,
        "women_pct": round(100 * (g == "F").mean(), 1) if len(g) else None,
        "gender": _shares(p["gender"]),
        "sectors": _shares(sec),
        "sector_unclassified": int((p["sector"] == "sin_clasificar").sum()),
    }


def timeline(raw_rows: pd.DataFrame, meta: EventMeta, step_min=2) -> list[dict]:
    """Number of people connected over time (attendees only)."""
    r = raw_rows[(raw_rows["role"] == "attendee") & raw_rows["join"].notna() & raw_rows["leave"].notna()]
    if r.empty:
        return []
    first = r["join"].min()
    start = (meta.planned_start if meta.planned_start is not None else first) - pd.Timedelta(minutes=15)
    start = max(start, first.floor("min"))
    end = meta.actual_end if meta.actual_end is not None else r["leave"].max()
    out = []
    t = start.floor("min")
    while t <= end:
        n = r.loc[(r["join"] <= t) & (r["leave"] > t), "email"].nunique()
        off = int(round((t - meta.planned_start).total_seconds() / 60)) if meta.planned_start is not None else None
        out.append({"t": t.strftime("%H:%M"), "n": int(n), "m": off})   # m = minutes from scheduled start
        t += pd.Timedelta(minutes=step_min)
    return out


def minutes_histogram(aud: pd.DataFrame) -> list[dict]:
    """How long the audience stayed connected."""
    edges = [(0, 15, "Menos de 15 min"), (15, 30, "15–30 min"), (30, 45, "30–45 min"),
             (45, 60, "45–60 min"), (60, 10_000, "Más de 60 min")]
    n = len(aud)
    out = []
    for lo, hi, lab in edges:
        k = int(((aud.minutes >= lo) & (aud.minutes < hi)).sum())
        out.append({"key": lab, "n": k, "pct": round(100 * k / n, 1) if n else 0})
    return out


def chat_by_time(chat: list[ChatMsg], timeline_pts: list[dict], staff_names: set[str]) -> list[dict]:
    """Audience chat messages per timeline step (aligned with the attendance curve)."""
    if not chat or not timeline_pts:
        return []
    times = [m.time for m in chat if N.norm_text(m.name) not in staff_names]
    labels = [p["t"] for p in timeline_pts]
    counts = [0] * len(labels)
    for tm in times:
        hhmm = tm.strftime("%H:%M")
        idx = max((i for i, lab in enumerate(labels) if lab <= hhmm), default=None)
        if idx is not None:
            counts[idx] += 1
    return [{"t": lab, "n": c} for lab, c in zip(labels, counts)]


def registration_curve(reg: pd.DataFrame, meta: EventMeta, days=30) -> dict:
    """Cumulative registrations by day before the event (last `days` days)."""
    if meta.planned_start is None or "registered_at" not in reg or reg.registered_at.isna().all():
        return {}
    ev_day = meta.planned_start.normalize()
    d = (reg.registered_at.dropna().dt.normalize() - ev_day).dt.days
    total = int(len(d))
    pts = []
    for k in range(-days, 1):
        pts.append({"d": k, "n": int((d <= k).sum())})
    return {"points": pts, "total": total,
            "before_window": int((d < -days).sum()),
            "last_week_pct": round(100 * ((d > -7) & (d <= 0)).sum() / total, 1) if total else None,
            "same_day_pct": round(100 * (d == 0).sum() / total, 1) if total else None}


def chat_stats(chat: list[ChatMsg], staff_names: set[str]) -> dict:
    if not chat:
        return {"messages": 0, "people": 0, "questions": 0, "links": []}
    df = pd.DataFrame([{"name": m.name, "text": m.text, "q": is_question(m.text)} for m in chat])
    aud = df[~df.name.map(N.norm_text).isin(staff_names)]
    links = sorted({l for m in chat for l in m.links})
    return {
        "messages": int(len(df)),
        "people": int(aud.name.nunique()),
        "questions": int(aud.q.sum()),
        "askers": int(aud[aud.q].name.nunique()),
        "links": links,
    }


def event_stats(people: pd.DataFrame, raw_rows: pd.DataFrame, meta: EventMeta,
                reg: pd.DataFrame | None, chat: list[ChatMsg]) -> tuple[dict, pd.DataFrame, pd.DataFrame | None]:
    p = enrich(people, reg)
    aud = p[p.role == "attendee"]
    staff = p[p.role != "attendee"]
    staff_names = {N.norm_text(x) for x in staff.display_name.dropna()}

    dur_min = None
    if meta.planned_start is not None and meta.actual_end is not None:
        dur_min = max(1, (meta.actual_end - meta.planned_start).total_seconds() / 60)

    s = {
        "stats_version": STATS_VERSION,
        "webinar_name": meta.webinar_name,
        "date": meta.planned_start.strftime("%Y-%m-%d") if meta.planned_start is not None else None,
        "planned_start": str(meta.planned_start) if meta.planned_start is not None else None,
        "actual_end": str(meta.actual_end) if meta.actual_end is not None else None,
        "duration_min": round(dur_min) if dur_min else None,
        "participants_total": int(len(p)),          # all unique connections incl. organizers/panel
        "attendees": int(len(aud)),                 # audience only
        "organizers_panel": int(len(staff)),
        "minutes_median": float(aud.minutes.median()) if len(aud) else None,
        "minutes_mean": round(float(aud.minutes.mean()), 1) if len(aud) else None,
        "stayed_half_pct": round(100 * (aud.minutes >= dur_min / 2).mean(), 1) if (len(aud) and dur_min) else None,
        "connection": _shares(aud["connection"]),
        "demographics": demographics(p),             # over all participants (as reported publicly)
        "timeline": timeline(raw_rows, meta),
        "chat": chat_stats(chat, staff_names),
    }
    tl = s["timeline"]
    s["peak_concurrent"] = max((x["n"] for x in tl), default=None)
    s["minutes_hist"] = minutes_histogram(aud)
    s["chat_timeline"] = chat_by_time(chat, tl, staff_names)
    if meta.planned_start is not None and len(aud):
        s["late_pct"] = round(100 * (aud["join"] > meta.planned_start + pd.Timedelta(minutes=10)).mean(), 1)

    regp = None
    if reg is not None and len(reg):
        regp = enrich(reg[["email"]], reg)
        s["data_notes"] = {
            "us_default_discarded": int((regp.country_note == "us_default_discarded").sum()),
            "country_inferred_from_email": int((regp.country_note == "inferred_from_email").sum()),
            "registration_source": reg.attrs.get("source"),
        }
        attended = set(p.email)
        regp["attended"] = regp.email.isin(attended)
        s["registrations"] = int(len(regp))
        s["registration_curve"] = registration_curve(reg, meta)
        s["registered_attended"] = int(regp.attended.sum())
        s["conversion_pct"] = round(100 * regp.attended.mean(), 1)
        s["walk_ins"] = int((~aud.email.isin(set(regp.email))).sum())
        s["registration_demographics"] = demographics(regp)
        # country funnel: registered vs attended
        f = regp.dropna(subset=["country"]).groupby("country").agg(reg=("email", "size"), att=("attended", "sum"))
        s["country_funnel"] = [{"key": k, "reg": int(r.reg), "att": int(r.att)}
                               for k, r in f.sort_values("reg", ascending=False).head(15).iterrows()]
    return s, p, regp
