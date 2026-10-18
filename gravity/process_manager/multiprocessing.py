"""
"""
import multiprocessing
import signal
from typing import (
    Iterable,
    List,
    Set,
)

from gravity.process_manager import BaseProcessManager, ProcessExecutor
from gravity.settings import ProcessManager
from gravity.state import ConfigFile


class MultiprocessingProcessManager(BaseProcessManager):

    name = ProcessManager.multiprocessing

    def __init__(self, process_executor=None, **kwargs):
        super().__init__(**kwargs)

        assert process_executor is not None, f"Process executor is required for {self.__class__.__name__}"
        self.process_executor = process_executor
        self.processes = []

    def follow(self, configs=None, service_names=None, quiet=False):
        """ """

    def start(self, configs=None, service_names=None):
        for config in configs:
            for service in config.services:
                process = multiprocessing.Process(target=self.process_executor.exec, args=(config, service))
                process.start()
                self.processes.append(process)
        # The services would outlive this process on SIGTERM, so pass it on to them.
        previous_handler = signal.signal(signal.SIGTERM, self._terminate_processes)
        try:
            for process in self.processes:
                process.join()
        finally:
            signal.signal(signal.SIGTERM, previous_handler)

    def _terminate_processes(self, signum, frame):
        for process in self.processes:
            process.terminate()

    def pm(self, *args, **kwargs):
        """ """

    def stop(self, configs=None, service_names=None):
        """ """

    def _intended_pm_files_for_config(self, config: ConfigFile) -> Set[str]:
        raise NotImplementedError()

    def _present_pm_files_for_config(self, config: ConfigFile) -> Set[str]:
        raise NotImplementedError()

    def _disable_and_remove_pm_files(self, pm_files: Iterable[str]) -> None:
        raise NotImplementedError()

    def _all_present_pm_files(self) -> List[str]:
        raise NotImplementedError()

    def restart(self, configs=None, service_names=None):
        """ """

    def graceful(self, configs=None, service_names=None, start_if_stopped=False):
        """ """

    def status(self, configs=None, service_names=None):
        """ """

    def terminate(self):
        """ """

    def shutdown(self):
        """ """

    def update(self, configs: List[ConfigFile], force: bool = False, clean: bool = False) -> None:
        """ """

    _service_environment_formatter = ProcessExecutor._service_environment_formatter
