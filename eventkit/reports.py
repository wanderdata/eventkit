"""PDF reports: a one-page summary per event and a period report across events.

Charts are drawn with matplotlib, pages composed with reportlab (pure Python, no browser),
so this runs the same on a laptop, a server or Streamlit Community Cloud.
"""
from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_LEFT  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,  # noqa: E402
                                TableStyle)

from . import catalog as CAT
from . import normalize as N
from . import store

# ---------------------------------------------------------------- style
INK, INK2, MUTED, LINE, SURF = "#1a1a19", "#52514e", "#6f6d68", "#e1e0d9", "#f6f5f1"
S1, S2, S3, S4, S5, S6 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"
SECTOR_COLOR = {"publico": S1, "academia": S2, "privado": S3, "internacional": S4, "sociedad_civil": S5, "otros": S6}
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]

_FONT_OK = False


def _fonts():
    global _FONT_OK
    if _FONT_OK:
        return
    reg = font_manager.findfont("DejaVu Sans")
    bold = font_manager.findfont(font_manager.FontProperties(family="DejaVu Sans", weight="bold"))
    pdfmetrics.registerFont(TTFont("Sans", reg))
    pdfmetrics.registerFont(TTFont("Sans-Bold", bold))
    from reportlab.pdfbase.pdfmetrics import registerFontFamily
    registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans", boldItalic="Sans-Bold")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "axes.edgecolor": LINE, "axes.labelcolor": INK2,
                         "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.color": LINE, "grid.linewidth": .6, "axes.axisbelow": True})
    _FONT_OK = True


def _st(size=9, color=INK, bold=False, lead=None, space=0):
    return ParagraphStyle("x", fontName="Sans-Bold" if bold else "Sans", fontSize=size, textColor=colors.HexColor(color),
                          leading=lead or size * 1.3, spaceAfter=space, alignment=TA_LEFT)


def _fmt(v, d=0):
    if v is None:
        return "–"
    s = f"{v:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(v):
    return "–" if v is None else f"{_fmt(v)}%"


def _date(d: str | None) -> str:
    if not d:
        return ""
    y, m, dd = map(int, d[:10].split("-"))
    return f"{dd} de {MONTHS[m - 1]} de {y}"


def _fig_png(fig, w_mm, h_mm) -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=220, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=w_mm * mm, height=h_mm * mm)


def _kpi_table(items, cols=4, width_mm=180):
    """items: [(value, label)] -> grid of tiles."""
    cells, row = [], []
    for v, lab in items:
        row.append([Paragraph(v, _st(15, INK, True, 17)), Paragraph(lab, _st(7.5, INK2, lead=9.5))])
        if len(row) == cols:
            cells.append(row)
            row = []
    if row:
        cells.append(row + [""] * (cols - len(row)))
    t = Table(cells, colWidths=[width_mm / cols * mm] * cols)
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0, colors.white),
                           ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(SURF)),
                           ("INNERGRID", (0, 0), (-1, -1), 3, colors.white),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def _table(header, rows, widths_mm, align_right_from=2, size=7.5):
    data = [[Paragraph(h, _st(size, INK2, True)) for h in header]] + \
           [[Paragraph(str(c), _st(size, INK)) for c in r] for r in rows]
    t = Table(data, colWidths=[w * mm for w in widths_mm], repeatRows=1)
    style = [("LINEBELOW", (0, 0), (-1, 0), .8, colors.HexColor(INK2)),
             ("LINEBELOW", (0, 1), (-1, -1), .3, colors.HexColor(LINE)),
             ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5), ("LEFTPADDING", (0, 0), (-1, -1), 3)]
    t.setStyle(TableStyle(style))
    return t


def _footer(canvas, doc, text):
    canvas.saveState()
    canvas.setFont("Sans", 6.5)
    canvas.setFillColor(colors.HexColor(MUTED))
    canvas.drawString(15 * mm, 9 * mm, text)
    canvas.drawRightString(195 * mm, 9 * mm, f"{doc.page}")
    canvas.restoreState()


def _load():
    from .site import metrics_bundle
    events = store.load_events()
    for e in events:
        m = CAT.event_meta(e["id"])
        e["series"] = m.get("series") or e.get("series")
        e["type"] = m.get("type") or e.get("type") or "Webinar"
    att = store.load_attendance()
    mb = metrics_bundle(att, events)
    return events, att, mb


