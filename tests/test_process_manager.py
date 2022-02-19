import json
from pathlib import Path

import pytest
from gravity import process_manager


JOB_CONF_XML_STATIC_HANDLERS = """
<job_conf>
    <handlers>
        <handler id="handler0"/>
        <handler id="handler1"/>
    </handlers>
</job_conf>
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
        - job-handler
        - workflow-scheduler
    handler1:
      processes: 1
      pools:
        - job-handler.special
    handler2:
      processes: 1
      pools:
        - job-handler
        - job-handler.special
"""


def test_update(galaxy_yml, default_config_manager):
    default_config_manager.add([str(galaxy_yml)])
    new_bind = 'localhost:8081'
    galaxy_yml.write(json.dumps({'galaxy': None, 'gravity': {'gunicorn': {'bind': new_bind}}}))
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()


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
        assert " --attach-to-pool=job-handler --attach-to-pool=workflow-scheduler" in handler0_config
        handler1_config = handler_config_paths[1].open().read()
        assert " --server-name=handler1" in handler1_config
        assert " --attach-to-pool=job-handler.special" in handler1_config
        handler2_config = handler_config_paths[2].open().read()
        assert " --server-name=handler2" in handler2_config
        assert " --attach-to-pool=job-handler --attach-to-pool=job-handler.special" in handler2_config


@pytest.mark.parametrize('job_conf', [[JOB_CONF_XML_NO_HANDLERS]], indirect=True)
def test_no_static_handlers(default_config_manager, galaxy_yml, job_conf):
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        instance_conf_dir = Path(default_config_manager.state_dir) / 'supervisor' / 'supervisord.conf.d' / '_default_.d'
        assert not (instance_conf_dir / 'galaxy_standalone_handler0.conf').exists()


@pytest.mark.parametrize('job_conf', [[JOB_CONF_XML_STATIC_HANDLERS]], indirect=True)
def test_static_handlers(default_config_manager, galaxy_yml, job_conf):
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        instance_conf_dir = Path(default_config_manager.state_dir) / 'supervisor' / 'supervisord.conf.d' / '_default_.d'
        handler0_config_path = instance_conf_dir / 'galaxy_standalone_handler0.conf'
        assert handler0_config_path.exists()
        assert 'galaxy.yml --server-name=handler0 --pid-file=' in handler0_config_path.open().read()
        handler1_config_path = instance_conf_dir / 'galaxy_standalone_handler1.conf'
        assert handler1_config_path.exists()
        assert 'galaxy.yml --server-name=handler1 --pid-file=' in handler1_config_path.open().read()
