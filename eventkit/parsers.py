"""Readers for the files exported after a webinar.

Every reader works from file *content*, not file names, so colleagues can
upload the exports with whatever names Webex / Forms gives them.

Supported inputs
  participants   Webex "participant report"   (.csv UTF-16 tab, or .xlsx)
  registration   Webex registration report    (.csv / .xlsx)
                 Microsoft Forms export        (.xlsx)
  transcript     Webex transcript              (.txt  "h:mm:ss : Speaker : text")
  chat           Webex chat                    (.txt  "YYYY-MM-DD HH:MM : Name : text")
  ai_summary     Webex AI meeting summary      (.txt  starts "Meeting summary"/"Resumen de la reunión")
  slides         .pptx or .pdf
  event_yml      optional event.yml with manual overrides
"""
from __future__ import annotations

import html
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .normalize import norm_text

# ------------------------------------------------------------------ helpers

def _clean_cell(v):
    """Webex wraps values as ="..." to stop Excel from reformatting them."""
    if isinstance(v, str):
        v = v.strip()
        m = re.fullmatch(r'=?"+(.*?)"+', v)
        if m:
            v = m.group(1).strip()
    return v


def read_table(path: Path) -> pd.DataFrame | None:
    """Read csv/xlsx robustly (Webex uses UTF-16 + tabs). Returns None if not tabular."""
    suf = path.suffix.lower()
    df = None
    if suf in (".xlsx", ".xlsm", ".xls"):
        try:
            df = pd.read_excel(path, sheet_name=0, dtype=str)
        except Exception:
            return None
    elif suf in (".csv", ".tsv", ".txt"):
        raw = path.read_bytes()
        encs = ["utf-16"] if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else ["utf-8-sig", "latin-1"]
        for enc in encs:
            for sep in ("\t", ",", ";"):
                try:
                    d = pd.read_csv(io.BytesIO(raw), encoding=enc, sep=sep, dtype=str)
                except Exception:
                    continue
                if d.shape[1] >= 4:
                    df = d
                    break
            if df is not None:
                break
    if df is None:
        return None
    df.columns = [str(_clean_cell(c)).strip() for c in df.columns]
    return df.map(_clean_cell)


def _col(df: pd.DataFrame, *keywords, exclude=()) -> str | None:
    """First column whose normalized header contains any keyword."""
    for c in df.columns:
        n = norm_text(c)
        if any(k in n for k in keywords) and not any(x in n for x in exclude):
            return c
    return None


