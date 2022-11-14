import json
import os
import re
import subprocess
import time

import pytest
import requests
from click.testing import CliRunner
from yaml import safe_load

from gravity.cli import galaxyctl
from gravity.state import CELERY_BEAT_DB_FILENAME

STARTUP_TIMEOUT = 30
CELERY_BEAT_TIMEOUT = 10
# celery.beat.PersistentScheduler uses shelve, which can append a suffix based on which db backend is used
CELERY_BEAT_DB_FILENAMES = list(map(lambda ext: CELERY_BEAT_DB_FILENAME + ext, ('', '.db', '.dat', '.bak', '.dir')))


def log_for_service(state_dir, process_manager_name, start_time, service_name, instance_name=None):
    if process_manager_name == "systemd":
        # instance_name should never be none in the systemd case
        log_name = f"galaxy-{instance_name}-{service_name}"
        cmd = f"journalctl --user --no-pager --since=@{start_time} --unit={log_name}.service".split()
        return subprocess.check_output(cmd, text=True)
    else:
        # could probably just glob here
        if instance_name is not None:
            log_name = f"{instance_name}_galaxy_{service_name}_{service_name}.log"
        else:
            log_name = f"{service_name}.log"
        path = state_dir / "log" / log_name
        with open(path) as fh:
            return fh.read()


def wait_for_startup(state_dir, free_port, prefix="/", path="/api/version", service_name="gunicorn",
                     process_manager_name="supervisor", start_time=None, instance_name=None):
    for _ in range(STARTUP_TIMEOUT * 4):
        try:
            requests.get(f"http://localhost:{free_port}{prefix.rstrip('/')}{path}").raise_for_status()
            return True, ""
        except Exception:
            time.sleep(0.25)
    return False, log_for_service(state_dir, process_manager_name, start_time, service_name, instance_name=instance_name)


def wait_for_gxit_proxy(state_dir, process_manager_name, start_time):
    instance_name = os.path.basename(state_dir)
    for _ in range(STARTUP_TIMEOUT * 4):
        startup_logs = log_for_service(state_dir, process_manager_name, start_time, service_name="gx-it-proxy", instance_name=instance_name)
        if 'Watching path' in startup_logs:
            return True, ""
        time.sleep(0.25)
    return False, startup_logs


def wait_for_any_path(paths, timeout):
    for _ in range(timeout * 4):
        try:
            assert any(map(lambda x: x.exists(), paths))
            return True
        except AssertionError:
            time.sleep(0.25)
    return False


def start_instance(state_dir, galaxy_yml, free_port, process_manager_name="supervisor", instance_name=None):
    runner = CliRunner()
    start_time = time.time()
    result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'start'])
    assert result.exit_code == 0, result.output
    if process_manager_name == "systemd":
        gunicorn_name = f"galaxy-{instance_name}-gunicorn"
        output = subprocess.check_output(f"systemctl --user status {gunicorn_name}.service".split(), text=True)
        assert f"● {gunicorn_name}.service" in output
    else:
        assert re.search(r"gunicorn\s*STARTING", result.output)
    startup_done, startup_logs = wait_for_startup(state_dir, free_port, process_manager_name=process_manager_name,
                                                  start_time=start_time, instance_name=instance_name)
    assert startup_done is True, f"Startup failed. Application startup logs:\n {startup_logs}"


def supervisor_service_pids(runner, galaxy_yml, instance_name):
    result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'status'])
    assert result.exit_code == 0, result.output
    start_time = time.time()
    while 'STARTING' in result.output:
        assert (time.time() - start_time) < STARTUP_TIMEOUT, result.output
        time.sleep(1)
        result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'status'])
        assert result.exit_code == 0, result.output
    pids = {}
    for line in result.output.splitlines():
        line_a = line.split()
        service = line_a[0].split(":")[-1]
        pids[service] = line_a[3].rstrip(",")
    return pids


def systemd_service_pids(runner, galaxy_yml, instance_name):
    pids = {}
    units = subprocess.check_output(f"systemctl --user list-units --plain --no-legend galaxy-{instance_name}-*".split(), text=True)
    for unit_line in units.splitlines():
        assert 'active' in unit_line, unit_line
        assert 'running' in unit_line, unit_line
        unit = unit_line.split()[0]
        output = subprocess.check_output(f"systemctl --user show --property=MainPID {unit}".split(), text=True)
        assert 'MainPID=' in output, output
        pid = output.split("=")[-1]
        assert pid != "0", output
        service = unit.replace(f"galaxy-{instance_name}-", "").replace(".service", "")
        pids[service] = pid
    return pids


