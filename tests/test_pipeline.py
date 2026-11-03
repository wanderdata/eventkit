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


def test_git_store_roundtrip(tmp_path, monkeypatch):
    import subprocess
    from eventkit.storage import GitStore
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    a = GitStore(f"file://{bare}", root=tmp_path / "a")
    ra = a.sync()                                   # empty remote -> new history
    (ra / "events").mkdir()
    (ra / "events" / "x.txt").write_text("hola")
    assert a.save("first") is True
    assert a.save("nothing new") is False
    b = GitStore(f"file://{bare}", root=tmp_path / "b")
    assert (b.sync() / "events" / "x.txt").read_text() == "hola"
    (b.root / "events" / "y.txt").write_text("b")
    b.save("from b")
    (ra / "events" / "z.txt").write_text("a")       # a is behind -> push must rebase
    a.save("from a")
    assert {p.name for p in (a.sync() / "events").iterdir()} == {"x.txt", "y.txt", "z.txt"}
    assert ".eventkit_salt" in (a.root / ".gitignore").read_text()


def test_app_starts_and_shows_pages(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("EVENTKIT_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("EVENTKIT_DATA_REPO", raising=False)
    monkeypatch.setenv("EVENTKIT_SALT", "test-salt")
    app = Path(__file__).resolve().parent.parent / "streamlit_app.py"
    at = AppTest.from_file(str(app), default_timeout=60).run()
    assert not at.exception
    assert any("Subir un evento" in t.value for t in at.title)
    for page in ("Todos los eventos", "Por serie", "Por evento", "Administrar"):
        at.session_state["page"] = page
        at.session_state["nav"] = page
        at.run()
        assert not at.exception


def test_app_password_gate(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("EVENTKIT_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("EVENTKIT_DATA_REPO", raising=False)
    monkeypatch.setenv("APP_PASSWORD", "secreto")
    app = Path(__file__).resolve().parent.parent / "streamlit_app.py"
    at = AppTest.from_file(str(app), default_timeout=60).run()
    assert not any("Subir un evento" in t.value for t in at.title)      # locked
    at.text_input[0].set_value("mala")
    at.button[0].click().run()
    assert at.error and not any("Subir un evento" in t.value for t in at.title)
    at.text_input[0].set_value("secreto")
    at.button[0].click().run()
    assert any("Subir un evento" in t.value for t in at.title)          # unlocked


def test_git_store_bad_remote_raises(tmp_path):
    from eventkit.storage import GitStore
    s = GitStore(f"file://{tmp_path}/does-not-exist.git", root=tmp_path / "c")
    with pytest.raises(RuntimeError, match="No se puede acceder"):
        s.sync()


def test_mailing_list_unique_across_events(home, tmp_path):
    from eventkit import export
    people = [f"p{i}@gmail.com" for i in range(80)]
    cli.process([make(tmp_path / "a", date="2026-05-12", emails=people, n_att=40, seed=2)])
    cli.process([make(tmp_path / "b", date="2026-06-12", emails=people[:50] + [f"n{i}@x.org" for i in range(10)],
                      n_att=30, seed=3)])
    df = export.mailing_list()
    assert df.correo.is_unique and len(df) == 80 + 10 + 2          # + host/panelist
    assert set(df.columns) == set(export.COLUMNS)
    att = export.mailing_list(only_attended=True)
    assert len(att) < len(df) and (att.sesiones_asistidas >= 1).all()
    one = export.mailing_list(["2026-06-12"])
    assert len(one) == 60 + 2
    assert export.to_excel(df)[:2] == b"PK" and export.to_text(df).count(b"\n") == len(df)


def test_series_catalog_and_app_pages(home, tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    import yaml
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from eventkit import catalog as CAT
    from eventkit.site import build_site
    CAT.ensure()
    a = CAT.add_series("Serie A", "Series A")
    b = CAT.add_series("Serie B", "Series B")
    d1 = make(tmp_path / "e1", date="2026-05-12", seed=4)
    (d1 / "event.yml").write_text(yaml.safe_dump({"series": a, "type": "Webinar"}))
    d2 = make(tmp_path / "e2", date="2026-05-12", seed=5)                    # same date, other series
    (d2 / "event.yml").write_text(yaml.safe_dump({"series": b, "type": "Taller"}))
    e1, e2 = cli.process([d1]), cli.process([d2])
    assert e1 == "2026-05-12" and e2 == f"2026-05-12-{b}"
    CAT.set_event_meta(e2, series=a)                                        # move B -> A
    cli.rebuild()
    assert CAT.event_meta(e2)["series"] == a and CAT.event_meta(e2)["type"] == "Taller"
    html = build_site().read_text()
    assert '"series_metrics"' in html and a in html
    monkeypatch.setenv("EVENTKIT_HOME", str(home))
    app = Path(__file__).resolve().parent.parent / "streamlit_app.py"
    at = AppTest.from_file(str(app), default_timeout=90).run()
    for page in ("Todos los eventos", "Por serie", "Por evento", "Administrar"):
        at.session_state["page"] = page
        at.session_state["nav"] = page
        at.run()
        assert not at.exception, (page, at.exception)


def test_new_indicators_present(home, tmp_path):
    from eventkit.stats import STATS_VERSION
    cli.process([make(tmp_path / "x", date="2026-05-12", seed=9)])
    e = store.load_events()[0]
    assert e["stats_version"] == STATS_VERSION
    assert e["minutes_hist"] and e["registration_curve"]["points"] and "late_pct" in e
    assert all("m" in p for p in e["timeline"])
