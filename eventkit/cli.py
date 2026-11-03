"""Command line entry point.

Run inside a series folder (or pass --home / set EVENTKIT_HOME):

    eventkit init my-series/              # create a new series folder (config, CI, inbox)
    eventkit process                      # every upload waiting in inbox/
    eventkit process path/to/files.zip    # one event
    eventkit rebuild                      # recompute all events from events/*/raw
    eventkit site                         # rebuild the dashboard only
    eventkit docx                         # re-export Word files after editing summaries
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path

import yaml

from . import catalog as CAT
from . import normalize as N
from . import parsers as P
from . import stats as S
from . import store
from . import summarize as SUM
from .docx_out import md_to_docx

from . import paths


def _expand(items: list[Path]) -> list[Path]:
    """Files from folders and zips (zips extracted to a temp dir)."""
    out = []
    for p in items:
        if p.is_dir():
            out += _expand(sorted(x for x in p.iterdir() if not x.name.startswith(".")))
        elif p.suffix.lower() == ".zip":
            tmp = Path(tempfile.mkdtemp(prefix="eventkit_"))
            with zipfile.ZipFile(p) as z:
                z.extractall(tmp)
            out += _expand([tmp])
        elif p.is_file():
            out.append(p)
    return out


def classify_files(files: list[Path]) -> dict[str, list[Path]]:
    kinds = defaultdict(list)
    for f in files:
        k = P.detect(f)
        kinds[k or "unknown"].append(f)
    return kinds


def group_uploads(inbox: Path) -> list[list[Path]]:
    """Each zip or sub-folder is one event; loose files in inbox/ form one more event."""
    groups, loose = [], []
    for p in sorted(inbox.iterdir()):
        if p.name.startswith("."):
            continue
        if p.is_dir() or p.suffix.lower() == ".zip":
            groups.append([p])
        else:
            loose.append(p)
    if loose:
        groups.append(loose)
    return groups


def _fill_sectors_with_claude(frames):
    """Ask Claude for organisations the rules could not place; cache answers in config/org_sectors.csv."""
    items, seen = [], set()
    for f in frames:
        if f is None:
            continue
        u = f[(f.sector == "sin_clasificar") & f.organization.notna()]
        for o, t, e in zip(u.organization, u.job_title, u.email):
            k = N.norm_text(o)
            if k and k not in seen:
                seen.add(k)
                items.append({"organization": str(o), "job_title": str(t or ""), "email_domain": e.split("@")[-1]})
    if not items:
        return False
    found = SUM.classify_orgs_with_claude(items[:400])
    if found:
        N.save_org_cache({N.norm_text(k): (k, v) for k, v in found.items()})
        print(f"  classified {len(found)} organisations with Claude")
        return True
    return False


def process(files: list[Path], force_summary=False, move_raw=True, event_id: str | None = None) -> str:
    kinds = classify_files(_expand(files))
    if not kinds.get("participants"):
        raise SystemExit("No Webex participant report found among: " + ", ".join(f.name for f in files))

    people, meta, raw_rows = P.read_participants(kinds["participants"][0])
    reg = P.read_registration(kinds["registration"][0]) if kinds.get("registration") else None
    chat = P.read_chat(kinds["chat"][0]) if kinds.get("chat") else []
    utts = P.read_transcript(kinds["transcript"][0]) if kinds.get("transcript") else []
    slides = P.read_slides(kinds["slides"][0]) if kinds.get("slides") else []
    ai_sum = P.read_ai_summary(kinds["ai_summary"][0]) if kinds.get("ai_summary") else ""
    overrides = {}
    if kinds.get("event_yml"):
        overrides = yaml.safe_load(kinds["event_yml"][0].read_text(encoding="utf-8")) or {}

    date_id = meta.planned_start.strftime("%Y-%m-%d")
    fixed = event_id or overrides.get("id")
    event_id = fixed or date_id
    series_id = overrides.get("series")
    if not fixed and series_id:
        # same date in another series -> its own event, e.g. 2026-11-03-otra-serie
        other = CAT.event_meta(event_id).get("series")
        if (paths.events_dir() / event_id).exists() and other and other != series_id:
            event_id = f"{date_id}-{series_id}"
    edir = paths.events_dir() / event_id
    # classification: meta.yml (set from the app, e.g. after moving an event) wins over the upload's event.yml
    m = CAT.event_meta(event_id)
    series_id = m.get("series") or series_id or CAT.series_list()[0]["id"]
    event_type = m.get("type") or overrides.get("type") or "Webinar"
    CAT.set_event_meta(event_id, series=series_id, type=event_type)
    ser = CAT.get_series(series_id)
    (edir / "raw").mkdir(parents=True, exist_ok=True)
    print(f"→ {event_id}: {meta.webinar_name}")
    for k, v in sorted(kinds.items()):
        print(f"  {k:13s} {', '.join(x.name for x in v)}")

    # keep the raw exports with the event (rebuilds work from here)
    for k, fs in kinds.items():
        if k == "unknown":
            continue
        for f in fs:
            dest = edir / "raw" / f.name
            if f.resolve() != dest.resolve():
                shutil.copy2(f, dest)

    s, p, regp = S.event_stats(people, raw_rows, meta, reg, chat)
    if _fill_sectors_with_claude([p, regp]):
        N._org_cache.cache_clear()
        s, p, regp = S.event_stats(people, raw_rows, meta, reg, chat)

    ctx = SUM.make_context(meta, utts, chat, slides, ai_sum, p, overrides, series=ser, event_type=event_type)
    status = SUM.write_summaries(edir, ctx, s, force=force_summary)
    print(f"  summaries: {status}")

    # titles for the dashboard
    arts = json.loads((edir / "article.json").read_text(encoding="utf-8")) if (edir / "article.json").exists() else {}
    es, en = arts.get("es", {}), arts.get("en", {})
    s.update({
        "id": event_id,
        "title_es": overrides.get("title_es") or es.get("event_title") or meta.webinar_name,
        "title_en": overrides.get("title_en") or en.get("event_title") or meta.webinar_name,
        "speaker": overrides.get("speaker") or es.get("speaker"),
        "speaker_affiliation": overrides.get("speaker_affiliation") or es.get("speaker_affiliation"),
        "headline_es": es.get("title"),
        "headline_en": en.get("title"),
        "summary_status": status,
        "series": series_id,
        "type": event_type,
    })
    (edir / "stats.json").write_text(json.dumps(s, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    store.save_event(s)
    store.save_attendance(event_id, p, regp)

    for lang in ("es", "en"):
        md = edir / f"summary_{lang}.md"
        if md.exists():
            md_to_docx(md, edir / f"summary_{lang}.docx")

    if move_raw:
        for f in files:
            if paths.inbox_dir().resolve() in f.resolve().parents:
                shutil.rmtree(f) if f.is_dir() else f.unlink()
    return event_id


def rebuild(force_summary=False):
    if not paths.events_dir().exists():
        return
    for edir in sorted(d for d in paths.events_dir().iterdir() if (d / "raw").is_dir()):
        process([edir / "raw"], force_summary=force_summary, move_raw=False, event_id=edir.name)


def export_docx():
    for md in paths.events_dir().glob("*/summary_*.md"):
        md_to_docx(md, md.with_suffix(".docx"))


def init(target: Path):
    """Create a new series folder from the packaged templates."""
    target.mkdir(parents=True, exist_ok=True)
    for d in ("inbox", "events", "data", "config"):
        (target / d).mkdir(exist_ok=True)
    (target / "inbox" / ".gitkeep").touch()
    (target / "events" / ".gitkeep").touch()
    copies = {
        "series.yml": "config/series.yml",
        "event.example.yml": "config/event.example.yml",
        "gitlab-ci.yml": ".gitlab-ci.yml",
        "gitignore": ".gitignore",
        "README_series.md": "README.md",
    }
    for src, dst in copies.items():
        d = target / dst
        if not d.exists():
            shutil.copy2(paths.TEMPLATES / src, d)
    print(f"Series folder ready: {target}\n"
          "  1. edit config/series.yml\n"
          "  2. optional: add config/style_example_es.md (a published article to imitate)\n"
          "  3. push it to a PRIVATE GitLab project and set the CI/CD variables (see README.md)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="eventkit", description="Webinar summaries and participation dashboards.")
    ap.add_argument("--home", type=Path, help="series folder (default: $EVENTKIT_HOME or current directory)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", help="create a new series folder")
    i.add_argument("target", type=Path)
    a = sub.add_parser("process", help="process uploads (default: everything in inbox/)")
    a.add_argument("paths", nargs="*", type=Path)
    a.add_argument("--force-summary", action="store_true", help="rewrite summaries even if they exist")
    r = sub.add_parser("rebuild", help="recompute every event from events/*/raw")
    r.add_argument("--force-summary", action="store_true")
    sub.add_parser("site", help="rebuild the dashboard")
    sub.add_parser("docx", help="re-export Word files from the markdown summaries")
    args = ap.parse_args(argv)
    paths.set_home(args.home)

    from .site import build_site
    if args.cmd == "init":
        init(args.target)
    elif args.cmd == "process":
        groups = []
        targets = args.paths or [paths.inbox_dir()]
        for pth in targets:
            if pth.resolve() == paths.inbox_dir().resolve():
                if pth.exists():
                    groups += group_uploads(pth)
            else:
                groups.append([pth])
        if not groups:
            print("Nothing to process.")
        for g in groups:
            process(g, force_summary=args.force_summary)
        build_site()
    elif args.cmd == "rebuild":
        rebuild(args.force_summary)
        build_site()
    elif args.cmd == "site":
        build_site()
    elif args.cmd == "docx":
        export_docx()


if __name__ == "__main__":
    sys.exit(main())
