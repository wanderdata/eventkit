# Webinar series – summaries and dashboard

This private project holds the data of one webinar series. The pipeline uses
[eventkit](https://github.com/wanderdata/eventkit) to write each event's article
(Spanish and English) and to publish the participation dashboard on GitLab Pages.

⚠️ `events/*/raw/` contains personal data (names, e-mails). Keep this project **private**.

## Subir un evento (guía rápida)

1. Después del webinar, descarga de Webex: *informe de participantes*, *informe de inscripción*,
   *transcripción*, *chat*, *resumen de la reunión* y la presentación del ponente (.pptx o .pdf).
2. Comprímelos en **un solo .zip** (los nombres de archivo no importan). Opcional: agrega un
   `event.yml` (ver `config/event.example.yml`) para fijar título, ponente, etc.
3. En GitLab: *Code → Repository →* carpeta `inbox/` → **+ → Upload file** → sube el .zip → *Commit*.
4. Espera 3–5 minutos (*Build → Pipelines*). Se crea `events/AAAA-MM-DD/` con la nota en español
   e inglés (`.md` y `.docx`), `review.md` y el tablero actualizado (*Deploy → Pages*).
5. **Revisa `review.md`**: citas marcadas ⚠️/❌, nombres a verificar y dudas señaladas.
6. Para corregir la nota, edita `summary_es.md` / `summary_en.md` (*Edit*). Al guardar se regeneran
   el Word y el tablero. El párrafo de cifras se actualiza solo: no lo edites.

Sube **un zip por evento**: si subes archivos sueltos, cada uno lanza un pipeline y el evento puede
procesarse incompleto.

Para corregir el sector de una organización: edita `config/org_sectors.csv`
(`organization,sector,source`; sectores: publico, academia, privado, internacional, sociedad_civil, otros).

## Setup (once)

1. Settings → CI/CD → Variables (Masked, Protected):
   - `ANTHROPIC_API_KEY` – Claude API key.
   - `EVENTKIT_SALT` – long random string; keep a copy, never change it.
   - `GITLAB_PUSH_TOKEN` – Settings → Access tokens → role *Developer*, scope *write_repository*.
2. Settings → General → Visibility: Pages → **Only project members**.
3. Runners must reach `github.com`, `pypi.org` and `api.anthropic.com`.
4. Build → Pipelines → **Run pipeline**. The dashboard URL is under Deploy → Pages.

## Run locally

```bash
pip install "eventkit @ git+https://github.com/wanderdata/eventkit@v0.1.0"
export EVENTKIT_SALT=...        # same value as the GitLab variable
export ANTHROPIC_API_KEY=...    # optional; without it a prompt file is written instead
eventkit process path/to/export.zip
eventkit rebuild
open public/index.html
```
