from powerwidget.cli import main


def test_now_and_stats_with_mock(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    db = str(tmp_path / "p.db")
    assert main(["--mock", "--db", db, "now"]) == 0
    assert "total" in capsys.readouterr().out
    assert main(["--db", db, "stats"]) == 0
    assert "no data" in capsys.readouterr().out