# ---------------------------------------------------------------- charts
def _session_chart(e):
    pts, fl, ph = e.get("timeline") or [], e.get("flow") or [], e.get("phases") or []
    if not pts:
        return None
    fig, (a0, a1, a2) = plt.subplots(3, 1, figsize=(7.2, 2.8), sharex=True,
                                     gridspec_kw={"height_ratios": [0.35, 2.2, 0.8], "hspace": 0.12})
    x = list(range(len(pts)))
    idx = lambda hhmm: next((i for i, p in enumerate(pts) if p["t"] >= hhmm), len(pts) - 1)
    for k, p in enumerate(ph):
        a, b = idx(p["start"]), idx(p["end"])
        a0.axvspan(a, b, color="#c9c6bd" if k % 2 else "#dcdad3", lw=0)
        short = {"bienvenida": "Bienvenida", "presentacion": "Presentación", "preguntas": "Preguntas", "cierre": "Cierre"}
        if b - a >= 3:
            a0.text((a + b) / 2, .5, short.get(p["key"], p["label"]), ha="center", va="center", fontsize=6.5, color=INK, weight="bold")
        for ax in (a1, a2):
            ax.axvline(a, color="#b9b7ae", lw=.6, ls=(0, (2, 2)))
    a0.set_ylim(0, 1); a0.axis("off")
    ys = [p["n"] for p in pts]
    a1.fill_between(x, ys, color=S1, alpha=.12, lw=0)
    a1.plot(x, ys, color=S1, lw=1.6)
    pk = max(range(len(ys)), key=ys.__getitem__)
    a1.annotate(f"Máximo: {ys[pk]}", (pk, ys[pk]), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=7, weight="bold")
    a1.set_ylabel("Conectadas", fontsize=7)
    a1.set_ylim(0, max(ys) * 1.18 + 1)
    if fl:
        m = [f["messages"] - f["questions"] for f in fl]
        q = [f["questions"] for f in fl]
        a2.bar(x, q, color=S5, width=.8)
        a2.bar(x, m, bottom=q, color="#b7d3f6", width=.8)
        a2.set_ylabel("Chat", fontsize=7)
        a2.grid(False)
    step = max(1, len(pts) // 9)
    a2.set_xticks(x[::step]); a2.set_xticklabels([p["t"] for p in pts][::step], fontsize=6.5)
    for ax in (a1, a2):
        ax.tick_params(labelsize=6.5, length=0)
    return fig


def _hbars(labels, values, color=S1, fmt_pct=True, figsize=(3.4, 2.2)):
    fig, ax = plt.subplots(figsize=figsize)
    y = list(range(len(labels)))[::-1]
    ax.barh(y, values, color=color, height=.62)
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=7)
    for yy, v in zip(y, values):
        ax.text(v, yy, f" {_fmt(v)}{'%' if fmt_pct else ''}", va="center", fontsize=6.5, color=INK)
    ax.set_xticks([]); ax.grid(False); ax.spines["bottom"].set_visible(False); ax.spines["left"].set_visible(False)
    ax.tick_params(length=0)
    ax.set_xlim(0, max(values or [1]) * 1.25)
    return fig


def _stack100(rows, keys, colors_, labels, figsize=(3.4, 1.1)):
    fig, ax = plt.subplots(figsize=figsize)
    for i, r in enumerate(rows):
        tot = sum(r["parts"].get(k, 0) for k in keys) or 1
        left = 0
        for k in keys:
            v = 100 * r["parts"].get(k, 0) / tot
            if v <= 0:
                continue
            ax.barh(i, v, left=left, color=colors_[k], height=.6, edgecolor="white", linewidth=1)
            if v >= 8:
                ax.text(left + v / 2, i, f"{v:.0f}%", ha="center", va="center", fontsize=6.3,
                        color=INK if k == "internacional" else "white", weight="bold")
            left += v
    ax.set_yticks(range(len(rows))); ax.set_yticklabels([r["label"] for r in rows], fontsize=7)
    ax.invert_yaxis(); ax.set_xlim(0, 100); ax.set_xticks([]); ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0)
    handles = [plt.Rectangle((0, 0), 1, 1, color=colors_[k]) for k in keys]
    ax.legend(handles, [labels(k) for k in keys], ncol=3, fontsize=5.8, frameon=False, loc="upper center",
              bbox_to_anchor=(.45, -0.05), handlelength=.9, columnspacing=.8)
    return fig


