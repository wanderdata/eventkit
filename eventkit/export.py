"""Mailing list export: unique e-mails from the raw exports of one or more events.

Contains personal data: only for use inside the private app.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from . import normalize as N
from . import parsers as P
from . import paths

COLUMNS = ["correo", "nombre", "pais", "organizacion", "cargo",
           "sesiones_inscritas", "sesiones_asistidas", "fechas", "ultima_sesion"]


def _event_people(edir: Path) -> pd.DataFrame:
    """One row per e-mail for one event: registered / attended flags + profile."""
    raw = edir / "raw"
    if not raw.exists():
        return pd.DataFrame()
    kinds = {}
    for f in sorted(raw.iterdir()):
        k = P.detect(f)
        if k and k not in kinds:
            kinds[k] = f
    rows = {}
    if "registration" in kinds:
        reg = P.read_registration(kinds["registration"])
        webex = reg.attrs.get("source") == "webex"
        for r in reg.itertuples():
            pais = N.country(r.country_raw)
            # Webex pre-selects "United States": keep it only with a US-looking e-mail
            if webex and pais == "Estados Unidos" and not r.email.endswith((".us", ".edu", ".gov")):
                pais = N.country_from_email(r.email)
            rows[r.email] = dict(nombre=r.name, pais=pais, organizacion=r.organization,
                                 cargo=r.job_title, inscrito=1, asistio=0)
    if "participants" in kinds:
        people, _, _ = P.read_participants(kinds["participants"])
        for r in people.itertuples():
            if r.email.startswith("noemail:"):
                continue
            row = rows.setdefault(r.email, dict(nombre=f"{r.first_name or ''} {r.last_name or ''}".strip()
                                                if str(r.first_name) not in ("N/A", "nan", "None") else r.display_name,
                                                pais=None, organizacion=None, cargo=None, inscrito=0))
            row["asistio"] = 1
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([{"correo": e, **v} for e, v in rows.items()])
    df["fecha"] = edir.name
    return df


def mailing_list(event_ids: list[str] | None = None, only_attended: bool = False) -> pd.DataFrame:
    """Unique e-mails across the given events (default: all). Latest profile wins."""
    edirs = sorted(d for d in paths.events_dir().iterdir() if (d / "raw").is_dir()) if paths.events_dir().exists() else []
    if event_ids is not None:
        edirs = [d for d in edirs if d.name in set(event_ids)]
    frames = [f for f in (_event_people(d) for d in edirs) if len(f)]
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.concat(frames, ignore_index=True)
    df = df[df.correo.str.contains(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", regex=True, na=False)]
    if only_attended:
        df = df[df.asistio == 1]
    df = df.sort_values("fecha")
    clean = lambda s: s.where(s.notna() & (s.astype(str).str.strip() != "") & (s.astype(str) != "nan"))
    for c in ("nombre", "pais", "organizacion", "cargo"):
        df[c] = clean(df[c])
    agg = df.groupby("correo").agg(
        nombre=("nombre", "last"), pais=("pais", "last"), organizacion=("organizacion", "last"),
        cargo=("cargo", "last"), sesiones_inscritas=("inscrito", "sum"), sesiones_asistidas=("asistio", "sum"),
        fechas=("fecha", lambda x: ", ".join(sorted(set(x)))), ultima_sesion=("fecha", "max"),
    ).reset_index()
    return agg.sort_values(["sesiones_asistidas", "correo"], ascending=[False, True])[COLUMNS].reset_index(drop=True)


def to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    head = {"correo": "Correo", "nombre": "Nombre", "pais": "País", "organizacion": "Organización",
            "cargo": "Cargo", "sesiones_inscritas": "Sesiones inscritas", "sesiones_asistidas": "Sesiones asistidas",
            "fechas": "Fechas", "ultima_sesion": "Última sesión"}
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.rename(columns=head).to_excel(xw, index=False, sheet_name="Correos")
        ws = xw.sheets["Correos"]
        for col, width in zip("ABCDEFGHI", (34, 28, 16, 34, 26, 10, 10, 26, 13)):
            ws.column_dimensions[col].width = width
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
    return buf.getvalue()


def to_text(df: pd.DataFrame) -> bytes:
    """One address per line: paste into Outlook/BCC or a mailing tool."""
    return ("\n".join(df.correo) + "\n").encode("utf-8")
