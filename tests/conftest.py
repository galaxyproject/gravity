import os
import signal
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml
from gravity import config_manager

GALAXY_BRANCH = os.environ.get("GRAVITY_TEST_GALAXY_BRANCH", "dev")
TEST_DIR = Path(os.path.dirname(__file__))
GXIT_CONFIG = """
gravity:
  gunicorn:
    bind: 'localhost:{gx_port}'
  gx_it_proxy:
    enable: true
    port: {gxit_port}
    verbose: true
galaxy:
  conda_auto_init: false
  interactivetools_enable: true
  interactivetools_map: database/interactivetools_map.sqlite
  galaxy_infrastructure_url: http://localhost:{gx_port}
  interactivetools_upstream_proxy: false
  interactivetools_proxy_host: localhost:{gxit_port}
"""


@pytest.fixture(scope='session')
def galaxy_git_dir():
    galaxy_dir = TEST_DIR / 'galaxy.git'
    if not galaxy_dir.exists():
        subprocess.run(['git', 'clone', '--bare', '--depth=1', '--branch', GALAXY_BRANCH, 'https://github.com/galaxyproject/galaxy'], cwd=TEST_DIR)
    yield galaxy_dir


@pytest.fixture(scope='session')
def galaxy_root_dir(galaxy_git_dir, tmpdir_factory):
    tmpdir = tmpdir_factory.mktemp('galaxy-worktree')
    subprocess.run(['git', 'worktree', 'add', '-d', str(tmpdir)], cwd=str(galaxy_git_dir))
    return tmpdir


@pytest.fixture()
def galaxy_yml(galaxy_root_dir):
    config = galaxy_root_dir / 'config' / 'galaxy123.yml'
    sample_config = galaxy_root_dir / 'config' / 'galaxy.yml.sample'
    sample_config.copy(config)
    try:
        yield config
    finally:
        config.remove()


@pytest.fixture()
def state_dir():
    directory = tempfile.mkdtemp()
    try:
        yield Path(directory)
    finally:
        try:
            os.kill(int(open(os.path.join(directory, 'supervisor', 'supervisord.pid')).read()), signal.SIGTERM)
        except Exception:
            pass
        shutil.rmtree(directory)


@pytest.fixture
def default_config_manager(state_dir):
    with config_manager.config_manager(state_dir=state_dir) as cm:
        yield cm


@pytest.fixture()
def job_conf(request, galaxy_root_dir):
    conf = yaml.safe_load(request.param[0])
    ext = "xml" if isinstance(conf, str) else "yml"
    job_conf_path = galaxy_root_dir / 'config' / f'job_conf.{ext}'
    with open(job_conf_path, 'w') as jcfh:
        jcfh.write(request.param[0])
    yield job_conf_path
    os.unlink(job_conf_path)


@pytest.fixture()
def free_port():
    # Inspired by https://gist.github.com/bertjwregeer/0be94ced48383a42e70c3d9fff1f4ad0
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("localhost", 0))
    portnum = s.getsockname()[1]
    s.close()
    return portnum


another_free_port = free_port


@pytest.fixture()
def startup_config(galaxy_virtualenv, free_port):
    return {
        'gravity': {
            'virtualenv': galaxy_virtualenv,
            'gunicorn': {
                'bind': f'localhost:{free_port}'}
        },
        'galaxy': {
            'conda_auto_init': False
        }
    }


@pytest.fixture
def gxit_config(free_port, another_free_port):
    config_yaml = GXIT_CONFIG.format(gxit_port=another_free_port, gx_port=free_port)
    return yaml.safe_load(config_yaml)


@pytest.fixture
def tusd_config(startup_config, free_port, another_free_port):
    startup_config["gravity"] = {"tusd": {"enable": True, "port": another_free_port, "upload_dir": "/tmp"}}
    startup_config["galaxy"]["galaxy_infrastructure_url"] = f"http://localhost:{free_port}"
    return startup_config


@pytest.fixture
def gxit_startup_config(galaxy_virtualenv, gxit_config):
    gxit_config['gravity']['virtualenv'] = galaxy_virtualenv
    return gxit_config


@pytest.fixture(scope="session")
def galaxy_virtualenv(galaxy_root_dir):
    virtual_env_dir = str(TEST_DIR / "galaxy_venv")
    os.environ['GALAXY_VIRTUAL_ENV'] = virtual_env_dir
    subprocess.run(
        str(galaxy_root_dir / "scripts/common_startup.sh"),
        env={
            "GALAXY_SKIP_CLIENT_BUILD": "1",
            "GALAXY_VIRTUAL_ENV": virtual_env_dir},
        cwd=str(galaxy_root_dir)
    )
    return virtual_env_dir
