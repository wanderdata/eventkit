"""What happened during the session: phases from the transcript, audience flows, and the
topics of the public's chat questions."""
from __future__ import annotations

import json
import os
import re

import pandas as pd
import yaml

from . import normalize as N
from . import paths
from .parsers import ChatMsg, EventMeta, Utterance, is_question

PHASE_LABELS = {"antes": "Antes del inicio", "bienvenida": "Bienvenida", "presentacion": "Presentación",
                "preguntas": "Preguntas y respuestas", "cierre": "Cierre"}


# ----------------------------------------------------------------- phases
def _blocks(utts: list[Utterance]) -> list[dict]:
    out = []
    for u in utts:
        w = len(u.text.split())
        if out and out[-1]["speaker"] == u.speaker:
            out[-1]["end"] = u.t
            out[-1]["words"] += w
        else:
            out.append({"speaker": u.speaker, "start": u.t, "end": u.t, "words": w})
    return out


def phases(utts: list[Utterance], meta: EventMeta) -> list[dict]:
    """Welcome / presentation / Q&A / closing, in seconds from the recording start and on the clock.

    The main speaker is whoever talks most after the scheduled start; the presentation is their
    longest stretch (short interruptions under a minute are absorbed); Q&A runs until the main
    speaker's last substantial answer; what follows is the closing."""
    if not utts or meta.planned_start is None or meta.actual_start is None:
        return []
    t0 = (meta.planned_start - meta.actual_start).total_seconds() - 5 * 60
    content = [u for u in utts if u.t >= t0]
    if len(content) < 5:
        return []
    words = {}
    for u in content:
        words[u.speaker] = words.get(u.speaker, 0) + len(u.text.split())
    main = max(words, key=words.get)
    bl = _blocks(content)
    # merge main-speaker blocks separated by short interruptions (< 60 s)
    runs, cur = [], None
    for b in bl:
        if b["speaker"] == main:
            if cur and b["start"] - cur["end"] < 60:
                cur["end"] = b["end"]
                cur["words"] += b["words"]
            else:
                cur = dict(b)
                runs.append(cur)
        elif cur and b["end"] - b["start"] >= 60:
            cur = None
    pres = max(runs, key=lambda r: r["words"])
    # welcome starts with the first substantial organizer intervention around the scheduled start
    first = next((b for b in bl if b["words"] >= 40 and b["start"] >= t0), bl[0])
    later_main = [b for b in bl if b["speaker"] == main and b["start"] > pres["end"] and b["words"] >= 200]
    qa_end = later_main[-1]["end"] if later_main else pres["end"]
    end = content[-1].t + 30
    if meta.actual_end is not None:
        end = min(end, (meta.actual_end - meta.actual_start).total_seconds())
    raw = [("bienvenida", first["start"], pres["start"]),
           ("presentacion", pres["start"], pres["end"]),
           ("preguntas", pres["end"], qa_end),
           ("cierre", qa_end, end)]
    out = []
    for key, a, b in raw:
        if b - a < 30:
            continue
        sp = {}
        for u in content:
            if a <= u.t < b:
                sp[u.speaker] = sp.get(u.speaker, 0) + len(u.text.split())
        clock = lambda s: (meta.actual_start + pd.Timedelta(seconds=s))
        out.append({"key": key, "label": PHASE_LABELS[key],
                    "start": clock(a).strftime("%H:%M"), "end": clock(b).strftime("%H:%M"),
                    "start_m": round((clock(a) - meta.planned_start).total_seconds() / 60, 1),
                    "end_m": round((clock(b) - meta.planned_start).total_seconds() / 60, 1),
                    "minutes": round((b - a) / 60, 1),
                    "speakers": [s for s, _ in sorted(sp.items(), key=lambda kv: -kv[1])[:3]],
                    "_a": a, "_b": b})
    return out


def phase_text(utts: list[Utterance], ph: list[dict], key: str) -> str:
    p = next((x for x in ph if x["key"] == key), None)
    if not p:
        return ""
    return " ".join(u.text for u in utts if p["_a"] <= u.t < p["_b"])


def public(ph: list[dict]) -> list[dict]:
    return [{k: v for k, v in p.items() if not k.startswith("_")} for p in ph]


# ----------------------------------------------------------- flows by step
def flows(people_aud: pd.DataFrame, timeline: list[dict], chat: list[ChatMsg], staff: set[str],
          ph: list[dict], step_min=2) -> list[dict]:
    """Per timeline step: arrivals, departures, chat messages, chat questions, phase."""
    if not timeline:
        return []
    day = None
    if len(people_aud) and people_aud["join"].notna().any():
        day = people_aud["join"].dropna().iloc[0].normalize()
    def ts(hhmm):
        h, m = map(int, hhmm.split(":"))
        return day + pd.Timedelta(hours=h, minutes=m) if day is not None else None
    aud_chat = [m for m in chat if N.norm_text(m.name) not in staff]
    out = []
    for p in timeline:
        a = ts(p["t"])
        b = a + pd.Timedelta(minutes=step_min) if a is not None else None
        arr = dep = msgs = qs = 0
        if a is not None:
            arr = int(((people_aud["join"] >= a) & (people_aud["join"] < b)).sum())
            dep = int(((people_aud["leave"] >= a) & (people_aud["leave"] < b)).sum())
            for m in aud_chat:
                if a <= m.time < b:
                    msgs += 1
                    qs += int(is_question(m.text))
        phase = next((x["key"] for x in ph if x["start"] <= p["t"] < x["end"]), "antes" if ph and p["t"] < ph[0]["start"] else None)
        out.append({"t": p["t"], "arrivals": arr, "departures": dep, "messages": msgs, "questions": qs, "phase": phase})
    return out


