import json
from pathlib import Path

from gravity import __version__, config_manager
from gravity.settings import Settings


def test_register_defaults(galaxy_yml, galaxy_root_dir, state_dir, default_config_manager):
    default_config_manager.add([str(galaxy_yml)])
    assert str(galaxy_yml) in default_config_manager.state['config_files']
    config = default_config_manager.get_registered_config(str(galaxy_yml))
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
    default_config_manager.add([str(galaxy_yml)])
    config = default_config_manager.get_registered_config(str(galaxy_yml))
    gunicorn_attributes = config['attribs']['gunicorn']
    assert gunicorn_attributes['preload'] is False


def test_register_non_default(galaxy_yml, default_config_manager):
    new_bind = 'localhost:8081'
    environment = {'FOO': 'foo'}
    concurrency = 4
    galaxy_yml.write(json.dumps({
        'galaxy': None,
        'gravity': {
            'gunicorn': {
                'bind': new_bind,
                'environment': environment
            },
            'celery': {
                'concurrency': concurrency
            }
        }
    }))
    default_config_manager.add([str(galaxy_yml)])
    config = default_config_manager.get_registered_config(str(galaxy_yml))
    gunicorn_attributes = config['attribs']['gunicorn']
    assert gunicorn_attributes['bind'] == new_bind
    assert gunicorn_attributes['environment'] == environment
    default_settings = Settings()
    assert gunicorn_attributes['workers'] == default_settings.gunicorn.workers
    celery_attributes = config['attribs']['celery']
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


def test_convert_0_x_config(state_dir, galaxy_yml, configstate_yaml_0_x):
    configstate_yaml = state_dir / "configstate.yaml"
    open(configstate_yaml, "w").write(configstate_yaml_0_x)
    with config_manager.config_manager(state_dir=state_dir) as cm:
        assert cm.state.gravity_version == __version__
        config = cm.state.config_files[str(galaxy_yml)]
        assert config.config_type == "galaxy"
        assert config.instance_name == "gravity-0-x"
        assert "attribs" not in config


# TODO: tests for switching process managers between supervisor and systemd
