import json
import re
import time

import requests
from click.testing import CliRunner
from yaml import safe_load

from gravity.cli import galaxyctl

STARTUP_TIMEOUT = 20


def test_cmd_register(state_dir, galaxy_yml):
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'register', str(galaxy_yml)])
    assert result.exit_code == 0
    assert 'Registered galaxy config:' in result.output


def test_cmd_deregister(state_dir, galaxy_yml):
    test_cmd_register(state_dir, galaxy_yml)
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'deregister', str(galaxy_yml)])
    assert result.exit_code == 0
    assert 'Deregistered config:' in result.output


def wait_for_startup(state_dir, free_port):
    with open(state_dir / "log" / 'gunicorn.log') as fh:
        content = ""
        for _ in range(STARTUP_TIMEOUT * 4):
            content = f"{content}{fh.read()}"
            if "Application startup complete" in content:
                requests.get(f"http://localhost:{free_port}/api/version").raise_for_status()
                return True
            else:
                time.sleep(0.25)
    return content


def test_cmd_start(state_dir, galaxy_yml, startup_config, free_port):
    galaxy_yml.write(json.dumps(startup_config))
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'register', str(galaxy_yml)])
    assert result.exit_code == 0
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'update'])
    assert result.exit_code == 0
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'start'])
    assert re.search(r"gunicorn\s*STARTING", result.output)
    assert result.exit_code == 0
    startup_done = wait_for_startup(state_dir, free_port)
    assert startup_done is True, f"Startup failed. Application startup logs:\n {startup_done}"
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'stop'])
    assert result.exit_code == 0
    assert "All processes stopped, supervisord will exit" in result.output


def test_cmd_show(state_dir, galaxy_yml):
    test_cmd_register(state_dir, galaxy_yml)
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'show', str(galaxy_yml)])
    assert result.exit_code == 0
    details = safe_load(result.output)
    assert details['config_type'] == 'galaxy'


def test_cmd_configs(state_dir, galaxy_yml):
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'configs'])
    assert result.exit_code == 0
    assert 'No config files registered' in result.output
    test_cmd_register(state_dir, galaxy_yml)
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'configs'])
    assert result.exit_code == 0
    assert result.output.startswith("TYPE")
    assert str(galaxy_yml) in result.output