def _email_col(df: pd.DataFrame) -> str | None:
    """Column holding the most e-mail-looking values (Forms has a dummy 'Email' column)."""
    best, best_n = None, 0
    for c in df.columns:
        n = df[c].astype(str).str.contains(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", regex=True, na=False).sum()
        if n > best_n:
            best, best_n = c, n
    return best


def norm_email(e) -> str:
    e = str(e or "").strip().lower()
    return e if "@" in e else ""


def _minutes(v) -> float:
    m = re.search(r"([\d.,]+)", str(v or ""))
    return float(m.group(1).replace(",", ".")) if m else 0.0


# ------------------------------------------------------------- detection

def detect(path: Path) -> str | None:
    suf = path.suffix.lower()
    name = path.name.lower()
    if name in ("event.yml", "event.yaml"):
        return "event_yml"
    if suf in (".pptx", ".pdf"):
        return "slides"
    if suf == ".docx":
        return "docx"
    if suf in (".csv", ".xlsx", ".xls", ".tsv"):
        df = read_table(path)
        if df is None:
            return None
        cols = " | ".join(norm_text(c) for c in df.columns)
        if ("duracion de asistencia" in cols or "attendance duration" in cols
                or "duracion de la asistencia" in cols):
            return "participants"
        if any(k in cols for k in ("pais", "country")) and any(k in cols for k in ("genero", "gender")):
            return "registration"
        if "estado de registro" in cols or "registration status" in cols:
            return "registration"
        return None
    if suf == ".txt":
        head = path.read_text(encoding="utf-8-sig", errors="replace")[:4000]
        first = norm_text(head.splitlines()[0] if head.strip() else "")
        if first.startswith(("meeting summary", "resumen de la reunion", "resumen de reunion")):
            return "ai_summary"
        if re.search(r"^(-+>\s*)?\d{4}-\d{2}-\d{2} \d{2}:\d{2} : ", head, re.M):
            return "chat"
        if re.search(r"^\d{1,2}:\d{2}(:\d{2})? : ", head, re.M):
            return "transcript"
    return None


# ----------------------------------------------------------- participants

ROLE_RANK = {"host": 4, "cohost": 3, "panelist": 2, "presenter": 2, "attendee": 1}


@dataclass
class EventMeta:
    webinar_name: str = ""
    planned_start: pd.Timestamp | None = None
    actual_start: pd.Timestamp | None = None
    actual_end: pd.Timestamp | None = None


def read_participants(path: Path) -> tuple[pd.DataFrame, EventMeta]:
    """One row per unique e-mail (Webex adds a row per reconnection)."""
    df = read_table(path)
    c_email = _col(df, "correo electronico del asistente", "attendee email") or _email_col(df)
    c_disp = _col(df, "nombre para mostrar", "display name")
    c_first = _col(df, "nombre", "first name", exclude=("mostrar", "seminario", "sesion", "webinar", "session", "display"))
    c_last = _col(df, "apellido", "last name")
    c_role = _col(df, "funcion", "role")
    c_join = _col(df, "entrada", "unirse", "join time")
    c_leave = _col(df, "salida", "abandono", "leave time")
    c_dur = _col(df, "duracion de asistencia", "attendance duration", "duracion de la asistencia")
    c_conn = _col(df, "tipo de conexion", "connection type")

    meta = EventMeta()
    c = _col(df, "nombre del seminario web", "webinar name", "event name")
    meta.webinar_name = str(df[c].dropna().iloc[0]).strip() if c else ""
    c = _col(df, "hora de inicio planificada", "scheduled start")
    meta.planned_start = pd.to_datetime(df[c].dropna().iloc[0]) if c else None
    c = _col(df, "hora de inicio del seminario", "actual start", "webinar start time", exclude=("planificada", "scheduled"))
    meta.actual_start = pd.to_datetime(df[c].dropna().iloc[0]) if c else None
    c = _col(df, "hora de finalizacion del seminario", "actual end", "webinar end time", exclude=("planificada", "scheduled"))
    meta.actual_end = pd.to_datetime(df[c].dropna().iloc[0]) if c else None

    d = pd.DataFrame({
        "email": df[c_email].map(norm_email),
        "display_name": df[c_disp] if c_disp else "",
        "first_name": df[c_first] if c_first else "",
        "last_name": df[c_last] if c_last else "",
        "role": (df[c_role].fillna("attendee").str.lower().str.replace("-", "").str.strip()) if c_role else "attendee",
        "join": pd.to_datetime(df[c_join], errors="coerce") if c_join else pd.NaT,
        "leave": pd.to_datetime(df[c_leave], errors="coerce") if c_leave else pd.NaT,
        "minutes": df[c_dur].map(_minutes) if c_dur else 0.0,
        "connection": df[c_conn] if c_conn else "",
    })
    # people who joined without e-mail (phone dial-in): keep by display name
    d.loc[d.email == "", "email"] = "noemail:" + d["display_name"].fillna("").map(norm_text)
    d["role_rank"] = d["role"].map(ROLE_RANK).fillna(1)

    g = d.sort_values("join").groupby("email", as_index=False).agg(
        display_name=("display_name", "first"),
        first_name=("first_name", "first"),
        last_name=("last_name", "first"),
        role_rank=("role_rank", "max"),
        join=("join", "min"),
        leave=("leave", "max"),
        minutes=("minutes", "sum"),
        sessions=("join", "size"),
        connection=("connection", "first"),
    )
    inv = {v: k for k, v in ROLE_RANK.items() if k != "presenter"}
    g["role"] = g["role_rank"].map(inv)
    # cap duplicate-device overlap: minutes cannot exceed join->leave span
    span = (g["leave"] - g["join"]).dt.total_seconds() / 60
    g["minutes"] = g[["minutes"]].join(span.rename("span")).min(axis=1).round(0)
    return g.drop(columns="role_rank"), meta, d


# ----------------------------------------------------------- registration

def read_registration(path: Path) -> pd.DataFrame:
    """One row per unique e-mail, latest submission wins."""
    df = read_table(path)
    c_email = _email_col(df)
    c_country = _col(df, "pais", "country")
    c_gender = _col(df, "genero", "gender")
    c_org = _col(df, "organizacion", "organization", "institucion", "institution")
    c_title = _col(df, "cargo", "job title", "puesto", "position")
    c_time = _col(df, "hora de registro", "registration time", "completion time", "start time")
    c_full = _col(df, "nombre y apellido", "full name")
    c_first = _col(df, "nombre", "first name", exclude=("seminario", "webinar", "apellido", "full"))
    c_last = _col(df, "apellido", "last name")
    c_att = _col(df, "asistido", "attended")

    if c_full:
        name = df[c_full]
    else:
        first = df[c_first].fillna("").astype(str).str.strip() if c_first else pd.Series("", index=df.index)
        last = df[c_last].fillna("").astype(str).str.strip() if c_last else pd.Series("", index=df.index)
        # Webex's first "Nombre" column often already holds the full name
        name = pd.Series([f if (l and f.lower().endswith(l.lower())) else f"{f} {l}".strip()
                          for f, l in zip(first, last)], index=df.index)
    d = pd.DataFrame({
        "email": df[c_email].map(norm_email),
        "name": pd.Series(name).astype(str).str.strip(),
        "country_raw": df[c_country] if c_country else None,
        "gender_raw": df[c_gender] if c_gender else None,
        "organization": df[c_org] if c_org else None,
        "job_title": df[c_title] if c_title else None,
        "registered_at": pd.to_datetime(df[c_time], errors="coerce") if c_time else pd.NaT,
        "attended_flag": df[c_att] if c_att else None,
    })
    d = d[d.email != ""].sort_values("registered_at")
    d["submissions"] = d.groupby("email")["email"].transform("size")
    d = d.drop_duplicates("email", keep="last").reset_index(drop=True)
    cols = " ".join(norm_text(c) for c in df.columns)
    d.attrs["source"] = "webex" if ("estado de registro" in cols or "registration status" in cols) else "form"
    return d


# -------------------------------------------------------- transcript / chat

TS_RE = re.compile(r"^(\d{1,2}(?::\d{2}){1,2}) : (.*?) : (.*)$")
CHAT_RE = re.compile(r"^(-+>\s*)?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) : (.*?) : (.*)$")


def _secs(ts: str) -> int:
    parts = [int(p) for p in ts.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


@dataclass
class Utterance:
    t: int
    speaker: str
    text: str


def read_transcript(path: Path) -> list[Utterance]:
    out = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        m = TS_RE.match(line.strip())
        if m:
            out.append(Utterance(_secs(m.group(1)), m.group(2).strip(), m.group(3).strip()))
        elif out and line.strip():
            out[-1].text += " " + line.strip()
    return out


def strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()


@dataclass
class ChatMsg:
    time: pd.Timestamp
    name: str
    text: str
    is_reply: bool = False
    links: list = field(default_factory=list)


def read_chat(path: Path) -> list[ChatMsg]:
    out = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        m = CHAT_RE.match(line.strip())
        if m:
            raw = m.group(4)
            links = sorted(set(re.findall(r'href="(https?://[^"]+)"', raw)))
            text = strip_html(raw)
            links += [u for u in re.findall(r"https?://\S+", text) if u not in links]
            out.append(ChatMsg(pd.Timestamp(m.group(2)), m.group(3).strip(), text, bool(m.group(1)), links))
        elif out and line.strip():
            out[-1].text += "\n" + strip_html(line)
    return out


def is_question(text: str) -> bool:
    t = text.strip()
    return "?" in t or bool(re.match(r"(?i)^(pregunta|consulta|question)\b", t))


# ----------------------------------------------------------------- slides

def read_slides(path: Path) -> list[str]:
    if path.suffix.lower() == ".pptx":
        from pptx import Presentation
        prs = Presentation(str(path))
        slides = []
        for s in prs.slides:
            texts = []
            for shp in s.shapes:
                if shp.has_text_frame:
                    t = shp.text_frame.text.strip()
                    if t:
                        texts.append(t)
                if getattr(shp, "has_table", False) and shp.has_table:
                    for row in shp.table.rows:
                        texts.append(" | ".join(c.text.strip() for c in row.cells))
            slides.append("\n".join(texts))
        return slides
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            return []
        return [(p.extract_text() or "").strip() for p in PdfReader(str(path)).pages]
    return []


def read_ai_summary(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")
