# Deploying the web app (Streamlit Community Cloud)

The app (`streamlit_app.py`) is in Spanish. Events are grouped in **series** (e.g. a webinar cycle; one-off events go under *Eventos individuales*) and have a **type** (Webinar, Seminario presencial, Híbrido, Taller, Conferencia… — extendable). Pages:

- **Subir evento** · **Todos los eventos** (global dashboard) · **Por serie** (dropdown) · **Por evento** (series → event) · **Administrar** (create/rename series, per-series organizers and style example, move an event to another series or type, add event types, platform title).

Older single-series data is migrated automatically on first start: existing events are filed under a series named after the old settings, as webinars.

What each page does:

- **Subir evento**: drag all the files of one event (or a zip). The app recognises each file, shows a checklist, and on *Procesar evento* computes the statistics and saves everything. A ready-made article (`.md`) can go in the same upload.
- **Todos los eventos**: dashboard of every event, mailing list, and the **period report** (PDF for any date range and series).
- **Por serie**: the series dashboard (sessions side by side, retention, profile by session, mailing list).
- **Por evento**: the event dashboard (incl. the minute-by-minute session chart and the topics of the chat questions), the **one-page PDF**, the article (paste or upload `.md`, edit, Word), the automatic review, the original files, **Añadir o reemplazar archivos** (add a missing chat or transcript without re-uploading), and **Eliminar este evento**.

The bottom of every page shows the app version (commit and date), to check that a change is live.

Hosted apps lose their disk when they restart, so the app keeps all event data in a **separate private GitHub repository** (the *data repo*). Every upload, edit or deletion becomes a commit there, so nothing is lost and every change can be undone.

```
github.com/wanderdata/eventkit              code + app (public: no data in it)
github.com/wanderdata/event-tracker-data    data: events/, data/, config/ (private, personal data)
share.streamlit.io                          runs the app, behind APP_PASSWORD
```

## 1. Create the data repository (2 min)
1. github.com → **New repository** → name `event-tracker-data`, **Private**, no README.
2. Load sessions 1–2 into it. Unzip `webinars-cepal-unumerit.zip`, then in a terminal (PowerShell works):
   ```
   cd webinars-cepal-unumerit
   git init -b main
   git add -A
   git commit -m "Sessions 1-2"
   git remote add origin https://github.com/wanderdata/event-tracker-data.git
   git push -u origin main
   ```
   (If you skip this, the app starts with an empty series.)

## 2. Create a token for the app (3 min)
github.com → avatar → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
- Name `event-tracker-app`, expiration 1 year
- **Repository access → Only select repositories → `event-tracker-data`**
- **Permissions → Repository permissions → Contents: Read and write** (nothing else)
- Generate, then copy the `github_pat_…` value.

## 3. Deploy the app (5 min)
1. Go to **share.streamlit.io** and sign in with GitHub (authorize access to private repos when asked).
2. **Create app** → deploy from GitHub: repository `wanderdata/eventkit`, branch `main`, main file `streamlit_app.py`. Under *App URL*, choose a name such as `cepal-webinars`.
3. **Advanced settings → Secrets**: paste the following, with your values:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."   # optional – leave this line out to write articles yourself
   EVENTKIT_SALT = "..."            # generate once, keep a copy, never change
   EVENTKIT_DATA_REPO = "wanderdata/event-tracker-data"
   EVENTKIT_DATA_TOKEN = "github_pat_..."
   APP_PASSWORD = "..."             # recommended; required if the code repo is public
   ```
   Generate the salt with `python -c "import secrets;print(secrets.token_hex(32))"`. In PowerShell without Python, use
   `-join ((1..64) | % { '{0:x}' -f (Get-Random -Max 16) })`.
4. **Deploy**. The first start takes 2–4 minutes.

**If Streamlit only offers public repositories:** make `wanderdata/eventkit` public (it contains code only) and set `APP_PASSWORD`. The app then shows a password screen before anything else, and the data repo stays private.

The current set-up uses the public option: `wanderdata/eventkit` is public and `APP_PASSWORD` protects the app.
Share the app's address and the password with colleagues. (With a private code repo, the app would instead be
invite-only through **Share**, and Streamlit's free tier allows one such app per account.)

## 4. Using it after an event
1. Download the Webex exports (participants, registration, transcript `.txt` or `.vtt`, chat, meeting summary) and the slides.
2. App → **Subir evento** → drag them all in → check the list → choose series and type → **Procesar evento**.
3. Add the article (see below), then read **Revisión automática**: it flags quotes that don't match the transcript and names to verify.
4. A file was missing or not recognised? **Por evento → Añadir o reemplazar archivos**.

## Without a Claude API key (manual articles)
Leave `ANTHROPIC_API_KEY` out of the secrets. Everything else works the same. For each event without an article, **Por evento → Nota informativa** offers:
- **Descargar el texto preparado para Claude**: the transcript, chat, slides and style instructions in one file, ready to paste into Claude for a draft;
- **Párrafo de cifras**: the participation paragraph, generated from the data, to copy into your article;
- a box to **paste the final article**, or a button to **upload it as `.md`** (Spanish and English tabs). Saving creates the Word file, adds the participation paragraph if missing, and runs the automatic quote check.

You can add the key later; new events then get their article written automatically.

## Updating the app
Push to `main` of `wanderdata/eventkit` and Streamlit redeploys automatically. The data repo is unaffected.

## Running it on your own computer
```
pip install "eventkit[app] @ git+https://github.com/wanderdata/eventkit@main"   # needs access to the repo
streamlit run streamlit_app.py
```
Without `EVENTKIT_DATA_REPO`, the app keeps data in a local folder (`EVENTKIT_HOME`, default `./event-data`).

## Privacy
The data repo holds the raw exports (names, e-mails) of every participant. Keep it private, give the token access to that repo only, and check with ECLAC that storing them on GitHub is acceptable. The dashboards and PDFs show aggregates only. Without `ANTHROPIC_API_KEY` (the current set-up) nothing is sent to an AI service; with it, transcript, chat and slide text (not participant lists) are sent to the Claude API to draft the articles, and organization names to classify sectors.
