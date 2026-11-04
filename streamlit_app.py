"""Plataforma de webinars: subir archivos de un evento, tablero de la serie y tablero por evento.

Run locally:   streamlit run streamlit_app.py
Deploy:        Streamlit Community Cloud → this repo → streamlit_app.py (see DEPLOY.md)
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Webinars · eventos", page_icon="📊", layout="wide", initial_sidebar_state="collapsed")

# ---------------------------------------------------------------- settings
for key in ("ANTHROPIC_API_KEY", "EVENTKIT_SALT", "EVENTKIT_DATA_REPO", "EVENTKIT_DATA_TOKEN",
            "EVENTKIT_DATA_BRANCH", "EVENTKIT_MODEL", "EVENTKIT_HOME", "APP_PASSWORD"):
    try:
        if key in st.secrets and not os.environ.get(key):
            os.environ[key] = str(st.secrets[key])
    except Exception:  # no secrets file locally
        pass


PAGES = ["Subir evento", "Todos los eventos", "Por serie", "Por evento", "Administrar"]

CSS = """
<style>
/* ---- look & feel */
:root{--ek-ink:#0b0b0b;--ek-ink2:#52514e;--ek-muted:#6f6d68;--ek-line:#e1e0d9;--ek-surface:#fcfcfb;--ek-accent:#2a78d6}
html,body,[class*="st-"],button,input,textarea,select{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif!important}
code,pre,kbd{font-family:ui-monospace,SFMono-Regular,Consolas,monospace!important}
header[data-testid="stHeader"]{display:none!important}
[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stStatusWidget"]{display:none!important}
section[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"],[data-testid="stExpandSidebarButton"]{display:none!important}
.block-container{padding-top:1.4rem!important;max-width:1240px}
h1{font-size:1.65rem!important;font-weight:650!important;letter-spacing:-.01em}
h2,h3{font-weight:620!important;letter-spacing:-.005em}
.ek-brand{display:flex;flex-direction:column;gap:2px;margin:0 0 2px}
.ek-brand .k{font-size:12px;font-weight:650;letter-spacing:.08em;text-transform:uppercase;color:var(--ek-muted)}
.ek-brand .t{font-size:20px;font-weight:650;color:var(--ek-ink);line-height:1.25}
.ek-meta{font-size:12.5px;color:var(--ek-muted);margin-top:-4px}
.ek-steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:6px 0 4px}
.ek-step{border:1px solid var(--ek-line);background:var(--ek-surface);border-radius:12px;padding:10px 12px;font-size:13.5px}
.ek-step b{display:block;font-size:12px;color:var(--ek-muted);font-weight:650;letter-spacing:.05em;text-transform:uppercase}
.ek-check{display:grid;gap:6px;margin:6px 0 10px}
.ek-check .row{display:grid;grid-template-columns:26px 230px 1fr;gap:8px;align-items:center;border:1px solid var(--ek-line);
  background:var(--ek-surface);border-radius:10px;padding:8px 12px;font-size:14px}
.ek-check .ok{color:#006300;font-weight:700}.ek-check .no{color:#b42318;font-weight:700}.ek-check .opt{color:var(--ek-muted)}
.ek-check .f{color:var(--ek-ink2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}
@media(max-width:640px){.ek-check .row{grid-template-columns:22px 1fr}.ek-check .f{grid-column:2}}
[data-testid="stFileUploaderDropzone"]{padding:2.2rem 1rem!important;border:2px dashed #b7d3f6!important;background:#f3f8fe!important;border-radius:14px!important}
[data-testid="stExpander"] details{border-radius:12px!important}
div[data-testid="stSegmentedControl"] button{font-size:14.5px}

/* ---- icon font fallback: some networks block Streamlit's icon font, which then
   shows its internal names (e.g. "keyboard_arrow_down"). Hide those names and draw
   plain symbols instead, so the app looks the same everywhere. */
[data-testid="stIconMaterial"]{font-size:0!important;line-height:1!important;width:auto!important;min-width:0!important;overflow:visible!important}
[data-testid="stIconMaterial"]::after{font-size:15px;font-family:system-ui,sans-serif;line-height:1;color:currentColor}
[data-testid="stExpander"] summary [data-testid="stIconMaterial"]::after{content:"\\25B8"}
[data-testid="stExpander"] details[open] summary [data-testid="stIconMaterial"]::after{content:"\\25BE"}
[data-testid="stFileUploaderDeleteBtn"] [data-testid="stIconMaterial"]::after{content:"\\2715";font-size:13px}
[data-testid="stFileUploaderFile"] [data-testid="stIconMaterial"]::after{content:"\\1F4C4";font-size:18px}
[data-testid="stFileUploaderDropzone"] [data-testid="stIconMaterial"]::after{content:"\\2B06";font-size:22px}
[data-testid="stAlert"] [data-testid="stIconMaterial"]::after{content:""}
</style>
"""
st.html(CSS)


def _password_gate():
    """If APP_PASSWORD is set, ask for it once per browser session before showing anything."""
    import hmac
    pw = os.environ.get("APP_PASSWORD")
    if not pw or st.session_state.get("auth_ok"):
        return
    st.markdown('<div class="ek-brand"><span class="k">Acceso</span><span class="t">Plataforma de webinars</span></div>',
                unsafe_allow_html=True)
    with st.form("login"):
        given = st.text_input("Contraseña", type="password")
        ok = st.form_submit_button("Entrar", type="primary")
    if ok:
        if hmac.compare_digest(given.encode(), pw.encode()):
            st.session_state["auth_ok"] = True
            st.rerun()
        st.error("Contraseña incorrecta.")
    st.stop()


_password_gate()

from eventkit import cli, paths, store as S, summarize as SUM  # noqa: E402  (after env is set)
from eventkit import catalog as CAT  # noqa: E402
from eventkit import normalize as N  # noqa: E402
from eventkit import parsers as P  # noqa: E402
from eventkit.docx_out import md_to_docx  # noqa: E402
from eventkit.site import build_site, embed_html  # noqa: E402
from eventkit.storage import get_store  # noqa: E402

KIND_LABEL = {
    "participants": "Informe de participantes",
    "registration": "Informe de inscripción",
    "transcript": "Transcripción",
    "chat": "Chat",
    "ai_summary": "Resumen automático de Webex",
    "slides": "Presentación",
    "event_yml": "Datos manuales (event.yml)",
    "docx": "Documento Word (no se usa)",
    "unknown": "No reconocido (se ignora)",
}
EXPECTED = ["participants", "registration", "transcript", "chat", "slides", "ai_summary"]
REQUIRED = {"participants"}


# ---------------------------------------------------------------- storage
@st.cache_resource
def _store():
    return get_store()


def open_store(force=False):
    """Sync the data store once per session (or on demand) and point eventkit at it."""
    stg = _store()
    if force or not st.session_state.get("synced"):
        stg.sync()
        st.session_state["synced"] = True
        N._org_cache.cache_clear()
        N.sector_rules.cache_clear()
        N._countries.cache_clear()
    paths.set_home(stg.root)
    if CAT.ensure():   # first run with series: file existing events under the first series
        save(stg, "Clasificar eventos en series y tipos")
    _check_salt(stg)
    _check_stats_version(stg)
    if not (paths.public_dir() / "index.html").exists():
        build_site()
    return stg


def _check_stats_version(stg):
    """Recompute events processed by older code so new indicators appear for them too."""
    from eventkit.stats import STATS_VERSION
    old = [e["id"] for e in S.load_events() if e.get("stats_version", 1) < STATS_VERSION]
    if old:
        with st.spinner(f"Actualizando indicadores de {len(old)} eventos (solo esta vez)…"):
            cli.rebuild()
        save(stg, "Recalcular indicadores con la versión actual")


def _check_salt(stg):
    """Anonymous IDs depend on EVENTKIT_SALT. If the salt differs from the one the data was
    built with (e.g. data prepared elsewhere), recompute every event so returning attendees match."""
    import hashlib
    salt = os.environ.get("EVENTKIT_SALT")
    if not salt:
        return
    fp = hashlib.sha256(("eventkit-fingerprint:" + salt).encode()).hexdigest()[:16]
    f = paths.data_dir() / "salt_fingerprint.txt"
    if f.exists() and f.read_text().strip() == fp:
        return
    if S.load_events():
        with st.spinner("Preparando los datos con la clave de esta instalación (solo la primera vez)…"):
            cli.rebuild()
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    f.write_text(fp)
    save(stg, "Recalcular identificadores anónimos con la clave de esta instalación")


def save(stg, message):
    build_site()
    try:
        pushed = stg.save(message)
    except Exception as e:  # keep the app usable; tell the user
        st.error(f"No se pudo guardar en el repositorio de datos: {e}")
        return False
    return pushed


def _site_stamp() -> str:
    """Changes whenever the dashboard code or any of the data it shows changes."""
    import hashlib
    import eventkit
    parts = [eventkit.__file__]
    pkg = Path(eventkit.__file__).parent
    for f in [paths.config_file("dashboard.html"), pkg / "site.py", pkg / "stats.py",
              paths.data_dir() / "events.json", paths.data_dir() / "attendance.csv",
              paths.series_config_dir() / "catalog.yml"] + sorted(paths.events_dir().glob("*/meta.yml")) \
            + sorted(paths.events_dir().glob("*/summary_*.md")):
        if f.exists():
            st_ = f.stat()
            parts.append(f"{f}:{st_.st_mtime_ns}:{st_.st_size}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


def ensure_fresh_site():
    """Rebuild public/index.html if it was built by older code or from older data
    (hosted apps keep their disk across code updates)."""
    stamp_f = paths.public_dir() / ".build_stamp"
    stamp = _site_stamp()
    if not (paths.public_dir() / "index.html").exists() or not stamp_f.exists() or stamp_f.read_text() != stamp:
        build_site()
        stamp_f.write_text(_site_stamp())


def dashboard_html(tab="global") -> str:
    ensure_fresh_site()
    p = paths.public_dir() / "index.html"
    return embed_html(p.read_text(encoding="utf-8"), tab) if p.exists() else "<p>Sin datos aún.</p>"


def events():
    return list(reversed(S.load_events()))  # newest first


def show_dashboard(tab: str, fallback_height: int):
    """Embed the dashboard (our own generated HTML; user data inside is escaped by the page)."""
    html = dashboard_html(tab)
    if hasattr(st, "iframe"):
        # a keyed container per view, so Streamlit doesn't reuse the frame (and its old height)
        with st.container(key=f"dash_{re.sub(r'[^A-Za-z0-9_]', '_', tab)}"):
            st.iframe(html, height="content")
    else:  # older Streamlit
        import streamlit.components.v1 as components
        components.html(html, height=fallback_height, scrolling=True)


def event_label(e):
    return f"{e.get('date', e['id'])} · {e.get('title_es') or e.get('webinar_name', '')}"


def events_by_series() -> dict:
    """{series_id: [events newest first]} using the current classification."""
    out = {}
    for e in events():
        sid = CAT.event_meta(e["id"]).get("series") or e.get("series")
        out.setdefault(sid, []).append(e)
    return out


def series_label(sid):
    s = CAT.get_series(sid)
    return s.get("name_es") or sid


def pick_series(key, with_counts=True, only_with_events=True):
    groups = events_by_series()
    opts = [s["id"] for s in CAT.series_list() if (not only_with_events or s["id"] in groups)]
    if not opts:
        return None
    cur = st.session_state.get("series_sel")
    idx = opts.index(cur) if cur in opts else 0
    sid = st.selectbox("Serie", opts, index=idx, key=key,
                       format_func=lambda i: series_label(i) + (f"  ({len(groups.get(i, []))})" if with_counts else ""))
    st.session_state["series_sel"] = sid
    return sid


def strip_comments(md: str) -> str:
    """Hide the auto-generated markers in the article."""
    return re.sub(r"<!--.*?-->\n?", "", md, flags=re.S)


# ---------------------------------------------------------------- guards
try:
    stg = open_store()
except Exception as e:
    st.error(f"No se pudieron cargar los datos: {e}")
    st.stop()
if stg.kind == "git" and not os.environ.get("EVENTKIT_SALT"):
    st.error("Falta el secreto EVENTKIT_SALT. Agrégalo en la configuración de la app (Secrets) antes de usarla.")
    st.stop()

cat = CAT.load()

# ---------------------------------------------------------------- header + navigation
def go_to(name):
    st.session_state["page"] = name
    st.session_state["nav"] = name


st.session_state.setdefault("page", PAGES[0])
if not st.session_state.get("nav"):          # first visit, or the user clicked the active option off
    st.session_state["nav"] = st.session_state["page"]
h1, h2 = st.columns([3, 5], vertical_alignment="bottom")
with h1:
    n_ev = len(S.load_events())
    n_se = len(events_by_series())
    st.markdown(f'<div class="ek-brand"><span class="k">CEPAL · {n_ev} {"evento" if n_ev == 1 else "eventos"} en '
                f'{n_se} {"serie" if n_se == 1 else "series"}</span>'
                f'<span class="t">{cat["platform_title_es"]}</span></div>', unsafe_allow_html=True)
with h2:
    n1, n2 = st.columns([8, 1], vertical_alignment="bottom")
    choice = n1.segmented_control("Sección", PAGES, key="nav", label_visibility="collapsed")
    if choice and choice != st.session_state["page"]:
        st.session_state["page"] = choice
    if n2.button("↻", help="Actualizar: volver a leer los datos guardados", use_container_width=True):
        open_store(force=True)
        build_site()
        st.rerun()
page = st.session_state["page"]
mode = "notas automáticas (Claude)" if os.environ.get("ANTHROPIC_API_KEY") else "notas manuales"
st.markdown(f'<div class="ek-meta">Datos: {stg.describe()} · {mode}</div>', unsafe_allow_html=True)
st.divider()


# ================================================================ upload
def page_upload():
    st.title("Subir un evento")
    st.markdown(
        '<div class="ek-steps">'
        '<div class="ek-step"><b>1 · Descarga</b>Los informes de Webex y la presentación</div>'
        '<div class="ek-step"><b>2 · Arrastra</b>Todos los archivos juntos (o un .zip), aquí abajo</div>'
        '<div class="ek-step"><b>3 · Procesa</b>Revisa la lista y pulsa «Procesar evento»</div>'
        '</div>', unsafe_allow_html=True)
    with st.expander("¿Qué archivos descargar de Webex?"):
        st.markdown(
            "- **Informe de participantes** (.csv/.xlsx) — *obligatorio*\n"
            "- **Informe de inscripción** de Webex o exportación de Microsoft Forms (.csv/.xlsx)\n"
            "- **Transcripción** (.txt o .vtt) · **Chat** (.txt) · **Resumen de la reunión** (.txt)\n"
            "- **Presentación** del ponente (.pptx o .pdf)")

    files = st.file_uploader("Archivos del evento", accept_multiple_files=True,
                             type=["csv", "xlsx", "xls", "txt", "vtt", "pptx", "pdf", "zip", "yml", "yaml", "docx"],
                             key=f"up_{st.session_state.get('up_n', 0)}")
    if not files:
        return

    tmp = Path(tempfile.mkdtemp(prefix="evento_"))
    for f in files:
        (tmp / f.name).write_bytes(f.getbuffer())
    found = cli.classify_files(cli._expand([tmp]))

    import html as _h
    rows = []
    for k in EXPECTED + ["event_yml", "docx", "unknown"]:
        names = ", ".join(p.name for p in found.get(k, []))
        if k not in EXPECTED and not names:
            continue
        if names:
            mark, cls = ("✓", "ok") if k in EXPECTED or k == "event_yml" else ("·", "opt")
        else:
            mark, cls = ("✗", "no") if k in REQUIRED else ("–", "opt")
        detail = names or ("falta (obligatorio)" if k in REQUIRED else "no incluido")
        rows.append(f'<div class="row"><span class="{cls}">{mark}</span><span>{_h.escape(KIND_LABEL[k])}</span>'
                    f'<span class="f" title="{_h.escape(detail)}">{_h.escape(detail)}</span></div>')
    st.markdown('<div class="ek-check">' + "".join(rows) + "</div>", unsafe_allow_html=True)

    if not found.get("participants"):
        st.error("Falta el **informe de participantes** de Webex: sin él no se puede crear el evento.")
        return

    _, meta, _ = P.read_participants(found["participants"][0])
    date_id = meta.planned_start.strftime("%Y-%m-%d")
    st.info(f"**Evento detectado:** {date_id} — {meta.webinar_name}")

    # ---- classification
    st.markdown("**¿A qué serie y tipo pertenece?**")
    NEW = "__nueva__"
    groups = events_by_series()
    sids = [s["id"] for s in CAT.series_list()]
    last = st.session_state.get("last_series") or next(iter(groups), sids[0])
    c1, c2 = st.columns(2)
    sid = c1.selectbox("Serie", sids + [NEW], index=(sids + [NEW]).index(last) if last in sids else 0,
                       format_func=lambda i: "➕ Nueva serie…" if i == NEW else series_label(i), key="up_series")
    types = CAT.load()["types"]
    etype = c2.selectbox("Tipo de evento", types + [NEW], index=0,
                         format_func=lambda t: "➕ Otro tipo…" if t == NEW else t, key="up_type")
    new_series = {}
    if sid == NEW:
        with st.container(border=True):
            a1, a2 = st.columns(2)
            new_series["name_es"] = a1.text_input("Nombre de la serie (español)", key="ns_es")
            new_series["name_en"] = a2.text_input("Nombre de la serie (inglés)", key="ns_en")
            new_series["organizers_es"] = a1.text_input("Organizadores (español)", value="CEPAL", key="ns_org_es")
            new_series["organizers_en"] = a2.text_input("Organizadores (inglés)", value="ECLAC", key="ns_org_en")
    new_type = st.text_input("Nombre del nuevo tipo", key="nt") if etype == NEW else ""

    if sid != NEW:
        same = CAT.event_meta(date_id).get("series")
        if (paths.events_dir() / date_id).exists():
            if same == sid:
                st.warning("Este evento ya existe en esta serie: se actualizarán sus datos y la nota existente se "
                           "conserva salvo que marques «Reescribir la nota».")
            else:
                st.caption(f"Ya hay un evento del {date_id} en otra serie; este se guardará por separado.")

    with st.form("procesar"):
        st.markdown("**Datos opcionales** (si los dejas vacíos se detectan de los archivos)")
        c1, c2 = st.columns(2)
        title_es = c1.text_input("Título de la sesión (español)")
        title_en = c2.text_input("Título de la sesión (inglés)")
        speaker = c1.text_input("Ponente")
        affiliation = c2.text_input("Cargo e institución del ponente")
        force = st.checkbox("Reescribir la nota aunque ya exista", value=False)
        go = st.form_submit_button("Procesar evento", type="primary", use_container_width=True)
    if not go:
        return
    if sid == NEW and not new_series.get("name_es", "").strip():
        st.error("Escribe el nombre de la nueva serie.")
        return
    if etype == NEW and not new_type.strip():
        st.error("Escribe el nombre del nuevo tipo de evento.")
        return
    if sid == NEW:
        sid = CAT.add_series(**{k: v.strip() for k, v in new_series.items()})
    if etype == NEW:
        etype = new_type.strip()
        CAT.add_type(etype)
    st.session_state["last_series"] = sid

    overrides = {k: v for k, v in dict(title_es=title_es, title_en=title_en, speaker=speaker,
                                       speaker_affiliation=affiliation).items() if v.strip()}
    overrides.update(series=sid, type=etype)
    import yaml
    (tmp / "event.yml").write_text(yaml.safe_dump(overrides, allow_unicode=True), encoding="utf-8")

    bar = st.progress(0, text="Sincronizando datos…")
    open_store(force=True)
    bar.progress(25, text="Calculando estadísticas" + (" y redactando la nota (1–3 minutos)…"
                                                        if os.environ.get("ANTHROPIC_API_KEY") else "…"))
    try:
        eid = cli.process([tmp], force_summary=force, move_raw=False)
    except SystemExit as e:
        bar.empty()
        st.error(str(e))
        return
    except Exception as e:
        bar.empty()
        st.error(f"No se pudo procesar el evento: {e}")
        return
    bar.progress(80, text="Guardando archivos y actualizando el tablero…")
    save(stg, f"Evento {eid}: archivos y resultados")
    bar.progress(100, text=f"Evento {eid} procesado")
    shutil.rmtree(tmp, ignore_errors=True)
    st.session_state["up_n"] = st.session_state.get("up_n", 0) + 1
    st.session_state["event"] = eid
    st.session_state["series_sel"] = sid
    st.success("Listo. Revisa el tablero del evento y la revisión automática de la nota.")
    st.button("Ver el tablero del evento →", type="primary",
              on_click=go_to, args=("Por evento",))


# ================================================================ series
@st.cache_data(show_spinner="Preparando la lista de correos…", max_entries=8)
def _mailing(home: str, stamp: float, event_ids: tuple | None, only_attended: bool):
    """Cached per data version (stamp) so the page stays fast."""
    from eventkit import export
    df = export.mailing_list(list(event_ids) if event_ids else None, only_attended=only_attended)
    return len(df), export.to_excel(df), export.to_text(df)


def _data_stamp() -> float:
    f = paths.data_dir() / "events.json"
    return f.stat().st_mtime if f.exists() else 0.0


def mailing_buttons(scope: str, event_ids: tuple | None = None):
    """Export unique e-mails (Excel with profile, or plain text one per line)."""
    c0, c1, c2 = st.columns([2.2, 1.4, 1.4], vertical_alignment="bottom")
    who = c0.segmented_control("Incluir", ["Inscritos y participantes", "Solo quienes asistieron"],
                               key=f"mail_who_{scope}", default="Inscritos y participantes")
    only = who == "Solo quienes asistieron"
    n, xlsx, txt = _mailing(str(paths.home()), _data_stamp(), event_ids, only)
    tag = "asistentes" if only else "todos"
    c1.download_button(f"Lista de correos · Excel ({n})", xlsx, file_name=f"correos_{scope}_{tag}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True, key=f"mx_{scope}_{tag}",
                       help="Correos únicos con nombre, país, organización y sesiones inscritas/asistidas")
    c2.download_button("Solo correos · texto", txt, file_name=f"correos_{scope}_{tag}.txt", mime="text/plain",
                       use_container_width=True, key=f"mt_{scope}_{tag}",
                       help="Un correo por línea, para pegar en Outlook (CCO) o en una herramienta de envíos")
    st.caption("Contiene datos personales: úsala solo para comunicaciones de la CEPAL y no la compartas fuera del equipo.")


@st.cache_data(show_spinner="Preparando la ficha…", max_entries=16)
def _event_pdf(home: str, stamp: float, eid: str) -> bytes:
    from eventkit import reports
    return reports.event_pdf(eid)


def pdf_box(eid: str):
    """Build the one-page PDF only on request, and never let a failure break the page."""
    key = f"pdf_{eid}"
    if st.session_state.get(key) is None:
        if st.button("Preparar ficha del evento (PDF, 1 página)", key=f"{key}_go",
                     help="Resumen de una página: datos clave, indicadores, la sesión minuto a minuto, países, sectores y temas"):
            try:
                st.session_state[key] = _event_pdf(str(paths.home()), _data_stamp(), eid)
                st.rerun()
            except Exception as e:
                st.warning(f"No se pudo generar el PDF ({type(e).__name__}: {e}).")
    else:
        st.download_button("Descargar ficha del evento (PDF)", st.session_state[key], file_name=f"ficha_{eid}.pdf",
                           mime="application/pdf", type="primary", key=f"{key}_dl")


def period_report_box():
    import datetime as _dt
    evs = S.load_events()
    d0 = _dt.date.fromisoformat(min(e["date"] for e in evs))
    d1 = _dt.date.fromisoformat(max(e["date"] for e in evs))
    with st.container(border=True):
        st.markdown("**Informe del período** (PDF)")
        c1, c2, c3 = st.columns([1.2, 2.4, 1.2], vertical_alignment="bottom")
        rng = c1.date_input("Desde – hasta", (d0, d1), format="DD/MM/YYYY", key="rep_rng")
        sids = [x["id"] for x in CAT.series_list() if x["id"] in events_by_series()]
        chosen = c2.multiselect("Series (vacío = todas)", sids, format_func=series_label, key="rep_series")
        if c3.button("Preparar informe", use_container_width=True, key="rep_go"):
            a, b = (rng if isinstance(rng, (tuple, list)) and len(rng) == 2 else (d0, d1))
            try:
                from eventkit import reports
                st.session_state["rep_pdf"] = (reports.period_pdf(a.isoformat(), b.isoformat(), chosen or None),
                                               f"informe_{a.isoformat()}_{b.isoformat()}.pdf")
            except Exception as e:
                st.warning(f"No se pudo generar el informe ({type(e).__name__}: {e}).")
        if st.session_state.get("rep_pdf"):
            data, name = st.session_state["rep_pdf"]
            st.download_button("Descargar informe", data, file_name=name, mime="application/pdf", type="primary", key="rep_dl")


def page_global():
    st.title("Todos los eventos")
    if not S.load_events():
        st.info("Todavía no hay eventos. Usa «Subir evento».")
        return
    period_report_box()
    with st.container(border=True):
        st.markdown("**Exportar correos de todos los eventos** (sin duplicados)")
        mailing_buttons("todos")
    show_dashboard("global", 1600)


def page_series():
    st.title("Por serie")
    sid = pick_series("sel_series_page")
    if not sid:
        st.info("Todavía no hay eventos. Usa «Subir evento».")
        return
    ids = tuple(e["id"] for e in events_by_series().get(sid, []))
    with st.container(border=True):
        st.markdown("**Exportar correos de esta serie** (sin duplicados)")
        mailing_buttons(f"serie_{sid}", ids)
    show_dashboard(f"series:{sid}", 1250)


# ================================================================ event
def manual_article(eid, edir, lang, md, dx):
    """No article yet: offer the prepared prompt, the participation paragraph, and a box to paste the article."""
    st.info("Aún no hay nota en este idioma. Redáctala por tu cuenta y pégala aquí: se guardará con el evento "
            "y se generará el Word.")
    ev = next((e for e in S.load_events() if e["id"] == eid), None)
    c1, c2 = st.columns(2)
    prompt = edir / "prompt_es.md"
    if prompt.exists():
        c1.download_button("Descargar el texto preparado para Claude", prompt.read_bytes(),
                           file_name=f"{eid}_prompt.md", use_container_width=True, key=f"pr_{lang}",
                           help="Incluye transcripción, chat, diapositivas e instrucciones de estilo. "
                                "Pégalo en Claude para obtener un borrador.")
    if ev:
        with st.expander("Párrafo de cifras de participación (para copiar en la nota)"):
            st.code(SUM.stats_paragraph(ev, lang), language=None, wrap_lines=True)
    title = "Pega la nota final" if lang == "es" else "Paste the final article"
    text = st.text_area(f"{title} (la primera línea con `# ` se usa como título)", height=380,
                        key=f"new_{eid}_{lang}", placeholder="# Título de la nota\n\n*Bajada…*\n\nPrimer párrafo…")
    if st.button("Guardar nota", type="primary", key=f"savenew_{lang}", disabled=not text.strip()):
        md.write_text(text.strip() + "\n", encoding="utf-8")
        md_to_docx(md, dx)
        if lang == "es":  # refresh the automatic quote/name check against the transcript
            try:
                cli.process([edir / "raw"], move_raw=False, event_id=eid)
            except Exception:
                pass
        save(stg, f"Evento {eid}: nota ({lang}) agregada")
        st.success("Nota guardada.")
        st.rerun()


def page_event():
    if not events():
        st.info("Todavía no hay eventos. Usa «Subir evento».")
        return
    cur = st.session_state.get("event")
    if cur and CAT.event_meta(cur).get("series"):     # coming from an upload: open its series
        st.session_state.setdefault("series_sel", CAT.event_meta(cur)["series"])
    c1, c2 = st.columns(2)
    with c1:
        sid = pick_series("sel_series_event")
    evs = events_by_series().get(sid, [])
    ids = [e["id"] for e in evs]
    default = ids.index(cur) if cur in ids else 0
    eid = c2.selectbox("Evento", ids, index=default, format_func=lambda i: event_label(next(e for e in evs if e["id"] == i)))
    pdf_box(eid)
    st.session_state["event"] = eid
    edir = paths.events_dir() / eid

    show_dashboard(eid, 2900)

    # ---- article
    st.subheader("Nota informativa")
    tabs = st.tabs(["Español", "English"])
    for tab, lang in zip(tabs, ("es", "en")):
        with tab:
            md = edir / f"summary_{lang}.md"
            dx = edir / f"summary_{lang}.docx"
            if not md.exists():
                manual_article(eid, edir, lang, md, dx)
                continue
            c1, c2 = st.columns([1, 1])
            if dx.exists():
                c1.download_button(f"Descargar Word ({'español' if lang == 'es' else 'inglés'})", dx.read_bytes(),
                                   file_name=f"{eid}_nota_{lang}.docx", use_container_width=True, key=f"dx_{lang}")
            edit = c2.toggle("Editar", key=f"edit_{eid}_{lang}")
            text = md.read_text(encoding="utf-8")
            if edit:
                new = st.text_area("Texto (markdown). No edites el párrafo de cifras: se actualiza solo.",
                                   text, height=520, key=f"ta_{eid}_{lang}")
                if st.button("Guardar cambios", type="primary", key=f"save_{lang}"):
                    md.write_text(new, encoding="utf-8")
                    md_to_docx(md, dx)
                    save(stg, f"Evento {eid}: nota ({lang}) editada")
                    st.success("Guardado. El Word y el tablero se actualizaron.")
                    st.rerun()
            else:
                st.markdown(strip_comments(text))

    rv = edir / "review.md"
    if rv.exists():
        with st.expander("Revisión automática (citas y nombres a verificar)"):
            st.markdown(rv.read_text(encoding="utf-8"))

    # ---- input files
    st.subheader("Archivos del evento")
    raw = sorted((edir / "raw").glob("*")) if (edir / "raw").exists() else []
    if raw:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in raw:
                z.write(f, f.name)
        st.download_button("Descargar todos los archivos (.zip)", buf.getvalue(), file_name=f"{eid}_archivos.zip")
        with st.container(border=True):
            st.markdown("**Exportar correos de este evento** (sin duplicados)")
            mailing_buttons(eid, (eid,))
        for f in raw:
            kind = KIND_LABEL.get(P.detect(f) or "unknown", "")
            c1, c2, c3 = st.columns([5, 3, 2])
            c1.markdown(f'<div style="font-size:13.5px;word-break:break-all;padding-top:6px">{f.name}</div>', unsafe_allow_html=True)
            size = f.stat().st_size
            c2.caption(f"{kind} · " + (f"{size / 1e6:.1f} MB" if size >= 1e6 else f"{max(1, size // 1000)} KB"))
            c3.download_button("Descargar", f.read_bytes(), file_name=f.name, key=f"raw_{f.name}")
    else:
        st.caption("Sin archivos guardados.")

    with st.expander("Eliminar este evento"):
        st.write("Borra el evento, sus archivos y sus cifras de la serie. Queda en el historial del repositorio de datos.")
        if st.checkbox(f"Confirmo que quiero eliminar {eid}", key=f"del_ok_{eid}") and \
                st.button("Eliminar evento", type="secondary", key=f"del_{eid}"):
            S.delete_event(eid)
            save(stg, f"Evento {eid} eliminado")
            st.session_state.pop("event", None)
            st.rerun()


# ================================================================ admin
def page_admin():
    st.title("Administrar")
    t1, t2, t3, t4 = st.tabs(["Series", "Mover un evento", "Tipos de evento", "Plataforma"])
    groups = events_by_series()

    with t1:
        rows = [{"Serie": s["name_es"], "Organizadores": s.get("organizers_es", ""),
                 "Eventos": len(groups.get(s["id"], []))} for s in CAT.series_list()]
        import html as _h
        st.markdown('<div class="ek-check">' + "".join(
            f'<div class="row" style="grid-template-columns:1fr 220px 80px"><span>{_h.escape(r["Serie"])}</span>'
            f'<span class="f">{_h.escape(r["Organizadores"])}</span><span class="f">{r["Eventos"]} {"evento" if r["Eventos"] == 1 else "eventos"}</span></div>'
            for r in rows) + "</div>", unsafe_allow_html=True)

        with st.expander("Crear una serie nueva"):
            with st.form("new_series"):
                a1, a2 = st.columns(2)
                n_es = a1.text_input("Nombre (español)")
                n_en = a2.text_input("Nombre (inglés)")
                o_es = a1.text_input("Organizadores (español)", value="CEPAL")
                o_en = a2.text_input("Organizadores (inglés)", value="ECLAC")
                if st.form_submit_button("Crear serie", type="primary"):
                    if not n_es.strip():
                        st.error("Escribe al menos el nombre en español.")
                    else:
                        CAT.add_series(n_es, n_en, o_es, o_en)
                        save(stg, f"Serie nueva: {n_es.strip()}")
                        st.success("Serie creada.")
                        st.rerun()

        st.markdown("**Editar una serie**")
        sid = st.selectbox("Serie a editar", [x["id"] for x in CAT.series_list()], format_func=series_label, key="adm_s")
        cur = CAT.get_series(sid)
        with st.form(f"edit_{sid}"):
            a1, a2 = st.columns(2)
            n_es = a1.text_input("Nombre (español)", cur.get("name_es", ""))
            n_en = a2.text_input("Nombre (inglés)", cur.get("name_en", ""))
            o_es = a1.text_input("Organizadores (español)", cur.get("organizers_es", ""))
            o_en = a2.text_input("Organizadores (inglés)", cur.get("organizers_en", ""))
            sp = CAT.style_example_path(sid)
            own = sp.name == f"{sid}.md"
            ex = st.text_area("Nota de ejemplo para el estilo de redacción (opcional)",
                              sp.read_text(encoding="utf-8") if (sp.exists() and own) else "", height=200,
                              help="Pega una nota ya publicada de esta serie. Se usa como modelo al redactar las "
                                   "nuevas notas. Si la dejas vacía se usa el ejemplo general.")
            if st.form_submit_button("Guardar cambios", type="primary"):
                CAT.update_series(sid, name_es=n_es.strip() or cur.get("name_es"), name_en=n_en.strip(),
                                  organizers_es=o_es.strip(), organizers_en=o_en.strip())
                if ex.strip():
                    CAT.save_style_example(sid, ex)
                save(stg, f"Serie editada: {n_es.strip()}")
                st.success("Guardado.")
                st.rerun()

    with t2:
        evs = events()
        if not evs:
            st.info("Todavía no hay eventos.")
        else:
            lab = {e["id"]: f"{event_label(e)}  —  {series_label(CAT.event_meta(e['id']).get('series'))}" for e in evs}
            eid = st.selectbox("Evento", list(lab), format_func=lab.get, key="mv_e")
            m = CAT.event_meta(eid)
            sids = [x["id"] for x in CAT.series_list()]
            types = CAT.load()["types"]
            b1, b2 = st.columns(2)
            new_sid = b1.selectbox("Serie", sids, index=sids.index(m.get("series")) if m.get("series") in sids else 0,
                                   format_func=series_label, key=f"mv_s_{eid}")
            ty = m.get("type") if m.get("type") in types else types[0]
            new_ty = b2.selectbox("Tipo", types, index=types.index(ty), key=f"mv_t_{eid}")
            if st.button("Guardar clasificación", type="primary", key="mv_go",
                         disabled=(new_sid == m.get("series") and new_ty == m.get("type"))):
                CAT.set_event_meta(eid, series=new_sid, type=new_ty)
                save(stg, f"Evento {eid}: movido a {new_sid} ({new_ty})")
                st.success("Evento reclasificado. Los tableros ya lo muestran en su nueva serie.")
                st.rerun()

    with t3:
        types = CAT.load()["types"]
        st.write(", ".join(types))
        with st.form("new_type"):
            nt = st.text_input("Agregar un tipo de evento")
            if st.form_submit_button("Agregar") and nt.strip():
                CAT.add_type(nt.strip())
                save(stg, f"Tipo de evento nuevo: {nt.strip()}")
                st.rerun()

    with t4:
        with st.form("platform"):
            c = CAT.load()
            title = st.text_input("Título de la plataforma", c["platform_title_es"])
            if st.form_submit_button("Guardar", type="primary"):
                c["platform_title_es"] = title.strip() or c["platform_title_es"]
                CAT.save(c)
                save(stg, "Título de la plataforma")
                st.rerun()


{"Subir evento": page_upload, "Todos los eventos": page_global, "Por serie": page_series,
 "Por evento": page_event, "Administrar": page_admin}[page]()
