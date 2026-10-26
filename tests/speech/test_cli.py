from friday.speech.cli import _eval


def test_floor_eval_passes_offline(capsys):
    assert _eval(live=False, as_json=False) == 0
    assert "passed (floor only)" in capsys.readouterr().out
