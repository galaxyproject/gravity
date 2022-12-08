import json
from pathlib import Path

import pytest
from gravity import process_manager
from gravity.state import GracefulMethod
from yaml import safe_load


JOB_CONF_XML_STATIC_HANDLERS = """
<job_conf>
    <handlers>
        <handler id="handler0"/>
        <handler id="handler1"/>
    </handlers>
</job_conf>
"""

# example from job_conf.sample_advanced.yml
JOB_CONF_YAML_STATIC_HANDLERS = """
handling:
  processes:
    handler0:
    handler1:
      environment:
        BAZ: baz
    sge_handler:
      # Restrict a handler to load specific runners, by default they will load all.
      plugins: ['sge']
    special_handler0:
      tags: [special_handlers]
    special_handler1:
      tags: [special_handlers]
"""

JOB_CONF_YAML_NO_HANDLERS = """
---
handling:
  assign:
    - db-skip-locked
"""

JOB_CONF_XML_NO_HANDLERS = """
<job_conf>
</job_conf>
"""

JOB_CONF_XML_DYNAMIC_HANDLERS = """
<job_conf>
    <handlers assign_with="db-skip-locked"/>
</job_conf>
"""

DYNAMIC_HANDLER_CONFIG = """
gravity:
  handlers:
    handler:
      processes: 2
      name_template: >
        {name}{process}
      pools:
        - job-handlers
        - workflow-schedulers
      environment:
        FOO: foo
    handler1:
      processes: 1
      pools:
        - job-handlers.special
      environment:
        BAR: bar
    handler2:
      processes: 1
      pools:
        - job-handlers
        - job-handlers.special
"""


def test_update(galaxy_yml, default_config_manager):
    default_config_manager.add([str(galaxy_yml)])
    new_bind = 'localhost:8081'
    galaxy_yml.write(json.dumps({'galaxy': None, 'gravity': {'gunicorn': {'bind': new_bind}}}))
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()


def test_update_force(galaxy_yml, default_config_manager):
    test_update(galaxy_yml, default_config_manager)
    instance_conf_dir = Path(default_config_manager.state_dir) / 'supervisor' / 'supervisord.conf.d' / '_default_.d'
    gunicorn_conf_path = instance_conf_dir / "galaxy_gunicorn_gunicorn.conf"
    assert gunicorn_conf_path.exists()
    update_time = gunicorn_conf_path.stat().st_mtime
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
    assert gunicorn_conf_path.stat().st_mtime == update_time
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update(force=True)
    assert gunicorn_conf_path.stat().st_mtime != update_time


def test_disable_services(galaxy_yml, default_config_manager):
    default_config_manager.add([str(galaxy_yml)])
    galaxy_yml.write(json.dumps(
        {'galaxy': None, 'gravity': {
            'gunicorn': {'enable': False},
            'celery': {'enable': False, 'enable_beat': False}}}
    ))
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
    instance_conf_dir = Path(default_config_manager.state_dir) / 'supervisor' / 'supervisord.conf.d' / '_default_.d'
    gunicorn_conf_path = instance_conf_dir / "galaxy_gunicorn_gunicorn.conf"
    assert not gunicorn_conf_path.exists()
    celery_conf_path = instance_conf_dir / "galaxy_celery_celery.conf"
    assert not celery_conf_path.exists()
    celery_beat_conf_path = instance_conf_dir / "galaxy_celery-beat_celery-beat.conf"
    assert not celery_beat_conf_path.exists()


def test_gunicorn_graceful_method_preload(galaxy_yml, default_config_manager):
    instance_name = '_default_'
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
    config = default_config_manager.get_instance_config(instance_name)
    services = default_config_manager.get_instance_services(instance_name)
    gunicorn_service = [s for s in services if s["service_name"] == "gunicorn"][0]
    graceful_method = gunicorn_service.get_graceful_method(config["attribs"])
    assert graceful_method == GracefulMethod.DEFAULT


