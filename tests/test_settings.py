from io import StringIO
import json

from gravity.settings import Settings
from gravity.util import settings_to_sample
from yaml import safe_load


def test_schema_json():
    schema = Settings.schema_json(indent=2)
    assert "Configuration for Gravity process manager" in json.loads(schema)["description"]


def test_extra_fields_allowed():
    s = Settings(extra=1)
    assert not hasattr(s, "extra")


def test_defaults_loaded():
    settings = Settings()
    assert settings.gunicorn.bind == "localhost:8080"


def test_defaults_override_constructor():
    settings = Settings(**{"gunicorn": {"bind": "localhost:8081"}})
    assert settings.gunicorn.bind == "localhost:8081"


def test_defaults_override_env_var(monkeypatch):
    monkeypatch.setenv("GRAVITY_GUNICORN.BIND", "localhost:8081")
    settings = Settings()
    assert settings.gunicorn.bind == "localhost:8081"


def test_schema_to_sample():
    sample = settings_to_sample()
    settings = Settings(**safe_load(StringIO(sample))["gravity"])
    default_settings = Settings()
    assert settings.dict() == default_settings.dict()