# ---------------------------------------------------------------- facts
def event_facts(e, prev=None, sm=None) -> list[str]:
    d = e["demographics"]
    out = [f"Participaron {_fmt(e['participants_total'])} personas de {_fmt(d.get('countries_n'))} países"
           + (f", sobre {_fmt(e.get('registrations'))} inscripciones (tasa de asistencia de {_pct(e.get('conversion_pct'))}"
              + (f"; {_pct(prev.get('conversion_pct'))} en la sesión anterior" if prev and prev.get("conversion_pct") is not None else "")
              + ")." if e.get("registrations") else ".")]
    top3 = d.get("countries", [])[:3]
    if top3:
        names = [c["key"] for c in top3]
        joined = ", ".join(names[:-1]) + " y " + names[-1] if len(names) > 1 else names[0]
        out.append(f"{joined} concentraron el {_pct(sum(c['pct'] for c in top3))} de los participantes con país conocido; "
                   f"el {_pct(d.get('lac_pct'))} provino de América Latina y el Caribe.")
    if e.get("peak_concurrent"):
        out.append(f"El máximo de personas conectadas a la vez fue {_fmt(e['peak_concurrent'])}; la mitad del público estuvo "
                   f"al menos {_fmt(e.get('minutes_median'))} minutos y el {_pct(e.get('late_pct'))} llegó más de 10 minutos tarde.")
    if d.get("women_pct") is not None and len(d.get("sectors", [])) > 1:
        s0, s1 = d["sectors"][0], d["sectors"][1]
        out.append(f"Las mujeres representaron el {_pct(d['women_pct'])}. Por sector destacaron "
                   f"{N.sector_label(s0['key'], 'es_def')} ({_pct(s0['pct'])}) y {N.sector_label(s1['key'], 'es_def')} ({_pct(s1['pct'])}).")
    rc = e.get("registration_curve") or {}
    if rc.get("last_week_pct") is not None:
        out.append(f"El {_pct(rc['last_week_pct'])} de las inscripciones llegó en la última semana y el {_pct(rc.get('same_day_pct'))} el mismo día.")
    tp = e.get("topics") or {}
    tt = [t for t in tp.get("topics", []) if not t["label"].startswith(("Logística", "Otros"))]
    if tt:
        out.append(f"Las preguntas del chat se concentraron en «{tt[0]['label']}» ({tt[0]['n']} de {tp['questions']})"
                   + (f"; {tp['not_addressed']} no tuvieron una respuesta visible." if tp.get("not_addressed") else "."))
    if sm and sm.get("returning"):
        out.append(f"{_fmt(sm['returning'])} personas ({_pct(sm.get('returning_pct'))}) ya habían asistido a un evento anterior de la serie.")
    return out


