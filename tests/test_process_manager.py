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


def test_update(galaxy_yml, default_config_manager):
    default_config_manager.add([str(galaxy_yml)])
    new_bind = 'localhost:8081'
    galaxy_yml.write(json.dumps({'galaxy': None, 'gravity': {'gunicorn': {'bind': new_bind}}}))
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()


@pytest.mark.parametrize('job_conf', [[JOB_CONF_XML_NO_HANDLERS]], indirect=True)
def test_no_static_handlers(default_config_manager, galaxy_yml, job_conf):
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()


@pytest.mark.parametrize('job_conf', [[JOB_CONF_XML_STATIC_HANDLERS]], indirect=True)
def test_static_handlers(default_config_manager, galaxy_yml, job_conf):
    default_config_manager.add([str(galaxy_yml)])
    with process_manager.process_manager(state_dir=default_config_manager.state_dir) as pm:
        pm.update()
        instance_conf_dir = Path(default_config_manager.state_dir) / 'supervisor' / 'supervisord.conf.d' / '_default_.d'
        assert (instance_conf_dir / 'galaxy_standalone_handler0.conf').exists()
        assert (instance_conf_dir / 'galaxy_standalone_handler1.conf').exists()
