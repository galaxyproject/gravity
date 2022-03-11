import json

from gravity.settings import Settings


def test_schema_json():
    schema = Settings.schema_json(indent=2)
    assert "Configuration for gravity process manager" in json.loads(schema)['description']


def test_defaults_loaded():
    settings = Settings()
    assert settings.gunicorn.bind == 'localhost:8080'


def test_defaults_override_constructor():
    settings = Settings(**{'gunicorn': {'bind': 'localhost:8081'}})
    assert settings.gunicorn.bind == 'localhost:8081'


def test_defaults_override_env_var(monkeypatch):
    monkeypatch.setenv("GRAVITY_GUNICORN.BIND", "localhost:8081")
    settings = Settings()
    assert settings.gunicorn.bind == 'localhost:8081'
