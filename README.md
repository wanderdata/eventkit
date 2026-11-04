# eventkit

Turn the files Webex (or Teams/Zoom captions) produce after an event into:

1. **participation statistics**: registrations, show-up rate, countries, gender, sector, time connected, returning people;
2. **what happened in the session**: phases (welcome, presentation, Q&A, closing) from the transcript, arrivals,
   departures and chat activity minute by minute, and the topics of the audience's questions;
3. **dashboards in Spanish** for all events, each series and each event;
4. an **article in Spanish and English** (written by hand and uploaded, or drafted by Claude when an API key is set),
   with Word downloads and an automatic check of quotes and names;
5. **PDF reports**: a one-page summary per event and a report for any period;
6. a **mailing list** of unique e-mails.

A plain-language guide for colleagues is kept as a separate document ("Event platform: what it does, in plain language").

The tool holds **no data**. Event files live in a separate private folder or repository:

```
github.com/wanderdata/eventkit              ← this repo: code only (public)
github.com/wanderdata/event-tracker-data    ← private: events/, data/, config/ (personal data)
```

## Web app (upload page + dashboards)

`streamlit_app.py` is a Spanish web app on top of the same code. Events belong to a **series** and have a **type**
(`config/catalog.yml`, per event `events/<id>/meta.yml`). Pages: **Subir evento**, **Todos los eventos**,
**Por serie**, **Por evento**, **Administrar** (details in [DEPLOY.md](DEPLOY.md), which also explains how to put it
online with Streamlit Community Cloud).

```bash
pip install -e ".[app]"
streamlit run streamlit_app.py      # local folder ./event-data unless EVENTKIT_DATA_REPO is set
```

## Quick start (command line)

```bash
pip install "eventkit @ git+https://github.com/wanderdata/eventkit@v0.1.0"

eventkit init my-series          # creates config/, inbox/, .gitlab-ci.yml, README
cd my-series
export EVENTKIT_SALT=$(python -c "import secrets;print(secrets.token_hex(32))")   # keep it!
export ANTHROPIC_API_KEY=...     # optional
eventkit process path/to/webex-exports.zip
open public/index.html
```

Without an API key everything except the article runs. `events/<id>/prompt_es.md` is written instead: paste it into Claude, save the JSON answer as `events/<id>/article.json` and run `eventkit rebuild`.

## Inputs (detected by content, not file name)

| Export | Used for |
|---|---|
| Webex participant report (.csv/.xlsx) | **Required.** Attendance, minutes, timeline, event date |
| Webex registration report, or Microsoft Forms export | Country, gender, organization, show-up rate |
| Transcript: Webex .txt, or .vtt captions (Webex, Teams, Zoom) | Session phases, article content, quote checking. A transcript clearly shorter than the webinar (a late-starting recording) is aligned on the webinar's end |
| Chat: Webex export (.txt), or the chat copied from the recording page (.txt, "Ayer, 9:01" blocks) | Messages, questions and their topics (`topics.yml`) |
| Slides (.pptx/.pdf) | Authoritative spelling of names and figures |
| Webex AI summary (.txt) | Orientation only |
| Ready-made article (.md; `_es` / `_en` in the name, or detected) | Used as the event's article |
| `event.yml` (optional) | Manual facts: title, speaker, series, type… |

## Commands

| Command | |
|---|---|
| `eventkit init DIR` | new series folder |
| `eventkit process [ZIP/FOLDER…]` | process uploads (default: everything in `inbox/`) |
| `eventkit rebuild [--force-summary]` | recompute all events from `events/*/raw` |
| `eventkit site` | rebuild the dashboard |
| `eventkit docx` | re-export Word files after editing `summary_*.md` |
| `eventkit report event ID` / `report period --from --to --series` | PDF: one-page event summary / period report |

All commands accept `--home DIR` (or `$EVENTKIT_HOME`).

## Series folder

```
config/series.yml           series name, organizers, dashboard title
config/style_example_es.md  a published article Claude should imitate (recommended)
config/org_sectors.csv      organization → sector decisions (edit to correct; Claude appends)
config/countries.yml, sectors.yml, dashboard.html   optional overrides of the package defaults
inbox/                      uploads
events/<date>/raw/          original exports (personal data)
events/<date>/summary_es.md / summary_en.md / *.docx / review.md / stats.json
data/events.json            per-event aggregates
data/attendance.csv         anonymised ID × event (salted SHA-256 of the e-mail)
public/index.html           dashboard
```

## How the numbers are built

- **Participants** = unique e-mails in the participant report (organizers included); reconnections merged.
- **Demographics** come from participants matched to the registration form.
- **Webex pre-selects "United States"** in registration forms: such answers are kept only with a US-looking e-mail, otherwise inferred from the e-mail's country domain or left unknown.
- **Sector**: `org_sectors.csv` → e-mail domain (.gob, .edu, un.org…) → keywords (`sectors.yml`) → Claude.
- **Returning attendees** use the anonymous ID, so `EVENTKIT_SALT` must never change.
- The participation paragraph of each article is generated from these numbers, never by the model.
- **Phases**: the main speaker (most words after the scheduled start) → their longest stretch is the presentation; Q&A runs to their last answer of 200+ words.
- **Topics**: keywords in `topics.yml` (Spanish and English); "no visible answer" = under 40% of the question's terms appear in the Q&A, checked only when question and talk share a language.

## Privacy

The dashboard and `data/` contain aggregates and anonymous IDs only. The raw exports (`events/*/raw`) contain personal data and must stay in a private repository. Only when `ANTHROPIC_API_KEY` is set: transcript, chat and slide text are sent to the Claude API to draft the article, and organization names (without people's names) to classify sectors.

## Development

```bash
pip install -e ".[test]"
pytest -q          # uses synthetic exports from tests/fake_exports.py
```
