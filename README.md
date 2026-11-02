# eventkit

Turn the files Webex exports after a webinar into:

1. a **news article in Spanish and English** written by Claude (with Word downloads and an automatic check of quotes and names);
2. **participation statistics** for the event: registrations, show-up rate, countries, gender, sector, time connected, chat activity;
3. a **series dashboard** (static HTML for GitLab Pages) that tracks all events together, including returning attendees.

The tool holds **no data**. Each webinar series lives in its own private folder or repository (a *series folder*), and that's where you run `eventkit`.

```
github.com/wanderdata/eventkit          ← this repo: code only (public)
git.cepal.org/.../<series-project>      ← one private project per series: inbox/, events/, data/, config/
```

## Quick start

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
| Transcript (.txt) | Article content, quote checking |
| Chat (.txt) | Questions, links, next-session announcement |
| Slides (.pptx/.pdf) | Authoritative spelling of names and figures |
| Webex AI summary (.txt) | Orientation only |
| `event.yml` (optional) | Manual facts: title, speaker… |

## Commands

| Command | |
|---|---|
| `eventkit init DIR` | new series folder |
| `eventkit process [ZIP/FOLDER…]` | process uploads (default: everything in `inbox/`) |
| `eventkit rebuild [--force-summary]` | recompute all events from `events/*/raw` |
| `eventkit site` | rebuild the dashboard |
| `eventkit docx` | re-export Word files after editing `summary_*.md` |

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

## Privacy

The dashboard and `data/` contain aggregates and anonymous IDs only. The raw exports (`events/*/raw`) contain personal data and must stay in a private repository. Transcript, chat and slide text are sent to the Claude API to write the article. Organization names (without people's names) are sent to classify sectors.

## Development

```bash
pip install -e ".[test]"
pytest -q          # uses synthetic exports from tests/fake_exports.py
```