# ---------------------------------------------------------------- event one-pager
def event_pdf(event_id: str) -> bytes:
    _fonts()
    events, att, mb = _load()
    e = next(x for x in events if x["id"] == event_id)
    ser = CAT.get_series(e["series"])
    same = [x for x in events if x["series"] == e["series"]]
    i = same.index(e)
    prev = same[i - 1] if i > 0 else None
    sm = mb["series"].get(e["series"], {}).get("per_event", {}).get(e["id"], {})
    d = e["demographics"]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
                            title=f"Ficha del evento {event_id}", author="CEPAL")
    story = [Paragraph(f"{ser.get('name_es', '').upper()} · {e.get('type', '')}", _st(7, MUTED, True, space=2)),
             Paragraph(e.get("title_es") or e.get("webinar_name", ""), _st(15, INK, True, 18, 1)),
             Paragraph(" · ".join(x for x in [e.get("speaker"), _date(e.get("date")),
                                             f"evento {i + 1} de {len(same)} de la serie"] if x), _st(8, INK2, space=5))]
    facts = event_facts(e, prev, sm)
    story.append(Paragraph("Datos clave", _st(9, INK, True, space=1)))
    story += [Paragraph("• " + f, _st(7.8, INK, lead=10)) for f in facts[:7]]
    story.append(Spacer(1, 4))
    story.append(_kpi_table([
        (_fmt(e["participants_total"]), "Participantes"), (_fmt(e.get("registrations")), "Inscritos"),
        (_pct(e.get("conversion_pct")), "Tasa de asistencia"), (_fmt(d.get("countries_n")), "Países"),
        (_fmt(e.get("peak_concurrent")), "Pico simultáneo"), (f"{_fmt(e.get('minutes_median'))} min", f"Minutos conectados (mediana, de {_fmt(e.get('duration_min'))})"),
        (_pct(e.get("stayed_half_pct")), "Se quedaron más de la mitad"), (_pct(e.get("late_pct")), "Llegaron tarde (+10 min)"),
        (_pct(d.get("women_pct")), "Mujeres"), (_pct(d.get("lac_pct")), "América Latina y el Caribe"),
        (_pct(sm.get("returning_pct")), "Recurrentes en la serie"), (_fmt((e.get("chat") or {}).get("questions")), "Preguntas en el chat"),
    ], cols=6))
    story.append(Spacer(1, 5))
    fig = _session_chart(e)
    if fig:
        story.append(Paragraph("La sesión minuto a minuto", _st(8.5, INK, True, space=1)))
        story.append(_fig_png(fig, 180, 70))
    # bottom row: countries | sectors + topics
    cs = d.get("countries", [])[:8]
    left = _fig_png(_hbars([c["key"] for c in cs][:8], [c["pct"] for c in cs][:8], figsize=(3.3, 2.2)), 86, 60) if cs else ""
    sx = d.get("sectors", [])
    right = [Paragraph("Sector de los participantes", _st(8.5, INK, True, space=1)),
             _fig_png(_hbars([N.sector_label(x["key"], "es").replace(" e instituciones de investigación", " e investigación")
                              for x in sx], [x["pct"] for x in sx], color=S1, figsize=(3.4, 1.5)), 88, 38)] if sx else []
    tp = e.get("topics") or {}
    if tp.get("topics"):
        right.append(Spacer(1, 3))
        right.append(Paragraph("Temas de las preguntas del chat", _st(8.5, INK, True, space=1)))
        for t in tp["topics"][:5]:
            right.append(Paragraph(f"<b>{t['n']}</b> · {t['label']}" + (f" <font color='{MUTED}'>({t['not_addressed']} sin respuesta visible)</font>"
                                                                        if t.get("not_addressed") else ""), _st(7.3, INK, lead=9.4)))
    bottom = Table([[[Paragraph("Participantes por país", _st(8.5, INK, True, space=1)), left], right]],
                   colWidths=[90 * mm, 90 * mm])
    bottom.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(Spacer(1, 3))
    story.append(bottom)
    notes = []
    dn = e.get("data_notes") or {}
    if dn.get("us_default_discarded"):
        notes.append(f"Se descartaron {dn['us_default_discarded']} respuestas «Estados Unidos» preseleccionadas por Webex.")
    notes.append("Participantes: correos únicos del informe de Webex, incluida la organización. Perfil según el formulario de inscripción.")
    story.append(Spacer(1, 4))
    story.append(Paragraph("Notas: " + " ".join(notes), _st(6.5, MUTED, lead=8.2)))
    doc.build(story, onFirstPage=lambda c, dd: _footer(c, dd, f"Ficha del evento · generada el {_date(date.today().isoformat())}"))
    return buf.getvalue()


