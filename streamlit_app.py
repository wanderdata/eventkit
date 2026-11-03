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


PAGES = ["Subir evento", "Toda la serie", "Por evento"]

CSS = """
<style>
/* ---- look & feel */
:root{--ek-ink:#0b0b0b;--ek-ink2:#52514e;--ek-muted:#6f6d68;--ek-line:#e1e0d9;--ek-surface:#fcfcfb;--ek-accent:#2a78d6}
html,body,[class*="st-"],button,input,textarea,select{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif!important}
code,pre,kbd{font-family:ui-monospace,SFMono-Regular,Consolas,monospace!important}
header[data-testid="stHeader"]{background:transparent;height:0}
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
    _check_salt(stg)
    if not (paths.public_dir() / "index.html").exists():
        build_site()
    return stg


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


def dashboard_html(tab="series") -> str:
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

cfg = SUM.series_config()

# ---------------------------------------------------------------- header + navigation
def go_to(name):
    st.session_state["page"] = name
    st.session_state["nav"] = name


st.session_state.setdefault("page", PAGES[0])
if not st.session_state.get("nav"):          # first visit, or the user clicked the active option off
    st.session_state["nav"] = st.session_state["page"]
h1, h2 = st.columns([5, 4], vertical_alignment="bottom")
with h1:
    st.markdown(f'<div class="ek-brand"><span class="k">{cfg.get("dashboard_title_es", "Webinars")}</span>'
                f'<span class="t">{cfg.get("series_name_es", "")}</span></div>', unsafe_allow_html=True)
with h2:
    n1, n2 = st.columns([5, 1], vertical_alignment="bottom")
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
            "- **Transcripción** (.txt) · **Chat** (.txt) · **Resumen de la reunión** (.txt)\n"
            "- **Presentación** del ponente (.pptx o .pdf)")

    files = st.file_uploader("Archivos del evento", accept_multiple_files=True,
                             type=["csv", "xlsx", "xls", "txt", "pptx", "pdf", "zip", "yml", "yaml", "docx"],
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
    event_id = meta.planned_start.strftime("%Y-%m-%d")
    exists = (paths.events_dir() / event_id).exists()
    st.info(f"**Evento detectado:** {event_id} — {meta.webinar_name}")
    if exists:
        st.warning("Ya existe un evento con esta fecha. Se actualizarán sus datos; la nota existente se conserva "
                   "salvo que marques «Reescribir la nota».")

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

    overrides = {k: v for k, v in dict(title_es=title_es, title_en=title_en, speaker=speaker,
                                       speaker_affiliation=affiliation).items() if v.strip()}
    if overrides:
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
    st.success("Listo. Revisa el tablero del evento y la revisión automática de la nota.")
    st.button("Ver el tablero del evento →", type="primary",
              on_click=go_to, args=("Por evento",))


# ================================================================ series
def page_series():
    st.title("Toda la serie")
    if not S.load_events():
        st.info("Todavía no hay eventos. Usa «Subir evento».")
        return
    show_dashboard("series", 1250)


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
                cli.process([edir / "raw"], move_raw=False)
            except Exception:
                pass
        save(stg, f"Evento {eid}: nota ({lang}) agregada")
        st.success("Nota guardada.")
        st.rerun()


def page_event():
    evs = events()
    if not evs:
        st.info("Todavía no hay eventos. Usa «Subir evento».")
        return
    ids = [e["id"] for e in evs]
    default = ids.index(st.session_state["event"]) if st.session_state.get("event") in ids else 0
    eid = st.selectbox("Evento", ids, index=default, format_func=lambda i: event_label(next(e for e in evs if e["id"] == i)))
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


{"Subir evento": page_upload, "Toda la serie": page_series, "Por evento": page_event}[page]()
