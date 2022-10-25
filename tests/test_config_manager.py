import json
from pathlib import Path

import pytest

from gravity import config_manager
from gravity.settings import Settings
from gravity.state import GracefulMethod


def test_load_defaults(galaxy_yml, galaxy_root_dir, state_dir, default_config_manager):
    default_config_manager.load_config_file(str(galaxy_yml))
    config = default_config_manager.get_config()
    default_settings = Settings()
    assert config.config_type == 'galaxy'
    assert config.process_manager == 'supervisor'
    assert config.instance_name == default_settings.instance_name
    assert config.services != []
    assert config.app_server == 'gunicorn'
    assert Path(config.log_dir) == Path(state_dir) / 'log'
    assert Path(config.galaxy_root) == galaxy_root_dir
    gunicorn_settings = config.get_service('gunicorn').settings
    assert gunicorn_settings['bind'] == default_settings.gunicorn.bind
    assert gunicorn_settings['workers'] == default_settings.gunicorn.workers
    assert gunicorn_settings['timeout'] == default_settings.gunicorn.timeout
    assert gunicorn_settings['extra_args'] == default_settings.gunicorn.extra_args
    assert gunicorn_settings['preload'] is True
    celery_settings = config.get_service('celery').settings
    assert celery_settings == default_settings.celery.dict()
    with pytest.raises(IndexError):
        config.get_service('tusd')


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
    unicornherder_settings = config.get_service('unicornherder').settings
    assert unicornherder_settings['preload'] is False


def test_load_non_default(galaxy_yml, default_config_manager, non_default_config):
    if default_config_manager.instance_count == 0:
        galaxy_yml.write(json.dumps(non_default_config))
        default_config_manager.load_config_file(str(galaxy_yml))
    config = default_config_manager.get_config()
    gunicorn_settings = config.get_service('gunicorn').settings
    assert gunicorn_settings['bind'] == non_default_config['gravity']['gunicorn']['bind']
    assert gunicorn_settings['environment'] == non_default_config['gravity']['gunicorn']['environment']
    default_settings = Settings()
    assert gunicorn_settings['workers'] == default_settings.gunicorn.workers
    celery_settings = config.get_service('celery').settings
    assert celery_settings['concurrency'] == non_default_config['gravity']['celery']['concurrency']


def test_split_config(galaxy_yml, galaxy_root_dir, default_config_manager, non_default_config):
    default_config_file = str(galaxy_root_dir / "config" / "galaxy.yml.sample")
    non_default_config['gravity']['galaxy_config_file'] = default_config_file
    del non_default_config['galaxy']
    galaxy_yml.write(json.dumps(non_default_config))
    default_config_manager.load_config_file(str(galaxy_yml))
    test_load_non_default(galaxy_yml, default_config_manager, non_default_config)
    config = default_config_manager.get_config()
    assert config.gravity_config_file == str(galaxy_yml)
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
    graceful_method = config.get_service('gunicorn').graceful_method
    assert graceful_method == GracefulMethod.DEFAULT


def test_gunicorn_graceful_method_no_preload(galaxy_yml, default_config_manager):
    galaxy_yml.write(json.dumps(
        {'galaxy': None, 'gravity': {
            'gunicorn': {'preload': False}}}
    ))
    default_config_manager.load_config_file(str(galaxy_yml))
    config = default_config_manager.get_config()
    graceful_method = config.get_service('gunicorn').graceful_method
    assert graceful_method == GracefulMethod.SIGHUP


# TODO: tests for switching process managers between supervisor and systemd
