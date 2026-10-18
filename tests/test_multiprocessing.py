import os
import signal
import subprocess
import sys
import time

START_SCRIPT = """
import os
import sys
import types

from gravity.process_manager.multiprocessing import MultiprocessingProcessManager


class SleepExecutor:
    def __init__(self, pid_dir):
        self.pid_dir = pid_dir

    def exec(self, config, service):
        open(os.path.join(self.pid_dir, str(os.getpid())), "w").close()
        os.execvp("sleep", ["sleep", "60"])


if __name__ == "__main__":
    config = types.SimpleNamespace(services=[object(), object()])
    pm = MultiprocessingProcessManager(config_manager=object(), process_executor=SleepExecutor(sys.argv[1]))
    pm.start(configs=[config])
"""


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_for(condition, timeout=30):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.1)
    return True


def test_multiprocessing_start_forwards_sigterm_to_services(tmp_path):
    script = tmp_path / "start.py"
    script.write_text(START_SCRIPT)
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    proc = subprocess.Popen([sys.executable, str(script), str(pid_dir)])
    service_pids = []
    try:
        assert _wait_for(lambda: len(os.listdir(pid_dir)) == 2)
        service_pids = [int(name) for name in os.listdir(pid_dir)]
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=30)
        assert _wait_for(lambda: not any(_alive(pid) for pid in service_pids))
    finally:
        proc.kill()
        for pid in service_pids:
            if _alive(pid):
                os.kill(pid, signal.SIGKILL)
