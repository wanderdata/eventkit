# Deploying the web app (Streamlit Community Cloud)

The app (`streamlit_app.py`) has three pages, all in Spanish:

- **Subir evento**: drag all the Webex files of one event (or a zip). The app recognises each file, shows a checklist, and on *Procesar evento* computes the statistics, has Claude write the article (ES + EN), and saves everything.
- **Toda la serie**: the series dashboard.
- **Por evento**: pick an event from the dropdown to see its KPI panel, charts, article (read, edit, download Word), automatic review, and the original input files (download one by one or as a zip).

Hosted apps lose their disk when they restart, so the app keeps all event data in a **separate private GitHub repository** (the *data repo*). Every upload, edit or deletion becomes a commit there, so nothing is lost and every change can be undone.

```
github.com/wanderdata/eventkit              code + app (private)
github.com/wanderdata/event-tracker-data    data: events/, data/, config/ (private, personal data)
share.streamlit.io                          runs the app, invited viewers only
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
   ANTHROPIC_API_KEY = "sk-ant-..."
   EVENTKIT_SALT = "..."            # generate once, keep a copy, never change
   EVENTKIT_DATA_REPO = "wanderdata/event-tracker-data"
   EVENTKIT_DATA_TOKEN = "github_pat_..."
   ```
   Generate the salt with `python -c "import secrets;print(secrets.token_hex(32))"`. In PowerShell without Python, use
   `-join ((1..64) | % { '{0:x}' -f (Get-Random -Max 16) })`.
4. **Deploy**. The first start takes 2–4 minutes.

Because `eventkit` is a private repo, the app is **private**: only people you invite can open it.
Invite colleagues with **Share** (top right of the app) by e-mail; they sign in with Google or a one-time e-mailed link.
Streamlit's free tier allows one private app per account.

## 4. Using it after an event
1. Download the Webex exports (participants, registration, transcript, chat, meeting summary) and the slides.
2. App → **Subir evento** → drag them all in → check the list → (optional title/speaker) → **Procesar evento**.
3. 1–3 minutes later, open **Por evento** and read **Revisión automática** first: it flags quotes that don't match the transcript and names to verify.
4. Fix the article with **Editar** if needed. The Word file and dashboard update when you save.

## Updating the app
Push to `main` of `wanderdata/eventkit` and Streamlit redeploys automatically. The data repo is unaffected.

## Running it on your own computer
```
pip install "eventkit[app] @ git+https://github.com/wanderdata/eventkit@main"   # needs access to the repo
streamlit run streamlit_app.py
```
Without `EVENTKIT_DATA_REPO`, the app keeps data in a local folder (`EVENTKIT_HOME`, default `./event-data`).

## Privacy
The data repo holds the raw exports (names, e-mails) of every participant. Keep it private, give the token access to that repo only, and check with ECLAC that storing them on GitHub is acceptable. The dashboards show aggregates only. Transcript, chat and slide text are sent to the Claude API to write the articles.
