import json
import os
import string
from pathlib import Path

import pytest
from gravity import process_manager
from yaml import safe_load


JOB_CONF_XML_STATIC_HANDLERS = """
<job_conf>
    <handlers>
        <handler id="handler0"/>
        <handler id="handler1"/>
        <handler id="sge_handler">
            <plugin id="sge"/>
        </handler>
        <handler id="special_handler0" tags="special_handlers"/>
        <handler id="special_handler1" tags="special_handlers"/>
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
  process_manager: %(process_manager_name)s
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


# make pytest.params out of constants
params = {}
for name in [n for n in dir() if all([(c in string.ascii_uppercase + '_') for c in n])]:
    params[name] = pytest.param(globals()[name], id=name.lower())


def service_conf_dir(state_dir, process_manager_name):
    state_dir = Path(state_dir)
    if process_manager_name == 'supervisor':
        return state_dir / 'supervisor' / 'supervisord.conf.d' / '_default_.d'
    elif process_manager_name == 'systemd':
        return Path(os.environ.get('GRAVITY_SYSTEMD_UNIT_PATH'))
    raise Exception(f"Invalid process manager name: {process_manager_name}")


def service_conf_file(process_manager_name, service_name, service_type=None):
    service_type = service_type or service_name
    if process_manager_name == 'supervisor':
        return f'galaxy_{service_type}_{service_name}.conf'
    elif process_manager_name == 'systemd':
        return f'galaxy-{service_name}.service'
    raise Exception(f"Invalid process manager name: {process_manager_name}")


def service_conf_path(state_dir, process_manager_name, service_name, service_type=None):
    conf_dir = service_conf_dir(state_dir, process_manager_name)
    conf_file = service_conf_file(process_manager_name, service_name, service_type)
    return conf_dir / conf_file


@pytest.mark.parametrize('process_manager_name', ['supervisor', 'systemd'])
def test_update(galaxy_yml, default_config_manager, process_manager_name):
    default_config_manager.add([str(galaxy_yml)])
    new_bind = 'localhost:8081'
    galaxy_yml.write(json.dumps(
        {'galaxy': None, 'gravity': {'process_manager': process_manager_name, 'gunicorn': {'bind': new_bind}}}))
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()


@pytest.mark.parametrize('process_manager_name', ['supervisor', 'systemd'])
def test_update_default_services(galaxy_yml, default_config_manager, process_manager_name):
    test_update(galaxy_yml, default_config_manager, process_manager_name)
    conf_dir = service_conf_dir(default_config_manager.state_dir, process_manager_name)
    gunicorn_conf_path = service_conf_path(default_config_manager.state_dir, process_manager_name, 'gunicorn')
    assert gunicorn_conf_path.exists()
    celery_conf_path = conf_dir / service_conf_file(process_manager_name, 'celery')
    assert celery_conf_path.exists()
    celery_beat_conf_path = conf_dir / service_conf_file(process_manager_name, 'celery-beat')
    assert celery_beat_conf_path.exists()


@pytest.mark.parametrize('process_manager_name', ['supervisor', 'systemd'])
def test_update_force(galaxy_yml, default_config_manager, process_manager_name):
    test_update(galaxy_yml, default_config_manager, process_manager_name)
    gunicorn_conf_path = service_conf_path(default_config_manager.state_dir, process_manager_name, 'gunicorn')
    assert gunicorn_conf_path.exists()
    update_time = gunicorn_conf_path.stat().st_mtime
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
    assert gunicorn_conf_path.stat().st_mtime == update_time
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update(force=True)
    assert gunicorn_conf_path.stat().st_mtime != update_time


@pytest.mark.parametrize('process_manager_name', ['supervisor', 'systemd'])
def test_cleanup(galaxy_yml, default_config_manager, process_manager_name):
    test_update(galaxy_yml, default_config_manager, process_manager_name)
    gunicorn_conf_path = service_conf_path(default_config_manager.state_dir, process_manager_name, 'gunicorn')
    celery_conf_path = service_conf_path(default_config_manager.state_dir, process_manager_name, 'celery')
    celery_beat_conf_path = service_conf_path(default_config_manager.state_dir, process_manager_name, 'celery-beat')
    default_config_manager.remove([str(galaxy_yml)])
    assert gunicorn_conf_path.exists()
    assert celery_conf_path.exists()
    assert celery_beat_conf_path.exists()
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
    assert not gunicorn_conf_path.exists()
    assert not celery_conf_path.exists()
    assert not celery_beat_conf_path.exists()


@pytest.mark.parametrize('process_manager_name', ['supervisor', 'systemd'])
def test_disable_services(galaxy_yml, default_config_manager, process_manager_name):
    default_config_manager.add([str(galaxy_yml)])
    galaxy_yml.write(json.dumps(
        {'galaxy': None, 'gravity': {
            'process_manager': process_manager_name,
            'gunicorn': {'enable': False},
            'celery': {'enable': False, 'enable_beat': False}}}
    ))
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
    conf_dir = service_conf_dir(default_config_manager.state_dir, process_manager_name)
    gunicorn_conf_path = conf_dir / service_conf_file(process_manager_name, 'gunicorn')
    assert not gunicorn_conf_path.exists()
    celery_conf_path = conf_dir / service_conf_file(process_manager_name, 'celery')
    assert not celery_conf_path.exists()
    celery_beat_conf_path = conf_dir / service_conf_file(process_manager_name, 'celery-beat')
    assert not celery_beat_conf_path.exists()


@pytest.mark.parametrize('job_conf', [params["JOB_CONF_XML_DYNAMIC_HANDLERS"]], indirect=True)
@pytest.mark.parametrize('process_manager_name', ['supervisor', 'systemd'])
def test_dynamic_handlers(default_config_manager, galaxy_yml, job_conf, process_manager_name):
    galaxy_yml.write(DYNAMIC_HANDLER_CONFIG % {"process_manager_name": process_manager_name})
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        conf_dir = service_conf_dir(default_config_manager.state_dir, process_manager_name)
        handler_config_paths = [conf_dir / service_conf_file(
            process_manager_name, f'handler{i}', service_type='standalone') for i in range(3)]
        for config_path in handler_config_paths:
            assert config_path.exists()
        handler0_config = handler_config_paths[0].open().read()
        assert " --server-name=handler0" in handler0_config
        assert " --attach-to-pool=job-handlers --attach-to-pool=workflow-schedulers" in handler0_config
        assert "FOO=foo" in handler0_config
        handler1_config = handler_config_paths[1].open().read()
        assert " --server-name=handler1" in handler1_config
        assert " --attach-to-pool=job-handlers.special" in handler1_config
        assert "BAR=bar" in handler1_config
        handler2_config = handler_config_paths[2].open().read()
        assert " --server-name=handler2" in handler2_config
        assert " --attach-to-pool=job-handlers --attach-to-pool=job-handlers.special" in handler2_config


@pytest.mark.parametrize(
    'job_conf', [params["JOB_CONF_YAML_NO_HANDLERS"], params["JOB_CONF_XML_NO_HANDLERS"]], indirect=True)
@pytest.mark.parametrize('process_manager_name', ['supervisor', 'systemd'])
def test_no_static_handlers(default_config_manager, galaxy_yml, job_conf, process_manager_name):
    with open(galaxy_yml, 'w') as config_fh:
        config_fh.write(json.dumps({
            'gravity': {'process_manager': process_manager_name},
            'galaxy': {'job_config_file': str(job_conf)}}))
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        handler_config_path = service_conf_path(
            default_config_manager.state_dir,
            process_manager_name, 'handler0', service_type='standalone')
        assert not handler_config_path.exists()


@pytest.mark.parametrize(
    'job_conf', [params["JOB_CONF_YAML_STATIC_HANDLERS"], params["JOB_CONF_XML_STATIC_HANDLERS"]], indirect=True)
@pytest.mark.parametrize('process_manager_name', ['supervisor', 'systemd'])
def test_static_handlers(default_config_manager, galaxy_yml, job_conf, process_manager_name):
    with open(galaxy_yml, 'w') as config_fh:
        config_fh.write(json.dumps({
            'gravity': {'process_manager': process_manager_name},
            'galaxy': {'job_config_file': str(job_conf)}}))
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        conf_dir = service_conf_dir(default_config_manager.state_dir, process_manager_name)
        handler0_config_path = conf_dir / service_conf_file(process_manager_name, 'handler0', service_type='standalone')
        assert handler0_config_path.exists()
        assert '.yml --server-name=handler0' in handler0_config_path.open().read()
        handler1_config_path = conf_dir / service_conf_file(process_manager_name, 'handler1', service_type='standalone')
        assert handler1_config_path.exists()
        handler1_config = handler1_config_path.open().read()
        assert '.yml --server-name=handler1' in handler1_config
        if job_conf.ext == '.yml':
            # setting env vars on static handlers is only supported with YAML job conf
            assert 'BAZ=baz' in handler1_config
        for handler_name in ('sge_handler', 'special_handler0', 'special_handler1'):
            assert (conf_dir / service_conf_file(process_manager_name, handler_name, service_type='standalone')).exists()


@pytest.mark.parametrize('process_manager_name', ['supervisor', 'systemd'])
def test_static_handlers_embedded_in_galaxy_yml(default_config_manager, galaxy_yml, process_manager_name):
    with open(galaxy_yml, 'w') as config_fh:
        config_fh.write(json.dumps({
            'gravity': {'process_manager': process_manager_name},
            'galaxy': {'job_config': safe_load(JOB_CONF_YAML_STATIC_HANDLERS)}}))
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        conf_dir = service_conf_dir(default_config_manager.state_dir, process_manager_name)
        handler0_config_path = conf_dir / service_conf_file(process_manager_name, 'handler0', service_type='standalone')
        assert handler0_config_path.exists()
        assert '.yml --server-name=handler0' in handler0_config_path.open().read()
        handler1_config_path = conf_dir / service_conf_file(process_manager_name, 'handler1', service_type='standalone')
        assert handler1_config_path.exists()
        assert '.yml --server-name=handler1' in handler1_config_path.open().read()
        for handler_name in ('sge_handler', 'special_handler0', 'special_handler1'):
            assert (conf_dir / service_conf_file(process_manager_name, handler_name, service_type='standalone')).exists()


@pytest.mark.parametrize('process_manager_name', ['supervisor', 'systemd'])
def test_gxit_handler(default_config_manager, galaxy_yml, gxit_config, process_manager_name):
    galaxy_yml.write(json.dumps(gxit_config))
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        gxit_config_path = service_conf_path(default_config_manager.state_dir, process_manager_name, 'gx-it-proxy')
        assert gxit_config_path.exists()
        gxit_port = gxit_config["gravity"]["gx_it_proxy"]["port"]
        sessions = "database/interactivetools_map.sqlite"
        assert f'npx gx-it-proxy --ip localhost --port {gxit_port} --sessions {sessions}' in gxit_config_path.read_text()


@pytest.mark.parametrize('process_manager_name', ['supervisor', 'systemd'])
def test_tusd_process(default_config_manager, galaxy_yml, tusd_config, process_manager_name):
    galaxy_yml.write(json.dumps(tusd_config))
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        tusd_config_path = service_conf_path(default_config_manager.state_dir, process_manager_name, 'tusd')
        assert tusd_config_path.exists()
        assert "tusd -host" in tusd_config_path.read_text()


# TODO: test switching PMs in between invocations, test multiple instances