# ---------------------------------------------------------------- topics
_EMAIL = re.compile(r"\S+@\S+")
_URL = re.compile(r"https?://\S+|www\.\S+")


def _clean(text: str) -> str:
    t = _URL.sub("[enlace]", _EMAIL.sub("[correo]", text))
    return re.sub(r"\s+", " ", t).strip()


def _topic_config() -> dict:
    return yaml.safe_load(paths.config_file("topics.yml").read_text(encoding="utf-8"))


def _hits(text_n: str, kws) -> int:
    return sum(1 for k in kws if re.search(rf"(?<!\w){re.escape(N.norm_text(k))}(?!\w)", text_n))


_STOP = set("""a al algo algunas algunos ante antes como con contra cual cuales cuando de del desde donde dos el ella ellas
ellos en entre era es esa esas ese eso esos esta estas este esto estos fue ha hay la las le les lo los mas me mi mis muy
nos o otra otras otro otros para pero por porque que se sea segun ser si sin sobre su sus tambien tan tanto te tiene
tienen todo todos tu un una uno unos usted y ya podemos puede pueden podria deberia debe hacer cree considera como
gracias muchas excelente buenos dias hola saludos pregunta consulta dr profesor prof estimado felicitaciones senor""".split())


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", N.norm_text(text)) if len(w) >= 5 and w not in _STOP}


def _claude_topics(questions: list[dict]) -> dict | None:
    if not os.environ.get("ANTHROPIC_API_KEY") or not questions:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic()
        prompt = ("Agrupa estas preguntas del público de un seminario web en 3 a 6 temas. Usa etiquetas breves en español "
                  "(máx. 6 palabras). Las preguntas sobre materiales, enlaces, fechas o inscripción van en el tema "
                  "\"Logística (materiales, enlaces, fechas)\". Responde SOLO con JSON {\"<id>\": \"<tema>\"}.\n\n"
                  + json.dumps({q["id"]: q["text"] for q in questions}, ensure_ascii=False))
        msg = client.messages.create(model=os.environ.get("EVENTKIT_MODEL", "claude-opus-5-5"), max_tokens=3000,
                                     messages=[{"role": "user", "content": prompt}])
        txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
    except Exception as e:  # never block processing
        print(f"[eventkit] topic analysis with Claude skipped: {e}")
        return None


def question_topics(chat: list[ChatMsg], staff: set[str], qa_text: str = "") -> dict:
    """Group the audience's chat questions into topics and flag those not visibly addressed in the Q&A."""
    qs = []
    for m in chat:
        if N.norm_text(m.name) in staff or not is_question(m.text):
            continue
        qs.append({"id": str(len(qs)), "text": _clean(m.text), "who": N.norm_text(m.name), "time": m.time.strftime("%H:%M")})
    if not qs:
        return {"questions": 0, "askers": 0, "topics": [], "method": None}
    cfg = _topic_config()
    log_kw = cfg.get("logistica", {}).get("keywords", [])
    log_label = cfg.get("logistica", {}).get("label", "Logística")
    by_claude = _claude_topics(qs)
    qa_terms = _terms(qa_text)
    for q in qs:
        tn = N.norm_text(q["text"])
        if by_claude and q["id"] in by_claude:
            q["topic"] = by_claude[q["id"]]
        elif _hits(tn, log_kw) and len(q["text"]) < 160:
            q["topic"] = log_label
        else:
            scores = [(_hits(tn, t["keywords"]), -i, t["label"]) for i, t in enumerate(cfg.get("topics", []))]
            best = max(scores) if scores else (0, 0, "")
            q["topic"] = best[2] if best[0] > 0 else "Otros temas"
        terms = _terms(q["text"])
        english = len(re.findall(r"\b(the|of|and|that|what|how|is|to)\b", q["text"].lower())) >= 3
        q["addressed"] = (None if q["topic"] == log_label or not qa_terms or not terms or english
                          else len(terms & qa_terms) / len(terms) >= 0.40)
    groups = {}
    for q in qs:
        groups.setdefault(q["topic"], []).append(q)
    order = sorted(groups, key=lambda k: (k in (log_label, "Otros temas"), -len(groups[k])))
    topics = [{"label": k, "n": len(groups[k]), "askers": len({q["who"] for q in groups[k]}),
               "not_addressed": sum(1 for q in groups[k] if q["addressed"] is False),
               "questions": [{"text": q["text"], "time": q["time"], "addressed": q["addressed"]} for q in groups[k]]}
              for k in order]
    return {"questions": len(qs), "askers": len({q["who"] for q in qs}), "topics": topics,
            "not_addressed": sum(1 for q in qs if q["addressed"] is False),
            "method": "claude" if by_claude else "palabras clave"}
