import json
import re
from time import time
from click.testing import CliRunner

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


def wait_for_startup(state_dir):
    with open(state_dir / "log" / 'gunicorn.log') as fh:
        content = ""
        for _ in range(STARTUP_TIMEOUT * 4):
            content = f"{content}{fh.read()}"
            if "Application startup complete":
                return True
            else:
                time.sleep(0.25)
    return content


def test_cmd_start(state_dir, galaxy_yml, galaxy_virtualenv):
    galaxy_yml.write(json.dumps({'gravity': {'virtualenv': galaxy_virtualenv}, 'galaxy': {'conda_auto_init': False}}))
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'register', str(galaxy_yml)])
    assert result.exit_code == 0
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'update'])
    assert result.exit_code == 0
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'start'])
    assert re.search(r"gunicorn\s*STARTING", result.output)
    assert result.exit_code == 0
    startup_done = wait_for_startup(state_dir)
    assert startup_done is True, f"Startup failed. Application startup logs:\n {startup_done}"
    result = runner.invoke(galaxyctl, ['--state-dir', state_dir, 'stop'])
    assert result.exit_code == 0
