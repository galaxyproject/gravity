import os
import glob
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
  process_manager: {process_manager_name}
  service_command_style: direct
  instance_name: {instance_name}
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
  interactivetools_base_path: /
  interactivetools_prefix: interactivetool
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
def state_dir(monkeypatch):
    directory = tempfile.mkdtemp(prefix="gravity_test")
    unit_path = f"/run/user/{os.getuid()}/systemd/user"
    monkeypatch.setenv("GRAVITY_STATE_DIR", directory)
    monkeypatch.setenv("GRAVITY_SYSTEMD_UNIT_PATH", unit_path)
    try:
        yield Path(directory)
    finally:
        try:
            os.kill(int(open(os.path.join(directory, 'supervisor', 'supervisord.pid')).read()), signal.SIGTERM)
        except Exception:
            pass
        shutil.rmtree(directory)
        instance_name = os.path.basename(directory)
        unit_paths = glob.glob(os.path.join(unit_path, f"galaxy-{instance_name}*"))
        if unit_paths:
            units = list(map(os.path.basename, unit_paths))
            try:
                subprocess.check_call(["systemctl", "--user", "stop", *units])
                list(map(os.unlink, unit_paths))
                subprocess.check_call(["systemctl", "--user", "daemon-reload"])
            except Exception:
                subprocess.check_call(["systemctl", "--user", "list-units", "--all", "galaxy*"])
        try:
            # unfortunately these aren't created in /run
            os.unlink(os.path.expanduser(f"~/.config/systemd/user/multi-user.target.wants/galaxy-{instance_name}.target"))
        except Exception:
            pass


@pytest.fixture
def default_config_manager(state_dir):
    with config_manager.config_manager(state_dir=state_dir) as cm:
        yield cm


@pytest.fixture()
def job_conf(request, galaxy_root_dir):
    conf = yaml.safe_load(request.param)
    ext = "xml" if isinstance(conf, str) else "yml"
    job_conf_path = galaxy_root_dir / 'config' / f'job_conf.{ext}'
    with open(job_conf_path, 'w') as jcfh:
        jcfh.write(request.param)
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
def startup_config(state_dir, galaxy_virtualenv, free_port):
    return {
        'gravity': {
            'service_command_style': 'direct',
            'virtualenv': galaxy_virtualenv,
            'gunicorn': {
                'bind': f'localhost:{free_port}'}
        },
        'galaxy': {
            'conda_auto_init': False
        }
    }


@pytest.fixture()
def reports_config(galaxy_root_dir, galaxy_virtualenv, free_port):
    return {
        'gravity': {
            'service_command_style': 'direct',
            'virtualenv': galaxy_virtualenv,
            'gunicorn': {'enable': False},
            'celery': {
                'enable': False,
                'enable_beat': False,
            },
            'reports': {
                'enable': True,
                'bind': f'localhost:{free_port}',
                'config_file': str(galaxy_root_dir / "config" / "reports.yml.sample"),
            }
        }
    }


@pytest.fixture()
def non_default_config():
    return {
        'galaxy': None,
        'gravity': {
            'service_command_style': 'direct',
            'gunicorn': {
                'bind': 'localhost:8081',
                'environment': {'FOO': 'foo'}
            },
            'celery': {
                'concurrency': 4
            }
        }
    }


@pytest.fixture
def gxit_config(state_dir, free_port, another_free_port, process_manager_name):
    config_yaml = GXIT_CONFIG.format(
        gxit_port=another_free_port,
        gx_port=free_port,
        process_manager_name=process_manager_name,
        instance_name=os.path.basename(state_dir),
    )
    return yaml.safe_load(config_yaml)


@pytest.fixture
def tusd_config(state_dir, startup_config, free_port, another_free_port, process_manager_name):
    startup_config["gravity"] = {
        "process_manager": process_manager_name,
        "service_command_style": "direct",
        "instance_name": os.path.basename(state_dir),
        "tusd": {"enable": True, "port": another_free_port, "upload_dir": "/tmp"}}
    startup_config["galaxy"]["galaxy_infrastructure_url"] = f"http://localhost:{free_port}"
    return startup_config


@pytest.fixture
def gxit_startup_config(galaxy_virtualenv, gxit_config):
    gxit_config['gravity']['virtualenv'] = galaxy_virtualenv
    return gxit_config


@pytest.fixture
def tusd_startup_config(galaxy_virtualenv, tusd_config, free_port):
    tusd_config['gravity']['gunicorn'] = {'bind': f'localhost:{free_port}'}
    tusd_config['gravity']['virtualenv'] = galaxy_virtualenv
    return tusd_config


@pytest.fixture(scope="session")
def galaxy_virtualenv(galaxy_root_dir):
    virtual_env_dir = str(TEST_DIR / "galaxy_venv")
    os.environ['GALAXY_VIRTUAL_ENV'] = virtual_env_dir
    subprocess.run(
        str(galaxy_root_dir / "scripts/common_startup.sh"),
        env={
            "GALAXY_SKIP_CLIENT_BUILD": "1",
            "GALAXY_VIRTUAL_ENV": virtual_env_dir,
            "PATH": os.getenv("PATH"),
        },
        cwd=str(galaxy_root_dir)
    )
    return virtual_env_dir
