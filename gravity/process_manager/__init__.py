""" Galaxy Process Management superclass and utilities
"""
import contextlib
import errno
import importlib
import inspect
import os
import shlex
import sys
from abc import ABCMeta, abstractmethod
from functools import partial, wraps

import gravity.io
from gravity.config_manager import ConfigManager
from gravity.settings import DEFAULT_INSTANCE_NAME, ServiceCommandStyle
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
        configs = self.config_manager.get_configs(instances=instance_names or None)
        if not configs:
            gravity.io.exception("No configured Galaxy instances")
        for config in configs:
            try:
                configs_by_pm[config.process_manager].append(config)
            except KeyError:
                configs_by_pm[config.process_manager] = [config]
        if not all_process_managers:
            pm_names = configs_by_pm.keys()
        for pm_name in pm_names:
            routed_func = getattr(self.process_managers[pm_name], func.__name__)
            routed_func_params = list(inspect.signature(routed_func).parameters)
            if "configs" in routed_func_params:
                pm_configs = configs_by_pm.get(pm_name, [])
                kwargs["configs"] = pm_configs
                gravity.io.debug(f"Calling {func.__name__} in process manager {pm_name} for instances: {[c.instance_name for c in pm_configs]}")
            else:
                gravity.io.debug(f"Calling {func.__name__} in process manager {pm_name} for all instances")
            if "service_names" in routed_func_params:
                kwargs["service_names"] = service_names
            routed_func(*args, **kwargs)
        # note we don't ever actually call the decorated function, we call the routed one(s)
    return decorator


route = partial(_route, all_process_managers=False)
route_to_all = partial(_route, all_process_managers=True)


class BaseProcessExecutionEnvironment(metaclass=ABCMeta):
    def __init__(self, state_dir=None, config_file=None, config_manager=None, **kwargs):
        self.config_manager = config_manager or ConfigManager(state_dir=state_dir, config_file=config_file)
        self.tail = which("tail")

    @abstractmethod
    def _service_environment_formatter(self, environment, format_vars):
        raise NotImplementedError()

    def _service_default_path(self):
        return os.environ["PATH"]

    def _service_program_name(self, instance_name, service):
        return f"{instance_name}_{service.config_type}_{service.service_type}_{service.service_name}"

    def _service_format_vars(self, config, service, pm_format_vars=None):
        pm_format_vars = pm_format_vars or {}
        virtualenv_dir = config.virtualenv
        virtualenv_bin = shlex.quote(f'{os.path.join(virtualenv_dir, "bin")}{os.path.sep}') if virtualenv_dir else ""

        format_vars = {
            "config_type": service.config_type,
            "server_name": service.service_name,
            "galaxy_umask": service.settings.get("umask") or config.umask,
            "galaxy_conf": config.galaxy_config_file,
            "galaxy_root": config.galaxy_root,
            "virtualenv_bin": virtualenv_bin,
            "gravity_data_dir": shlex.quote(config.gravity_data_dir),
            "app_config": config.app_config,
        }

        format_vars["settings"] = service.settings
        format_vars["service_instance_count"] = service.count

        # update here from PM overrides
        format_vars.update(pm_format_vars)

        # template the command template
        if config.service_command_style in (ServiceCommandStyle.direct, ServiceCommandStyle.exec):
            format_vars["command_arguments"] = service.get_command_arguments(format_vars)
            format_vars["command"] = service.command_template.format(**format_vars)

            # template env vars
            environment = service.environment
            virtualenv_bin = format_vars["virtualenv_bin"]  # could have been changed by pm_format_vars
            if virtualenv_bin and service.add_virtualenv_to_path:
                path = environment.get("PATH", self._service_default_path())
                environment["PATH"] = ":".join([virtualenv_bin, path])
        else:
            config_file = shlex.quote(config.gravity_config_file)
            # is there a click way to do this?
            galaxyctl = sys.argv[0]
            if galaxyctl.endswith(f"{os.path.sep}galaxy"):
                # handle when called using the `galaxy` entrypoint
                galaxyctl += "ctl"
            if not galaxyctl.endswith(f"{os.path.sep}galaxyctl"):
                gravity.io.warn(f"Unable to determine galaxyctl command, sys.argv[0] is: {galaxyctl}")
            galaxyctl = shlex.quote(galaxyctl)
            instance_number_opt = ""
            if service.count > 1:
                instance_number_opt = f" --service-instance {pm_format_vars['instance_number']}"
            format_vars["command"] = f"{galaxyctl} --config-file {config_file} exec{instance_number_opt} {config.instance_name} {service.service_name}"
            environment = {}
        format_vars["environment"] = self._service_environment_formatter(environment, format_vars)

        return format_vars


