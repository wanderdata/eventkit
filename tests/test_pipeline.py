import json
import zipfile

import pytest

from eventkit import cli, normalize as N, parsers as P, paths, store
from tests.fake_exports import make


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("EVENTKIT_SALT", "test-salt")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cli.init(tmp_path / "series")
    paths.set_home(tmp_path / "series")
    N._org_cache.cache_clear()
    yield tmp_path / "series"
    paths.set_home(None)


def test_detection(tmp_path):
    f = make(tmp_path / "x")
    kinds = {P.detect(p): p.name for p in f.iterdir()}
    assert set(kinds) == {"participants", "registration", "chat", "transcript"}


def test_normalizers():
    assert N.country("  PERÚ ") == "Perú"
    assert N.country("Chile, Santiago") == "Chile"
    assert N.country("CR") == "Costa Rica"
    assert N.gender("MUJER ") == "F" and N.gender("Masculino/Male") == "M"
    assert N.sector("Ministerio de Economía", "a@gmail.com")[0] == "publico"
    assert N.sector("x", "a@uni.edu.co")[0] == "academia"
    assert N.sector("Calle 10 # 4-21", "a@gmail.com", "Ingeniero")[0] == "otros"


def test_full_pipeline_from_inbox_zip(home, tmp_path):
    src = make(tmp_path / "ev1", date="2026-05-12", seed=1)
    with zipfile.ZipFile(home / "inbox" / "ev1.zip", "w") as z:
        for f in src.iterdir():
            z.write(f, f.name)
    cli.main(["--home", str(home), "process"])

    edir = home / "events" / "2026-05-12"
    s = json.loads((edir / "stats.json").read_text())
    assert s["participants_total"] == 62 and s["attendees"] == 60 and s["registrations"] == 120
    assert s["demographics"]["countries_n"] >= 5
    assert (edir / "prompt_es.md").exists()          # no API key -> prompt for manual use
    assert not list((home / "inbox").glob("*.zip"))  # upload consumed
    html = (home / "public" / "index.html").read_text()
    assert "2026-05-12" in html and "@" not in html.split("const DATA")[1].split("</script>")[0]


def test_returning_attendees(home, tmp_path):
    people = [f"p{i}@gmail.com" for i in range(80)]
    cli.process([make(tmp_path / "a", date="2026-05-12", emails=people, n_att=40, seed=2)])
    cli.process([make(tmp_path / "b", date="2026-06-12", emails=people, n_att=40, seed=3)])
    m = store.series_metrics(store.load_attendance(), store.load_events())
    assert m["events"] == 2
    assert m["per_event"]["2026-06-12"]["returning"] > 0
    assert "@" not in (home / "data" / "attendance.csv").read_text()
