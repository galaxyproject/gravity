import json
from pathlib import Path

from gravity import __version__, config_manager
from gravity.settings import Settings
from gravity.state import GracefulMethod


def test_load_defaults(galaxy_yml, galaxy_root_dir, state_dir, default_config_manager):
    default_config_manager.load_config_file(str(galaxy_yml))
    config = default_config_manager.get_config()
    default_settings = Settings()
    assert config['config_type'] == 'galaxy'
    assert config['instance_name'] == default_settings.instance_name
    assert config['services'] != []
    attributes = config['attribs']
    assert attributes['app_server'] == 'gunicorn'
    assert Path(attributes['log_dir']) == Path(state_dir) / 'log'
    assert Path(config['galaxy_root']) == galaxy_root_dir
    gunicorn_attributes = attributes['gunicorn']
    assert gunicorn_attributes['bind'] == default_settings.gunicorn.bind
    assert gunicorn_attributes['workers'] == default_settings.gunicorn.workers
    assert gunicorn_attributes['timeout'] == default_settings.gunicorn.timeout
    assert gunicorn_attributes['extra_args'] == default_settings.gunicorn.extra_args
    assert gunicorn_attributes['preload'] is True
    assert attributes['celery'] == default_settings.celery.dict()
    assert attributes["tusd"] == default_settings.tusd.dict()


def test_preload_default(galaxy_yml, default_config_manager):
    app_server = 'unicornherder'
    galaxy_yml.write(json.dumps({
        'galaxy': None,
        'gravity': {
            'app_server': app_server
        }
    }))
    default_config_manager.load_config_file(str(galaxy_yml))
    config = default_config_manager.get_config()
    gunicorn_attributes = config['attribs']['gunicorn']
    assert gunicorn_attributes['preload'] is False


def test_load_non_default(galaxy_yml, default_config_manager, non_default_config):
    if default_config_manager.instance_count == 0:
        galaxy_yml.write(json.dumps(non_default_config))
        default_config_manager.load_config_file(str(galaxy_yml))
    config = default_config_manager.get_config()
    gunicorn_attributes = config['attribs']['gunicorn']
    assert gunicorn_attributes['bind'] == non_default_config['gravity']['gunicorn']['bind']
    assert gunicorn_attributes['environment'] == non_default_config['gravity']['gunicorn']['environment']
    default_settings = Settings()
    assert gunicorn_attributes['workers'] == default_settings.gunicorn.workers
    celery_attributes = config['attribs']['celery']
    assert celery_attributes['concurrency'] == non_default_config['gravity']['celery']['concurrency']


def test_split_config(galaxy_yml, galaxy_root_dir, default_config_manager, non_default_config):
    default_config_file = str(galaxy_root_dir / "config" / "galaxy.yml.sample")
    non_default_config['gravity']['galaxy_config_file'] = default_config_file
    del non_default_config['galaxy']
    galaxy_yml.write(json.dumps(non_default_config))
    default_config_manager.load_config_file(str(galaxy_yml))
    test_load_non_default(galaxy_yml, default_config_manager, non_default_config)
    config = default_config_manager.get_config()
    assert config.__file__ == str(galaxy_yml)
    assert config.galaxy_config_file == default_config_file


def test_auto_load_env_var(galaxy_yml, default_config_manager, monkeypatch):
    monkeypatch.setenv("GALAXY_CONFIG_FILE", str(galaxy_yml))
    assert default_config_manager.instance_count == 0
    default_config_manager.auto_load()
    assert default_config_manager.is_loaded(galaxy_yml)


def test_auto_load_root_dir(galaxy_root_dir, monkeypatch):
    monkeypatch.chdir(galaxy_root_dir)
    galaxy_yml_sample = galaxy_root_dir / "config" / "galaxy.yml.sample"
    with config_manager.config_manager() as cm:
        assert cm.instance_count == 1
        assert cm.is_loaded(galaxy_yml_sample)
    galaxy_yml = galaxy_root_dir / "config" / "galaxy.yml"
    galaxy_yml_sample.copy(galaxy_yml)
    with config_manager.config_manager() as cm:
        assert cm.instance_count == 1
        assert cm.is_loaded(galaxy_yml)
    galaxy_yml.remove()


def test_gunicorn_graceful_method_preload(galaxy_yml, default_config_manager):
    default_config_manager.load_config_file(str(galaxy_yml))
    config = default_config_manager.get_config()
    gunicorn_service = [s for s in config["services"] if s["service_name"] == "gunicorn"][0]
    graceful_method = gunicorn_service.get_graceful_method(config["attribs"])
    assert graceful_method == GracefulMethod.DEFAULT


def test_gunicorn_graceful_method_no_preload(galaxy_yml, default_config_manager):
    galaxy_yml.write(json.dumps(
        {'galaxy': None, 'gravity': {
            'gunicorn': {'preload': False}}}
    ))
    default_config_manager.load_config_file(str(galaxy_yml))
    config = default_config_manager.get_config()
    gunicorn_service = [s for s in config["services"] if s["service_name"] == "gunicorn"][0]
    graceful_method = gunicorn_service.get_graceful_method(config["attribs"])
    assert graceful_method == GracefulMethod.SIGHUP


# TODO: tests for switching process managers between supervisor and systemd
