""" Galaxy Process Management superclass and utilities
"""

import contextlib
import importlib
import inspect
import os
import subprocess
from abc import ABCMeta, abstractmethod

from gravity.config_manager import ConfigManager
from gravity.io import exception
from gravity.util import which


# If at some point we have additional process managers we can make a factory,
# but for the moment there's only supervisor.
@contextlib.contextmanager
def process_manager(*args, **kwargs):
    # roulette!
    for filename in os.listdir(os.path.dirname(__file__)):
        if filename.endswith(".py") and not filename.startswith("_"):
            mod = importlib.import_module("gravity.process_manager." + filename[: -len(".py")])
            for name in dir(mod):
                obj = getattr(mod, name)
                if not name.startswith("_") and inspect.isclass(obj) and issubclass(obj, BaseProcessManager) and obj != BaseProcessManager:
                    pm = obj(*args, **kwargs)
                    try:
                        yield pm
                    finally:
                        pm.terminate()
                    return


class BaseProcessManager(object, metaclass=ABCMeta):

    def __init__(self, state_dir=None, start_daemon=True, foreground=False):
        self.config_manager = ConfigManager(state_dir=state_dir)
        self.state_dir = self.config_manager.state_dir
        self.tail = which("tail")

    def _service_log_file(self, log_dir, program_name):
        return os.path.join(log_dir, program_name + ".log")

    def _service_program_name(self, instance_name, service):
        return f"{instance_name}_{service['config_type']}_{service['service_type']}_{service['service_name']}"

    def _service_environment(self, service, attribs):
        environment = service.get_environment()
        environment_from = service.environment_from
        if not environment_from:
            environment_from = service.service_type
        environment.update(attribs.get(environment_from, {}).get("environment", {}))
        return environment

    @abstractmethod
    def start(self, instance_names):
        """ """

    @abstractmethod
    def _process_config_changes(self, configs, meta_changes):
        """ """

    @abstractmethod
    def terminate(self):
        """ """

    @abstractmethod
    def stop(self, instance_names):
        """ """

    @abstractmethod
    def restart(self, instance_names):
        """ """

    @abstractmethod
    def reload(self, instance_names):
        """ """

    def follow(self, instance_names, quiet=False):
        # supervisor has a built-in tail command but it only works on a single log file. `galaxyctl supervisorctl tail
        # ...` can be used if desired, though
        if not self.tail:
            exception("`tail` not found on $PATH, please install it")
        instance_names, service_names, registered_instance_names = self.get_instance_names(instance_names)
        log_files = []
        if quiet:
            cmd = [self.tail, "-f", self.log_file]
            tail_popen = subprocess.Popen(cmd)
            tail_popen.wait()
        else:
            if not instance_names:
                instance_names = registered_instance_names
            for instance_name in instance_names:
                config = self.config_manager.get_instance_config(instance_name)
                log_dir = config["attribs"]["log_dir"]
                if not service_names:
                    services = self.config_manager.get_instance_services(instance_name)
                    for service in services:
                        program_name = self._service_program_name(instance_name, service)
                        log_files.append(self._service_log_file(log_dir, program_name))
                else:
                    log_files.extend([self._service_log_file(log_dir, s) for s in service_names])
                cmd = [self.tail, "-f"] + log_files
                tail_popen = subprocess.Popen(cmd)
                tail_popen.wait()

    @abstractmethod
    def graceful(self, instance_names):
        """ """

    @abstractmethod
    def update(self, instance_names):
        """ """

    @abstractmethod
    def shutdown(self, instance_names):
        """ """

    def get_instance_names(self, instance_names):
        registered_instance_names = self.config_manager.get_registered_instances()
        unknown_instance_names = []
        if instance_names:
            _instance_names = []
            for n in instance_names:
                if n in registered_instance_names:
                    _instance_names.append(n)
                else:
                    unknown_instance_names.append(n)
            instance_names = _instance_names
        elif registered_instance_names:
            instance_names = registered_instance_names
        else:
            exception("No instances registered (hint: `galaxyctl register /path/to/galaxy.yml`)")
        return instance_names, unknown_instance_names, registered_instance_names