def test_gunicorn_graceful_method_no_preload(galaxy_yml, default_config_manager):
    instance_name = '_default_'
    default_config_manager.add([str(galaxy_yml)])
    galaxy_yml.write(json.dumps(
        {'galaxy': None, 'gravity': {
            'gunicorn': {'preload': False}}}
    ))
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
    config = default_config_manager.get_instance_config(instance_name)
    services = default_config_manager.get_instance_services(instance_name)
    gunicorn_service = [s for s in services if s["service_name"] == "gunicorn"][0]
    graceful_method = gunicorn_service.get_graceful_method(config["attribs"])
    assert graceful_method == GracefulMethod.SIGHUP


@pytest.mark.parametrize('job_conf', [[JOB_CONF_XML_DYNAMIC_HANDLERS]], indirect=True)
def test_dynamic_handlers(default_config_manager, galaxy_yml, job_conf):
    galaxy_yml.write(DYNAMIC_HANDLER_CONFIG)
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        instance_conf_dir = Path(default_config_manager.state_dir) / 'supervisor' / 'supervisord.conf.d' / '_default_.d'
        handler_config_paths = [instance_conf_dir / f'galaxy_standalone_handler{i}.conf' for i in range(3)]
        for config_path in handler_config_paths:
            assert config_path.exists()
        handler0_config = handler_config_paths[0].open().read()
        assert " --server-name=handler0" in handler0_config
        assert " --attach-to-pool=job-handlers --attach-to-pool=workflow-schedulers" in handler0_config
        assert " FOO=foo" in handler0_config
        handler1_config = handler_config_paths[1].open().read()
        assert " --server-name=handler1" in handler1_config
        assert " --attach-to-pool=job-handlers.special" in handler1_config
        assert " BAR=bar" in handler1_config
        handler2_config = handler_config_paths[2].open().read()
        assert " --server-name=handler2" in handler2_config
        assert " --attach-to-pool=job-handlers --attach-to-pool=job-handlers.special" in handler2_config


@pytest.mark.parametrize('job_conf', [[JOB_CONF_YAML_NO_HANDLERS]], indirect=True)
def test_no_static_handlers_yaml(default_config_manager, galaxy_yml, job_conf):
    with open(galaxy_yml, 'w') as config_fh:
        config_fh.write(json.dumps({'galaxy': {'job_config_file': str(job_conf)}}))
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        instance_conf_dir = Path(default_config_manager.state_dir) / 'supervisor' / 'supervisord.conf.d' / '_default_.d'
        assert not (instance_conf_dir / 'galaxy_standalone_handler0.conf').exists()


@pytest.mark.parametrize('job_conf', [[JOB_CONF_XML_NO_HANDLERS]], indirect=True)
def test_no_static_handlers_xml(default_config_manager, galaxy_yml, job_conf):
    with open(galaxy_yml, 'w') as config_fh:
        config_fh.write(json.dumps({'galaxy': {'job_config_file': str(job_conf)}}))
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        instance_conf_dir = Path(default_config_manager.state_dir) / 'supervisor' / 'supervisord.conf.d' / '_default_.d'
        assert not (instance_conf_dir / 'galaxy_standalone_handler0.conf').exists()


@pytest.mark.parametrize('job_conf', [[JOB_CONF_YAML_STATIC_HANDLERS]], indirect=True)
def test_static_handlers_yaml(default_config_manager, galaxy_yml, job_conf):
    with open(galaxy_yml, 'w') as config_fh:
        config_fh.write(json.dumps({'galaxy': {'job_config_file': str(job_conf)}}))
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        instance_conf_dir = Path(default_config_manager.state_dir) / 'supervisor' / 'supervisord.conf.d' / '_default_.d'
        handler0_config_path = instance_conf_dir / 'galaxy_standalone_handler0.conf'
        assert handler0_config_path.exists()
        assert '.yml --server-name=handler0 --pid-file=' in handler0_config_path.open().read()
        handler1_config_path = instance_conf_dir / 'galaxy_standalone_handler1.conf'
        assert handler1_config_path.exists()
        handler1_config = handler1_config_path.open().read()
        assert '.yml --server-name=handler1 --pid-file=' in handler1_config
        assert 'BAZ=baz' in handler1_config
        assert (instance_conf_dir / 'galaxy_standalone_sge_handler.conf').exists()
        assert (instance_conf_dir / 'galaxy_standalone_special_handler0.conf').exists()
        assert (instance_conf_dir / 'galaxy_standalone_special_handler1.conf').exists()


