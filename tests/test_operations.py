import json
import os
import re
import time
from pathlib import Path

import pytest
import requests
from click.testing import CliRunner
from yaml import safe_load

from gravity.cli import galaxyctl
from gravity.state import CELERY_BEAT_DB_FILENAME

STARTUP_TIMEOUT = 30
CELERY_BEAT_TIMEOUT = 10
# celery.beat.PersistentScheduler uses shelve, which can append a suffix based on which db backend is used
CELERY_BEAT_DB_FILENAMES = map(lambda ext: CELERY_BEAT_DB_FILENAME + ext, ('', '.db', '.dat', '.bak', '.dir'))


def test_cmd_register(state_dir, galaxy_yml):
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'register', str(galaxy_yml)])
    assert result.exit_code == 0, result.output
    assert 'Registered galaxy config:' in result.output


def test_cmd_deregister(state_dir, galaxy_yml):
    test_cmd_register(state_dir, galaxy_yml)
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'deregister', str(galaxy_yml)])
    assert result.exit_code == 0, result.output
    assert 'Deregistered config:' in result.output


def wait_for_startup(state_dir, free_port, prefix="/"):
    for _ in range(STARTUP_TIMEOUT * 4):
        try:
            requests.get(f"http://localhost:{free_port}{prefix}api/version").raise_for_status()
            return True
        except Exception:
            time.sleep(0.25)
    with open(state_dir / "log" / 'gunicorn.log') as fh:
        startup_logs = fh.read()
    return startup_logs


def wait_for_gxit_proxy(state_dir):
    startup_logs = ""
    with open(state_dir / "log" / 'gx-it-proxy.log') as fh:
        for _ in range(STARTUP_TIMEOUT * 4):
            startup_logs = f"{startup_logs}{fh.read()}"
            if 'Watching path' in startup_logs:
                return True
            time.sleep(0.25)
    return startup_logs


def wait_for_any_path(paths, timeout):
    for _ in range(timeout * 4):
        try:
            assert any(map(lambda x: x.exists(), paths))
            return True
        except AssertionError:
            time.sleep(0.25)
    return False


def start_instance(state_dir, free_port):
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'start'])
    assert re.search(r"gunicorn\s*STARTING", result.output)
    assert result.exit_code == 0, result.output
    startup_done = wait_for_startup(state_dir, free_port)
    assert startup_done is True, f"Startup failed. Application startup logs:\n {startup_done}"


def test_cmd_start(state_dir, galaxy_yml, startup_config, free_port):
    galaxy_yml.write(json.dumps(startup_config))
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'register', str(galaxy_yml)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'update'])
    assert result.exit_code == 0, result.output
    start_instance(state_dir, free_port)
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'status'])
    celery_beat_db_paths = map(lambda f: state_dir / f, CELERY_BEAT_DB_FILENAMES)
    celery_beat_db_exists = wait_for_any_path(celery_beat_db_paths, CELERY_BEAT_TIMEOUT)
    assert celery_beat_db_exists is True, "celery-beat failed to write db. State dir contents:\n" \
        f"{os.listdir(state_dir)}"
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'stop'])
    assert result.exit_code == 0, result.output
    assert "All processes stopped, supervisord will exit" in result.output


@pytest.mark.parametrize('process_manager_name', ['supervisor'])
def test_cmd_start_with_gxit(state_dir, galaxy_yml, gxit_startup_config, free_port, process_manager_name):
    galaxy_yml.write(json.dumps(gxit_startup_config))
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'register', str(galaxy_yml)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'update'])
    assert result.exit_code == 0, result.output
    start_instance(state_dir, free_port)
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'status'])
    assert result.exit_code == 0, f"{result.output}\ngx-it-proxy startup failed. " \
        f"gx-it-proxy startup logs:\n{open(state_dir / 'log' / 'gx-it-proxy.log').read()}"
    startup_done = wait_for_gxit_proxy(state_dir)
    assert startup_done is True, f"gx-it-proxy startup failed. gx-it-proxy startup logs:\n {startup_done}"


def test_cmd_restart_with_update(state_dir, galaxy_yml, startup_config, free_port):
    galaxy_yml.write(json.dumps(startup_config))
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'register', str(galaxy_yml)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'update'])
    assert result.exit_code == 0, result.output
    start_instance(state_dir, free_port)
    # change prefix
    prefix = '/galaxypf/'
    startup_config['galaxy']['galaxy_url_prefix'] = prefix
    galaxy_yml.write(json.dumps(startup_config))
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'restart'])
    assert result.exit_code == 0, result.output
    startup_done = wait_for_startup(state_dir=state_dir, free_port=free_port, prefix=prefix)
    assert startup_done is True, f"Startup failed. Application startup logs:\n {startup_done}"


def test_cmd_update_with_0_x_config(state_dir, configstate_yaml_0_x):
    runner = CliRunner()
    configstate_yaml = state_dir / "configstate.yaml"
    open(configstate_yaml, "w").write(configstate_yaml_0_x)
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'update'])
    assert result.exit_code == 0, result.output
    assert "Converting Gravity config state to 1.0 format" in result.output
    assert "Adding service gunicorn" in result.output
    assert "Adding service celery" in result.output
    assert "Adding service celery-beat" in result.output


def test_cmd_show(state_dir, galaxy_yml):
    test_cmd_register(state_dir, galaxy_yml)
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'show', str(galaxy_yml)])
    assert result.exit_code == 0, result.output
    details = safe_load(result.output)
    assert details['config_type'] == 'galaxy'


def test_cmd_show_config_does_not_exist(state_dir, galaxy_yml):
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'show', str(galaxy_yml)])
    assert result.exit_code == 1
    assert f"{str(galaxy_yml)} is not a registered config file." in result.output
    assert "No config files have been registered." in result.output
    assert "Registered config files are:" not in result.output
    assert f'To register this config file run "galaxyctl register {str(galaxy_yml)}"' in result.output
    # register the sample file, but ask for galaxy.yml
    sample_file = Path(galaxy_yml).parent / 'galaxy.yml.sample'
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'register', str(sample_file)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'show', str(galaxy_yml)])
    assert result.exit_code == 1
    assert f"{str(galaxy_yml)} is not a registered config file." in result.output
    assert "Registered config files are:" in result.output
    assert f'To register this config file run "galaxyctl register {str(galaxy_yml)}"'


def test_cmd_instances(state_dir, galaxy_yml):
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'instances'])
    assert result.exit_code == 0, result.output
    assert not result.output
    test_cmd_register(state_dir, galaxy_yml)
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'instances'])
    assert result.exit_code == 0, result.output
    assert "_default_" in result.output


def test_cmd_configs(state_dir, galaxy_yml):
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'configs'])
    assert result.exit_code == 0, result.output
    assert 'No config files registered' in result.output
    test_cmd_register(state_dir, galaxy_yml)
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'configs'])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("TYPE")
    assert str(galaxy_yml) in result.output
