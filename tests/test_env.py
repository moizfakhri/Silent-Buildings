from nycdistress.env import load_dotenv, parse_env


def test_parse_env_ignores_comments_and_blanks():
    text = "# c\n\nSOCRATA_APP_TOKEN=abc123\n  # indented comment\nEMPTY=\nnoequals\n"
    assert parse_env(text) == {"SOCRATA_APP_TOKEN": "abc123", "EMPTY": ""}


def test_parse_env_quotes_export_inline_comment():
    text = "export A='x y'\nB=\"z\"\nC=val # trailing\nD=has#hash\n"
    assert parse_env(text) == {"A": "x y", "B": "z", "C": "val", "D": "has#hash"}


def test_load_dotenv_sets_only_when_unset(tmp_path, capsys):
    f = tmp_path / ".env"
    f.write_text("SOCRATA_APP_TOKEN=fromfile\nOTHER=1\n")
    env = {"OTHER": "keep"}
    assert load_dotenv(f, env) == ["SOCRATA_APP_TOKEN"]
    assert env == {"OTHER": "keep", "SOCRATA_APP_TOKEN": "fromfile"}
    assert capsys.readouterr().out == ""  # never prints values


def test_load_dotenv_env_var_wins_and_empty_is_unset(tmp_path):
    f = tmp_path / ".env"
    f.write_text("SOCRATA_APP_TOKEN=fromfile\n")
    env = {"SOCRATA_APP_TOKEN": "fromenv"}
    assert load_dotenv(f, env) == [] and env["SOCRATA_APP_TOKEN"] == "fromenv"
    env = {"SOCRATA_APP_TOKEN": ""}
    assert load_dotenv(f, env) == ["SOCRATA_APP_TOKEN"] and env["SOCRATA_APP_TOKEN"] == "fromfile"


def test_load_dotenv_missing_or_blank_token(tmp_path):
    assert load_dotenv(tmp_path / "nope.env", {}) == []
    f = tmp_path / ".env"
    f.write_text("SOCRATA_APP_TOKEN=\n")  # as in .env.example: blank means no token
    env = {}
    assert load_dotenv(f, env) == [] and "SOCRATA_APP_TOKEN" not in env