def test_static_handlers_embedded_in_galaxy_yml(default_config_manager, galaxy_yml):
    with open(galaxy_yml, 'w') as config_fh:
        config_fh.write(json.dumps({'galaxy': {'job_config': safe_load(JOB_CONF_YAML_STATIC_HANDLERS)}}))
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        instance_conf_dir = Path(default_config_manager.state_dir) / 'supervisor' / 'supervisord.conf.d' / '_default_.d'
        handler0_config_path = instance_conf_dir / 'galaxy_standalone_handler0.conf'
        assert handler0_config_path.exists()
        assert '.yml --server-name=handler0 --pid-file=' in handler0_config_path.open().read()
        handler1_config_path = instance_conf_dir / 'galaxy_standalone_handler1.conf'
        assert handler1_config_path.exists()
        assert '.yml --server-name=handler1 --pid-file=' in handler1_config_path.open().read()
        assert (instance_conf_dir / 'galaxy_standalone_sge_handler.conf').exists()
        assert (instance_conf_dir / 'galaxy_standalone_special_handler0.conf').exists()
        assert (instance_conf_dir / 'galaxy_standalone_special_handler1.conf').exists()


@pytest.mark.parametrize('job_conf', [[JOB_CONF_XML_STATIC_HANDLERS]], indirect=True)
def test_static_handlers(default_config_manager, galaxy_yml, job_conf):
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        instance_conf_dir = Path(default_config_manager.state_dir) / 'supervisor' / 'supervisord.conf.d' / '_default_.d'
        handler0_config_path = instance_conf_dir / 'galaxy_standalone_handler0.conf'
        assert handler0_config_path.exists()
        assert f'{str(galaxy_yml)} --server-name=handler0 --pid-file=' in handler0_config_path.open().read()
        handler1_config_path = instance_conf_dir / 'galaxy_standalone_handler1.conf'
        assert handler1_config_path.exists()
        assert f'{str(galaxy_yml)} --server-name=handler1 --pid-file=' in handler1_config_path.open().read()


def test_gxit_handler(default_config_manager, galaxy_yml, gxit_config):
    galaxy_yml.write(json.dumps(gxit_config))
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        instance_conf_dir = Path(default_config_manager.state_dir) / 'supervisor' / 'supervisord.conf.d' / '_default_.d'
        gxit_config_path = instance_conf_dir / 'galaxy_gx-it-proxy_gx-it-proxy.conf'
        assert gxit_config_path.exists()
        gxit_port = gxit_config["gravity"]["gx_it_proxy"]["port"]
        gxit_base_path = gxit_config["galaxy"]["interactivetools_base_path"]
        gxit_prefix = gxit_config["galaxy"]["interactivetools_prefix"]
        sessions = "database/interactivetools_map.sqlite"
        proxy_path_prefix = f'{gxit_base_path}{gxit_prefix}/access/interactivetoolentrypoint'
        assert f'npx gx-it-proxy --ip localhost --port {gxit_port} --sessions {sessions} --proxyPathPrefix {proxy_path_prefix}' in gxit_config_path.read_text()


def test_tusd_process(default_config_manager, galaxy_yml, tusd_config):
    galaxy_yml.write(json.dumps(tusd_config))
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        instance_conf_dir = Path(default_config_manager.state_dir) / 'supervisor' / 'supervisord.conf.d' / '_default_.d'
        tusd_config_path = instance_conf_dir / 'galaxy_tusd_tusd.conf'
        assert tusd_config_path.exists()
        assert "tusd -host" in tusd_config_path.read_text()