class BaseProcessManager(BaseProcessExecutionEnvironment, metaclass=ABCMeta):
    def __init__(self, *args, foreground=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._service_changes = None

    @property
    def _use_instance_name(self):
        return ((not self.config_manager.single_instance)
                or self.config_manager.get_config().instance_name != DEFAULT_INSTANCE_NAME)

    def _remove_unintended_pm_files_for_configs(self, configs):
        unintended_pm_files = set()
        for config in configs:
            intended_pm_files = self._intended_pm_files_for_config(config)
            present_pm_files = self._present_pm_files_for_config(config)
            unintended_pm_files.update(present_pm_files - intended_pm_files)
        self._disable_and_remove_pm_files(unintended_pm_files)

    def _remove_all_pm_files_for_configs(self, configs):
        for config in configs:
            pm_files = self._present_pm_files_for_config(config)
            self._disable_and_remove_pm_files(pm_files)

    def _remove_all_pm_files(self):
        # the kevin uxbridge method
        pm_files = self._all_present_pm_files()
        self._disable_and_remove_pm_files(pm_files)

    def _pre_update(self, configs, force, clean):
        all_configs = set(self.config_manager.get_configs())
        if not clean:
            # no --clean and either possibility of --force
            # remove any pm files for configs known to this gravity but managed by other PMs
            self._remove_all_pm_files_for_configs(all_configs - set(configs))
            # always remove any unintended pm files for known configs managed by this PM
            self._remove_unintended_pm_files_for_configs(configs)
        elif not force:
            # --clean but no --force, so remove everything we know about
            self._remove_all_pm_files_for_configs(all_configs)
            pm_files = self._all_present_pm_files()
            if pm_files:
                gravity.io.warn(f"Configs not managed by this Gravity remain after cleaning, use --force to remove: {', '.join(pm_files)}")
        else:
            # --clean and --force
            self._remove_all_pm_files()

    def _create_dir_for(self, path):
        try:
            os.makedirs(os.path.dirname(path))
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise

    def _file_needs_update(self, path, contents):
        """Update if contents differ"""
        if os.path.exists(path):
            # check first whether there are changes
            with open(path) as fh:
                existing_contents = fh.read()
            return existing_contents != contents
        return True

    def _update_file(self, path, contents, name, file_type, force):
        if force or self._file_needs_update(path, contents):
            verb = "Updating" if os.path.exists(path) else "Adding"
            gravity.io.info(f"{verb} {file_type} {name}")
            self._create_dir_for(path)
            with open(path, "w") as out:
                out.write(contents)
            self._service_changes = True
            return True
        else:
            gravity.io.debug(f"No changes to existing config for {file_type} {name}: {path}")
            return False

    @abstractmethod
    def follow(self, configs=None, service_names=None, quiet=False):
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
    def graceful(self, configs=None, service_names=None):
        """ """

    @abstractmethod
    def status(self):
        """ """

    @abstractmethod
    def update(self, configs=None, service_names=None, force=False, clean=False):
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


class ProcessExecutor(BaseProcessExecutionEnvironment):
    def _service_environment_formatter(self, environment, format_vars):
        return {k: v.format(**format_vars) for k, v in environment.items()}

    def exec(self, config, service, service_instance_number=None, no_exec=False):
        service_name = service.service_name

        # if this is an instance of a service, we need to ensure that instance_number is formatted in as needed
        instance_count = service.count
        if instance_count > 1:
            msg = f"Cannot exec '{service_name}': This service is configured to use multiple instances and "
            if service_instance_number is None:
                gravity.io.exception(msg + "--service-instance was not set")
            if service_instance_number not in range(0, instance_count):
                gravity.io.exception(msg + "--service-instance is out of range")
            service_instance = service.get_service_instance(service_instance_number)
        else:
            service_instance = service

        # force generation of real commands
        config.service_command_style = ServiceCommandStyle.exec
        format_vars = self._service_format_vars(config, service_instance)
        print_env = ' '.join('{}={}'.format(k, shlex.quote(v)) for k, v in format_vars["environment"].items())

        cmd = shlex.split(format_vars["command"])
        env = {**dict(os.environ), **format_vars["environment"]}
        cwd = format_vars["galaxy_root"]

        # ensure the data dir exists
        try:
            os.makedirs(config.gravity_data_dir)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise

        gravity.io.info(f"Working directory: {cwd}")
        gravity.io.info(f"Executing: {print_env} {format_vars['command']}")

        if not no_exec:
            os.chdir(cwd)
            os.execvpe(cmd[0], cmd, env)


class ProcessManagerRouter:
    def __init__(self, state_dir=None, config_file=None, config_manager=None, **kwargs):
        self.config_manager = config_manager or ConfigManager(state_dir=state_dir, config_file=config_file)
        self._load_pm_modules(**kwargs)
        self._process_executor = ProcessExecutor(config_manager=self.config_manager)

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
        configured_instance_names = self.config_manager.get_configured_instance_names()
        configured_service_names = self.config_manager.get_configured_service_names()
        if names:
            for name in names:
                if name in configured_instance_names:
                    instance_names.append(name)
                elif name in configured_service_names | VALID_SERVICE_NAMES:
                    service_names.append(name)
                else:
                    gravity.io.warn(f"Warning: Not a known instance or service name: {name}")
            if not instance_names and not service_names:
                gravity.io.exception("No provided names are known instance or service names")
        return (instance_names, service_names)

    def exec(self, instance_names=None, service_instance_number=None, no_exec=False):
        """ """
        instance_names, service_names = self._instance_service_names(instance_names)

        if len(instance_names) == 0 and self.config_manager.single_instance:
            instance_names = None
        elif len(instance_names) != 1:
            gravity.io.exception("Only zero or one instance name can be provided")

        config = self.config_manager.get_configs(instances=instance_names)[0]
        service_list = ", ".join(s.service_name for s in config.services)

        if len(service_names) != 1:
            gravity.io.exception(f"Exactly one service name must be provided. Configured service(s): {service_list}")

        service_name = service_names[0]
        services = config.get_services(service_names)
        if not services:
            gravity.io.exception(f"Service '{service_name}' is not configured. Configured service(s): {service_list}")

        service = services[0]
        return self._process_executor.exec(config, service, service_instance_number=service_instance_number, no_exec=no_exec)

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
    def graceful(self, instance_names=None):
        """ """

    @route
    def status(self, instance_names=None):
        """ """

    @route_to_all
    def update(self, instance_names=None, force=False, clean=False):
        """ """

    @route
    def shutdown(self):
        """ """

    @route
    def terminate(self):
        """ """

    @route
    def pm(self, *args):
        """ """