# ---------------------------------------------------------------- period report
def period_pdf(start: str | None = None, end: str | None = None, series_ids: list[str] | None = None) -> bytes:
    _fonts()
    events, att, mb = _load()
    sel = [e for e in events if (not start or e["date"] >= start) and (not end or e["date"] <= end)
           and (not series_ids or e["series"] in series_ids)]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
                            title="Informe de eventos", author="CEPAL")
    rng = f"{_date(start or (sel[0]['date'] if sel else None))} – {_date(end or (sel[-1]['date'] if sel else None))}"
    story = [Paragraph("INFORME DE EVENTOS", _st(7.5, MUTED, True, space=2)),
             Paragraph(rng, _st(17, INK, True, 21, 2))]
    if series_ids:
        story.append(Paragraph("Series: " + "; ".join(CAT.get_series(s).get("name_es", s) for s in series_ids), _st(8, INK2, space=4)))
    if not sel:
        story.append(Paragraph("No hay eventos en este período.", _st(10)))
        doc.build(story)
        return buf.getvalue()
    ids = {e["id"] for e in sel}
    a = att[(att.event_id.isin(ids)) & (att.attended == 1) & (att.role.fillna("attendee").isin(["attendee", ""]))]
    reg = att[(att.event_id.isin(ids)) & (att.registered == 1)]
    uniq = a.pid.nunique()
    two = int((a.groupby("pid").event_id.nunique() >= 2).sum())
    parts = sum(e["participants_total"] for e in sel)
    regs = sum(e.get("registrations") or 0 for e in sel)
    conv = [e["conversion_pct"] for e in sel if e.get("conversion_pct") is not None]
    women = a.gender.dropna()
    known_c = a.country.dropna()
    lac = known_c.map(lambda c: N.country_meta(c).get("lac", False))
    sers = list(dict.fromkeys(e["series"] for e in sel))

    summary = (f"En el período se realizaron {len(sel)} eventos en {len(sers)} {'serie' if len(sers) == 1 else 'series'}, "
               f"con {_fmt(parts)} participaciones de {_fmt(uniq)} personas distintas de {_fmt(known_c.nunique())} países. "
               f"{_fmt(two)} personas asistieron a más de un evento. Se recibieron {_fmt(regs)} inscripciones y, en promedio, "
               f"se conectó el {_pct(sum(conv) / len(conv) if conv else None)} de los inscritos.")
    story += [Paragraph(summary, _st(9, INK, lead=12.5, space=6)),
              _kpi_table([(_fmt(len(sel)), "Eventos"), (_fmt(uniq), "Personas distintas"), (_fmt(parts), "Participaciones"),
                          (_fmt(regs), "Inscripciones"), (_pct(sum(conv) / len(conv) if conv else None), "Tasa de asistencia (promedio)"),
                          (_fmt(two), "Asistieron a 2+ eventos"),
                          (_pct(100 * (women == "F").mean() if len(women) else None), "Mujeres"),
                          (_pct(100 * lac.mean() if len(lac) else None), "América Latina y el Caribe")], cols=4),
              Spacer(1, 8)]
    # participants per event, coloured by series
    pal = [S1, S2, S3, S4, S5, S6]
    scol = {s: pal[i % 6] for i, s in enumerate(sers)}
    fig, ax = plt.subplots(figsize=(7.2, 2.3))
    ax.bar(range(len(sel)), [e["participants_total"] for e in sel], color=[scol[e["series"]] for e in sel],
           width=min(.62, .15 + .12 * len(sel)))
    ax.set_xlim(-0.8, len(sel) - 0.2)
    for k, e in enumerate(sel):
        ax.text(k, e["participants_total"], f"{e['participants_total']}", ha="center", va="bottom", fontsize=6.5)
    ax.set_xticks(range(len(sel)))
    ax.set_xticklabels([f"{int(e['date'][8:10])}/{int(e['date'][5:7])}" for e in sel], fontsize=6.5)
    ax.tick_params(length=0)
    handles = [plt.Rectangle((0, 0), 1, 1, color=scol[s]) for s in sers]
    ax.legend(handles, [CAT.get_series(s).get("name_es", s) for s in sers], fontsize=6, frameon=False,
              loc="upper left", bbox_to_anchor=(0, 1.22), ncol=1)
    story += [Paragraph("Participantes por evento", _st(9, INK, True, space=1)), _fig_png(fig, 180, 60), Spacer(1, 6)]
    # events table
    short_date = lambda d: f"{d[8:10]}/{d[5:7]}/{d[2:4]}"
    one = len(sers) == 1
    rows = [[short_date(e["date"]), e.get("title_es") or ""] + ([] if one else [CAT.get_series(e["series"]).get("name_es", "")])
            + [e.get("type", ""), _fmt(e["participants_total"]), _pct(e.get("conversion_pct")),
               _pct(e["demographics"].get("women_pct")), _fmt(e["demographics"].get("countries_n"))] for e in sel]
    head = ["Fecha", "Evento"] + ([] if one else ["Serie"]) + ["Tipo", "Personas", "Asist.", "Mujeres", "Países"]
    widths = [18, 72 if one else 44] + ([] if one else [36]) + [24, 17, 14, 16, 13]
    story += [Paragraph("Eventos" + (f" · {CAT.get_series(sers[0]).get('name_es', '')}" if one else ""), _st(9, INK, True, space=2)),
              _table(head, rows, widths)]
    story.append(PageBreak())
    # by series
    srows = []
    for s in sers:
        es = [e for e in sel if e["series"] == s]
        aa = a[a.event_id.isin({e["id"] for e in es})]
        cv = [e["conversion_pct"] for e in es if e.get("conversion_pct") is not None]
        srows.append([CAT.get_series(s).get("name_es", s), _fmt(len(es)), _fmt(sum(e["participants_total"] for e in es)),
                      _fmt(sum(e["participants_total"] for e in es) / len(es)), _pct(sum(cv) / len(cv) if cv else None),
                      _fmt(aa.pid.nunique()), _fmt(int((aa.groupby("pid").event_id.nunique() >= 2).sum()))])
    story += [Paragraph("Por serie", _st(9, INK, True, space=2)),
              _table(["Serie", "Eventos", "Particip.", "Promedio", "Asistencia", "Personas", "En 2+"], srows,
                     [64, 16, 18, 18, 20, 20, 16]), Spacer(1, 8)]
    # geography and sectors for the period (people, not participations)
    cvc = known_c.value_counts().head(10)
    fig = _hbars(list(cvc.index), [round(100 * v / len(known_c), 1) for v in cvc.values], figsize=(3.4, 2.6))
    sec = a.sector[a.sector != "sin_clasificar"].value_counts()
    keys = [k for k in SECTOR_COLOR if k in sec.index]
    rows_sec = [{"label": "Período", "parts": {k: int(sec[k]) for k in keys}}] + \
               [{"label": f"{int(e['date'][8:10])}/{int(e['date'][5:7])}", "parts": {x["key"]: x["n"] for x in e["demographics"].get("sectors", [])}}
                for e in sel[-6:]]
    fig2 = _stack100(rows_sec, keys, SECTOR_COLOR, lambda k: N.sector_label(k, "es"), figsize=(3.6, 0.32 * len(rows_sec) + .7))
    two_col = Table([[[Paragraph("Países (personas distintas)", _st(9, INK, True, space=1)), _fig_png(fig, 86, 66)],
                      [Paragraph("Sector: período y últimos eventos", _st(9, INK, True, space=1)),
                       _fig_png(fig2, 92, 9 * len(rows_sec) + 18)]]], colWidths=[90 * mm, 90 * mm])
    two_col.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [two_col, Spacer(1, 8)]
    # topics across the period
    agg = {}
    for e in sel:
        for t in (e.get("topics") or {}).get("topics", []):
            if t["label"].startswith(("Logística", "Otros")):
                continue
            g = agg.setdefault(t["label"], {"n": 0, "events": 0, "no": 0})
            g["n"] += t["n"]; g["events"] += 1; g["no"] += t.get("not_addressed", 0)
    if agg:
        trows = [[k, _fmt(v["n"]), _fmt(v["events"]), _fmt(v["no"])] for k, v in sorted(agg.items(), key=lambda kv: -kv[1]["n"])[:10]]
        story += [Paragraph("Temas de las preguntas del público", _st(9, INK, True, space=2)),
                  _table(["Tema", "Preguntas", "Eventos", "Sin respuesta visible"], trows, [96, 24, 24, 36])]
    story.append(Spacer(1, 6))
    story.append(Paragraph("Notas: «participaciones» suma los participantes de cada evento; «personas distintas» cuenta a cada persona una vez "
                           "(público, sin organización). La tasa de asistencia es inscritos que se conectaron sobre inscritos. "
                           "Los temas se agrupan por palabras clave y la detección de respuestas es aproximada.", _st(6.8, MUTED, lead=8.8)))
    doc.build(story, onFirstPage=lambda c, dd: _footer(c, dd, f"Generado el {_date(date.today().isoformat())}"),
              onLaterPages=lambda c, dd: _footer(c, dd, f"Informe de eventos · {rng}"))
    return buf.getvalue()
