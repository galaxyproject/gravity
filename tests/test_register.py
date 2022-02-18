import os.path

import pytest

from gravity import (
    config_manager,
    process_manager,
)


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


def test_register(galaxy_root_dir, state_dir):
    config = galaxy_root_dir / 'config' / 'galaxy.yml.sample'
    with config_manager.config_manager(state_dir=state_dir) as cm:
        cm.add([str(config)])


def test_update(galaxy_root_dir, state_dir):
    config = galaxy_root_dir / 'config' / 'galaxy.yml.sample'
    with config_manager.config_manager(state_dir=state_dir) as cm:
        cm.add([str(config)])
    with process_manager.process_manager(state_dir=state_dir) as pm:
        pm.update()


def test_deregister(galaxy_root_dir, state_dir):
    config = galaxy_root_dir / 'config' / 'galaxy.yml.sample'
    test_register(galaxy_root_dir, state_dir)
    with config_manager.config_manager(state_dir=state_dir) as cm:
        cm.remove([str(config)])


@pytest.mark.parametrize('job_conf', [[JOB_CONF_XML_NO_HANDLERS]], indirect=True)
def test_no_static_handlers(galaxy_root_dir, state_dir, job_conf):
    test_register(galaxy_root_dir, state_dir)
    with process_manager.process_manager(state_dir=state_dir) as pm:
        pm.update()


@pytest.mark.parametrize('job_conf', [[JOB_CONF_XML_STATIC_HANDLERS]], indirect=True)
def test_static_handlers(galaxy_root_dir, state_dir, job_conf):
    test_register(galaxy_root_dir, state_dir)
    with process_manager.process_manager(state_dir=state_dir) as pm:
        pm.update()
        instance_conf_dir = state_dir / 'supervisor' / 'supervisord.conf.d' / '_default_.d'
        assert os.path.exists(instance_conf_dir / 'galaxy_standalone_handler0.conf')
        assert os.path.exists(instance_conf_dir / 'galaxy_standalone_handler1.conf')
