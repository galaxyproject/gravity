from io import StringIO

import yaml

from gravity.settings import (
    GunicornSettings,
    Settings,
    settings_to_sample,
    TusdSettings,
)


def test_json_schema():
    schema = Settings.model_json_schema()
    assert "Configuration for Gravity process manager" in schema["description"]


def test_extra_fields_allowed():
    s = Settings(extra=1)  # type: ignore[call-arg]
    assert not hasattr(s, "extra")


def test_defaults_loaded():
    settings = Settings()
    assert isinstance(settings.gunicorn, GunicornSettings)
    assert settings.gunicorn.bind == "localhost:8080"
    assert isinstance(settings.tusd, TusdSettings)
    assert settings.tusd.tusd_path == "tusd"
    assert settings.tusd.upload_dir == ""


def test_defaults_override_constructor():
    settings = Settings(gunicorn=GunicornSettings(bind="localhost:8081"))
    assert isinstance(settings.gunicorn, GunicornSettings)
    assert settings.gunicorn.bind == "localhost:8081"
    # Try Pydantic's ability to accept dicts for nested models
    settings = Settings(gunicorn={"bind": "localhost:8081"})  # type: ignore[arg-type]
    assert isinstance(settings.gunicorn, GunicornSettings)
    assert settings.gunicorn.bind == "localhost:8081"


def test_defaults_override_env_var(monkeypatch):
    monkeypatch.setenv("GRAVITY_GUNICORN.BIND", "localhost:8081")
    settings = Settings()
    assert isinstance(settings.gunicorn, GunicornSettings)
    assert settings.gunicorn.bind == "localhost:8081"


def test_schema_to_sample():
    sample = settings_to_sample()
    settings = Settings(**yaml.safe_load(StringIO(sample))["gravity"])
    default_settings = Settings()
    assert settings.dict() == default_settings.dict()
