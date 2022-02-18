import json
from pathlib import Path

from gravity.defaults import (
    DEFAULT_GUNICORN_BIND,
    DEFAULT_GUNICORN_TIMEOUT,
    DEFAULT_GUNICORN_WORKERS,
    DEFAULT_INSTANCE_NAME,

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


def test_register_bind(galaxy_yml, default_config_manager):
    new_bind = 'localhost:8081'
    galaxy_yml.write(json.dumps({'galaxy': None, 'gravity': {'gunicorn': {'bind': new_bind}}}))
    default_config_manager.add([str(galaxy_yml)])
    state = default_config_manager.state['config_files'][str(galaxy_yml)]
    gunicorn_attributes = state['attribs']['gunicorn']
    assert gunicorn_attributes['bind'] == new_bind
    assert gunicorn_attributes['workers'] == DEFAULT_GUNICORN_WORKERS


def test_deregister(galaxy_yml, default_config_manager):
    default_config_manager.add([str(galaxy_yml)])
    assert str(galaxy_yml) in default_config_manager.state['config_files']
    default_config_manager.remove([str(galaxy_yml)])
    assert str(galaxy_yml) not in default_config_manager.state['config_files']
