import json
from pathlib import Path

from gravity.defaults import (
    DEFAULT_GUNICORN_BIND,
    DEFAULT_GUNICORN_TIMEOUT,
    DEFAULT_GUNICORN_WORKERS,
    DEFAULT_INSTANCE_NAME,
    CELERY_DEFAULT_CONFIG

)


def test_register_defaults(galaxy_yml, galaxy_root_dir, state_dir, default_config_manager):
    default_config_manager.add([str(galaxy_yml)])
    assert str(galaxy_yml) in default_config_manager.state['config_files']
    state = default_config_manager.state['config_files'][str(galaxy_yml)]
    assert state['config_type'] == 'galaxy'
    assert state['instance_name'] == DEFAULT_INSTANCE_NAME
    assert state['services'] == []
    attributes = state['attribs']
    assert attributes['app_server'] == 'gunicorn'
    assert Path(attributes['log_dir']) == Path(state_dir) / 'log'
    assert Path(attributes['galaxy_root']) == galaxy_root_dir
    gunicorn_attributes = attributes['gunicorn']
    assert gunicorn_attributes['bind'] == DEFAULT_GUNICORN_BIND
    assert gunicorn_attributes['workers'] == DEFAULT_GUNICORN_WORKERS
    assert gunicorn_attributes['timeout'] == DEFAULT_GUNICORN_TIMEOUT
    assert gunicorn_attributes['extra_args'] == ""
    assert attributes['celery'] == CELERY_DEFAULT_CONFIG


def test_register_non_default(galaxy_yml, default_config_manager):
    new_bind = 'localhost:8081'
    concurrency = 4
    galaxy_yml.write(json.dumps({
        'galaxy': None,
        'gravity': {
            'gunicorn': {
                'bind': new_bind
            },
            'celery': {
                'concurrency': concurrency
            }
        }
    }))
    default_config_manager.add([str(galaxy_yml)])
    state = default_config_manager.state['config_files'][str(galaxy_yml)]
    gunicorn_attributes = state['attribs']['gunicorn']
    assert gunicorn_attributes['bind'] == new_bind
    assert gunicorn_attributes['workers'] == DEFAULT_GUNICORN_WORKERS
    celery_attributes = state['attribs']['celery']
    assert celery_attributes['concurrency'] == concurrency


def test_deregister(galaxy_yml, default_config_manager):
    default_config_manager.add([str(galaxy_yml)])
    assert str(galaxy_yml) in default_config_manager.state['config_files']
    assert default_config_manager.is_registered(str(galaxy_yml))
    default_config_manager.remove([str(galaxy_yml)])
    assert str(galaxy_yml) not in default_config_manager.state['config_files']
    assert not default_config_manager.is_registered(str(galaxy_yml))


def test_rename(galaxy_root_dir, state_dir, default_config_manager):
    galaxy_yml_sample = galaxy_root_dir / "config" / "galaxy.yml.sample"
    default_config_manager.add([str(galaxy_yml_sample)])
    galaxy_yml = galaxy_root_dir / "config" / "galaxy123.yml"
    galaxy_yml_sample.copy(galaxy_yml)
    assert default_config_manager.is_registered(str(galaxy_yml_sample.realpath()))
    assert not default_config_manager.is_registered(str(galaxy_yml))
    default_config_manager.rename(str(galaxy_yml_sample.realpath()), str(galaxy_yml))
    assert not default_config_manager.is_registered(str(galaxy_yml_sample.realpath()))
    assert default_config_manager.is_registered(str(galaxy_yml))


def test_auto_register(galaxy_yml, default_config_manager, monkeypatch):
    monkeypatch.setenv("GALAXY_CONFIG_FILE", str(galaxy_yml))
    assert not default_config_manager.is_registered(str(galaxy_yml))
    default_config_manager.auto_register()
    assert default_config_manager.is_registered(str(galaxy_yml))


def test_register_sample_update_to_non_sample(galaxy_root_dir, state_dir, default_config_manager):
    galaxy_yml_sample = galaxy_root_dir / "config" / "galaxy.yml.sample"
    default_config_manager.add([str(galaxy_yml_sample)])
    galaxy_yml = galaxy_root_dir / "config" / "galaxy.yml"
    galaxy_yml_sample.copy(galaxy_yml)
    default_config_manager.instance_count == 1
    assert default_config_manager.get_registered_config(str(galaxy_yml))
