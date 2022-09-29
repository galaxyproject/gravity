""" Galaxy Process Management superclass and utilities
"""

import contextlib
import importlib
import inspect
import os
import subprocess
from abc import ABCMeta, abstractmethod
from functools import partial, wraps

from gravity.config_manager import ConfigManager
from gravity.io import debug, exception, info, warn
from gravity.state import VALID_SERVICE_NAMES
from gravity.util import which


@contextlib.contextmanager
def process_manager(*args, **kwargs):
    pm = ProcessManagerRouter(*args, **kwargs)
    try:
        yield pm
    finally:
        pm.terminate()


def _route(func, all_process_managers=False):
    """Given instance names, populates kwargs with instance configs for the given PM, and calls the PM-routed function
    """
    @wraps(func)
    def decorator(self, *args, instance_names=None, **kwargs):
        configs_by_pm = {}
        pm_names = self.process_managers.keys()
        instance_names, service_names = self._instance_service_names(instance_names)
        configs = self.config_manager.get_registered_configs(instances=instance_names or None)
        for config in configs:
            try:
                configs_by_pm[config.process_manager].append(config)
            except KeyError:
                configs_by_pm[config.process_manager] = [config]
        if not all_process_managers:
            pm_names = configs_by_pm.keys()
        for pm_name in pm_names:
            routed_func = getattr(self.process_managers[pm_name], func.__name__)
            routed_func_params = inspect.getargspec(routed_func).args
            if "configs" in routed_func_params:
                pm_configs = configs_by_pm.get(pm_name, [])
                kwargs["configs"] = pm_configs
                debug(f"Calling {func.__name__} in process manager {pm_name} for instances: {[c.instance_name for c in pm_configs]}")
            else:
                debug(f"Calling {func.__name__} in process manager {pm_name} for all instances")
            if "service_names" in routed_func_params:
                kwargs["service_names"] = service_names
            routed_func(*args, **kwargs)
        # note we don't ever actually call the decorated function, we call the routed one(s)
    return decorator


route = partial(_route, all_process_managers=False)
route_to_all = partial(_route, all_process_managers=True)


class BaseProcessManager(metaclass=ABCMeta):

    def __init__(self, state_dir=None, config_manager=None, start_daemon=True, foreground=False):
        self.config_manager = config_manager or ConfigManager(state_dir=state_dir)
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

    def _file_needs_update(self, path, contents):
        """Update if contents differ"""
        if os.path.exists(path):
            # check first whether there are changes
            with open(path) as fh:
                existing_contents = fh.read()
            if existing_contents == contents:
                return False
        return True

    def _update_file(self, path, contents, name, file_type):
        exists = os.path.exists(path)
        if (exists and self._file_needs_update(path, contents)) or not exists:
            verb = "Updating" if exists else "Adding"
            info("%s %s %s", verb, file_type, name)
            with open(path, "w") as out:
                out.write(contents)
        else:
            debug("No changes to existing config for %s %s at %s", file_type, name, path)

    def follow(self, configs=None, service_names=None, quiet=False):
        # supervisor has a built-in tail command but it only works on a single log file. `galaxyctl supervisorctl tail
        # ...` can be used if desired, though
        if not self.tail:
            exception("`tail` not found on $PATH, please install it")
        log_files = []
        if quiet:
            cmd = [self.tail, "-f", self.log_file]
            tail_popen = subprocess.Popen(cmd)
            tail_popen.wait()
        else:
            if not configs:
                configs = self.config_manager.get_registered_configs()
            for config in configs:
                log_dir = config.attribs["log_dir"]
                if not service_names:
                    for service in config.services:
                        program_name = self._service_program_name(config.instance_name, service)
                        log_files.append(self._service_log_file(log_dir, program_name))
                else:
                    log_files.extend([self._service_log_file(log_dir, s) for s in service_names])
                cmd = [self.tail, "-f"] + log_files
                tail_popen = subprocess.Popen(cmd)
                tail_popen.wait()

    @abstractmethod
    def _process_config(self, config_file, config, **kwargs):
        """ """

    @abstractmethod
    def start(self, configs=None, service_names=None):
        """ """

    @abstractmethod
    def stop(self, configs=None, service_names=None):
        """ """

    @abstractmethod
    def restart(self, configs=None, service_names=None):
        """ """

    @abstractmethod
    def reload(self, configs=None, service_names=None):
        """ """

    @abstractmethod
    def graceful(self, configs=None, service_names=None):
        """ """

    @abstractmethod
    def status(self):
        """ """

    @abstractmethod
    def update(self, configs=None, service_names=None, force=False):
        """ """

    @abstractmethod
    def shutdown(self):
        """ """

    @abstractmethod
    def terminate(self):
        """ """

    @abstractmethod
    def pm(self, *args, **kwargs):
        """Direct pass-thru to process manager."""


class ProcessManagerRouter:
    def __init__(self, state_dir=None, **kwargs):
        self.config_manager = ConfigManager(state_dir=state_dir)
        self.state_dir = self.config_manager.state_dir
        self._load_pm_modules(state_dir=state_dir, **kwargs)

    def _load_pm_modules(self, *args, **kwargs):
        self.process_managers = {}
        for filename in os.listdir(os.path.dirname(__file__)):
            if filename.endswith(".py") and not filename.startswith("_"):
                mod = importlib.import_module("gravity.process_manager." + filename[: -len(".py")])
                for name in dir(mod):
                    obj = getattr(mod, name)
                    if not name.startswith("_") and inspect.isclass(obj) and issubclass(obj, BaseProcessManager) and obj != BaseProcessManager:
                        pm = obj(*args, config_manager=self.config_manager, **kwargs)
                        self.process_managers[pm.name] = pm

    def _instance_service_names(self, names):
        instance_names = []
        service_names = []
        registered_instance_names = self.config_manager.get_registered_instance_names()
        if names:
            for name in names:
                if name in registered_instance_names:
                    instance_names.append(name)
                elif name in VALID_SERVICE_NAMES:
                    service_names.append(name)
                else:
                    warn(f"Warning: Not a known instance or service name: {name}")
            if not instance_names and not service_names:
                exception("No provided names are known instance or service names")
        return (instance_names, service_names)

    @route
    def follow(self, instance_names=None, quiet=None):
        """ """

    @route
    def start(self, instance_names=None):
        """ """

    @route
    def stop(self, instance_names=None):
        """ """

    @route
    def restart(self, instance_names=None):
        """ """

    @route
    def reload(self, instance_names=None):
        """ """

    @route
    def graceful(self, instance_names=None):
        """ """

    @route
    def status(self):
        """ """

    @route_to_all
    def update(self, instance_names=None, force=False):
        """ """

    @route
    def shutdown(self):
        """ """

    @route
    def terminate(self):
        """ """

    @route
    def pm(self):
        """ """