@pytest.mark.parametrize('process_manager_name', ['supervisor', 'systemd'])
def test_cmd_start(state_dir, galaxy_yml, startup_config, free_port, process_manager_name):
    # TODO: test service_command_style = gravity, doesn't work when you're using CliRunner, which just imports the cli
    # rather than the entry point existing on the filesystem somewhere.
    instance_name = os.path.basename(state_dir)
    startup_config["gravity"]["process_manager"] = process_manager_name
    startup_config["gravity"]["instance_name"] = instance_name
    galaxy_yml.write(json.dumps(startup_config))
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'update'])
    assert result.exit_code == 0, result.output
    start_instance(state_dir, galaxy_yml, free_port, process_manager_name, instance_name=instance_name)
    result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'status'])
    celery_beat_db_paths = list(map(lambda f: state_dir / f, CELERY_BEAT_DB_FILENAMES))
    celery_beat_db_exists = wait_for_any_path(celery_beat_db_paths, CELERY_BEAT_TIMEOUT)
    assert celery_beat_db_exists is True, "celery-beat failed to write db. State dir contents:\n" \
        f"{os.listdir(state_dir)}"
    result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'stop'])
    assert result.exit_code == 0, result.output
    if process_manager_name == "supervisor":
        assert "All processes stopped, supervisord will exit" in result.output
    else:
        assert "" == result.output


def test_cmd_start_reports(state_dir, galaxy_yml, reports_config, free_port):
    galaxy_yml.write(json.dumps(reports_config))
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'update'])
    assert result.exit_code == 0, result.output
    result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'start'])
    assert re.search(r"reports\s*STARTING", result.output)
    assert result.exit_code == 0, result.output
    startup_done, startup_logs = wait_for_startup(state_dir, free_port, path="/", service_name="reports")
    assert startup_done is True, f"Startup failed. Application startup logs:\n {startup_logs}"
    result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'stop'])
    assert result.exit_code == 0, result.output
    assert "All processes stopped, supervisord will exit" in result.output


@pytest.mark.parametrize('process_manager_name', ['supervisor', 'systemd'])
def test_cmd_start_with_gxit(state_dir, galaxy_yml, gxit_startup_config, free_port, process_manager_name):
    instance_name = gxit_startup_config["gravity"]["instance_name"]
    galaxy_yml.write(json.dumps(gxit_startup_config))
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'update'])
    assert result.exit_code == 0, result.output
    start_time = time.time()
    start_instance(state_dir, galaxy_yml, free_port, process_manager_name, instance_name=instance_name)
    result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'status'])
    assert result.exit_code == 0, result.output
    startup_done, startup_logs = wait_for_gxit_proxy(state_dir, process_manager_name, start_time)
    assert startup_done is True, f"gx-it-proxy startup failed. gx-it-proxy startup logs:\n {startup_logs}"


@pytest.mark.parametrize('process_manager_name', ['supervisor', 'systemd'])
def test_cmd_graceful(state_dir, galaxy_yml, tusd_startup_config, free_port, process_manager_name):
    service_pid_func = globals()[process_manager_name + "_service_pids"]
    instance_name = tusd_startup_config["gravity"]["instance_name"]
    # disable preload, causes graceful to HUP
    tusd_startup_config["gravity"]["gunicorn"]["preload"] = False
    # make a fake tusd
    tusd_path = state_dir / "tusd"
    tusd_path.write_text("#!/bin/sh\nsleep 60\n")
    tusd_path.chmod(0o755)
    tusd_startup_config["gravity"]["tusd"]["tusd_path"] = str(tusd_path)
    galaxy_yml.write(json.dumps(tusd_startup_config))
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'update'])
    assert result.exit_code == 0, result.output
    start_instance(state_dir, galaxy_yml, free_port, process_manager_name, instance_name=instance_name)
    before_pids = service_pid_func(runner, galaxy_yml, instance_name)
    result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'graceful'])
    assert result.exit_code == 0, result.output
    after_pids = service_pid_func(runner, galaxy_yml, instance_name)
    assert before_pids['gunicorn'] == after_pids['gunicorn'], f"{before_pids}; {after_pids}"
    assert before_pids['celery'] != after_pids['celery'], f"{before_pids}; {after_pids}"
    assert before_pids['celery-beat'] != after_pids['celery-beat'], f"{before_pids}; {after_pids}"
    assert before_pids['tusd'] == after_pids['tusd'], f"{before_pids}; {after_pids}"


def test_cmd_restart_with_update(state_dir, galaxy_yml, startup_config, free_port):
    galaxy_yml.write(json.dumps(startup_config))
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'update'])
    assert result.exit_code == 0, result.output
    start_instance(state_dir, galaxy_yml, free_port)
    # change prefix
    prefix = '/galaxypf/'
    startup_config['galaxy']['galaxy_url_prefix'] = prefix
    galaxy_yml.write(json.dumps(startup_config))
    result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'restart'])
    assert result.exit_code == 0, result.output
    startup_done, startup_logs = wait_for_startup(state_dir=state_dir, free_port=free_port, prefix=prefix)
    assert startup_done is True, f"Startup failed. Application startup logs:\n {startup_logs}"


def test_cmd_show(state_dir, galaxy_yml):
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'show'])
    assert result.exit_code == 0, result.output
    details = safe_load(result.output)
    assert details['config_type'] == 'galaxy'


def test_cmd_list(state_dir, galaxy_yml):
    runner = CliRunner()
    result = runner.invoke(galaxyctl, ['--config-file', str(galaxy_yml), 'list'])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("TYPE")
    assert str(galaxy_yml) in result.output
