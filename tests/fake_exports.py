"""Generate synthetic Webex-style exports (no real people) for tests and demos."""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

COUNTRIES = ["Mexico", "Peru", "Colombia", "Chile", "Argentina", "Costa Rica", "Brazil", "Spain",
             "United States of America"]
ORGS = [("Universidad Nacional", "Docente"), ("Ministerio de Economía", "Analista"),
        ("CEPAL", "Oficial"), ("Consultora Andina S.A.", "Gerente"), ("Fundación Futuro", "Directora"),
        ("Independiente", "Consultor"), ("Calle 10 # 4-21", "Ingeniero")]
TLDS = ["gmail.com", "unal.edu.co", "mineco.gob.pe", "un.org", "empresa.com.mx", "hotmail.com"]


def make(folder: Path, date="2026-05-12", n_reg=120, n_att=60, seed=1, emails=None) -> Path:
    """Write participant (UTF-16 tab csv), registration (webex csv), chat and transcript files."""
    rnd = random.Random(seed)
    folder.mkdir(parents=True, exist_ok=True)
    start = datetime.fromisoformat(f"{date} 12:00:00")
    opened = start - timedelta(minutes=45)
    end = start + timedelta(minutes=75)
    people = emails or [f"persona{seed}_{i}@{rnd.choice(TLDS)}" for i in range(n_reg)]
    q = lambda v: f'="{v}"'

    reg_rows = ["\t".join(["Nombre del seminario web", "Dirección de correo electrónico", "Nombre", "Nombre", "Apellidos",
                           "Estado de registro", "Hora de registro", "Asistido", "ID de registro", "País o región",
                           "Genero/Gender", "Organización/Organization", "Cargo"])]
    for i, e in enumerate(people):
        org, title = rnd.choice(ORGS)
        reg_rows.append("\t".join(["Demo", e, f"Persona {i}", "Persona", str(i), "Aprobado",
                                   q(f"{date} 09:00:00"), "No", q(i), rnd.choice(COUNTRIES),
                                   rnd.choice(["Femenino/Female", "Masculino/Male", "Otro/Other"]), org, title]))
    (folder / "registration.csv").write_bytes("\n".join(reg_rows).encode("utf-16"))

    head = ["ID del seminario web", "Nombre del seminario web", "Hora de inicio planificada del seminario web",
            "Hora de finalización planificada del seminario web", "Duración planificada", "Hora de inicio del seminario web",
            "Hora de finalización del seminario web", "Nombre para mostrar", "Nombre", "Apellido", "Función",
            "Correo electrónico del asistente", "Hora de entrada", "Hora de salida", "Duración de asistencia",
            "Tipo de conexión", "ID de origen", "Nombre de la sesión"]
    rows = ["\t".join(head)]
    fmt = lambda d: q(d.strftime("%Y-%m-%d %H:%M:%S"))
    host = ["host@cepal.org", "panel@uni.edu"]
    for e, role in [(host[0], "host"), (host[1], "panelist")] + [(e, "attendee") for e in rnd.sample(people, n_att)]:
        j = opened if role != "attendee" else start + timedelta(minutes=rnd.randint(-10, 20))
        l = end if rnd.random() < .6 else j + timedelta(minutes=rnd.randint(5, 40))
        mins = int((l - j).total_seconds() // 60)
        rows.append("\t".join([q(123), "Serie demo - Sesión de prueba", fmt(start), fmt(start + timedelta(hours=5)),
                               "300 mins.", fmt(opened), fmt(end), e.split("@")[0], "N/A", "N/A", role, e,
                               fmt(j), fmt(l), f"{mins} mins.", "Web aplicación", "", "Serie demo"]))
    (folder / "participants.csv").write_bytes("\n".join(rows).encode("utf-16"))

    chat = [f"{date} 11:58 : Persona 1 : Buenos días desde Lima",
            f"{date} 12:30 : Persona 2 : ¿Cómo se mide el impacto?",
            f"{date} 13:05 : host : <p>Próxima sesión: <a href=\"https://example.org/r\">registro</a></p>"]
    (folder / "chat.txt").write_text("\n".join(chat), encoding="utf-8")
    tr = ["10:00 : Host : Probando audio.", "45:30 : Host : Bienvenidos a la sesión.",
          "47:00 : Ponente : La coordinación regional es clave para aprovechar las ventanas de oportunidad.",
          "1:10:00 : Ponente : Muchas gracias."]
    (folder / "transcript.txt").write_text("\n".join(tr), encoding="utf-8")
    return folder
