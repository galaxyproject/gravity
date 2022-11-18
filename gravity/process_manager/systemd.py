"""
"""
import os
import re
import shlex
import subprocess
from glob import glob
from functools import partial

import gravity.io
from gravity.process_manager import BaseProcessManager
from gravity.settings import ProcessManager
from gravity.state import GracefulMethod

SYSTEMD_TARGET_HASH_RE = r";\s*GRAVITY=([0-9a-f]+)"

SYSTEMD_SERVICE_TEMPLATE = """;
; This file is maintained by Gravity - CHANGES WILL BE OVERWRITTEN
;

[Unit]
Description={systemd_description}
After=network.target
After=time-sync.target
PartOf={systemd_target}

[Service]
UMask={galaxy_umask}
Type=simple
{systemd_user_group}
WorkingDirectory={galaxy_root}
TimeoutStartSec={settings[start_timeout]}
TimeoutStopSec={settings[stop_timeout]}
ExecStart={command}
{systemd_exec_reload}
{environment}
{systemd_memory_limit}
Restart=always

MemoryAccounting=yes
CPUAccounting=yes
BlockIOAccounting=yes

[Install]
WantedBy=multi-user.target
"""

SYSTEMD_TARGET_TEMPLATE = """;
; This file is maintained by Gravity - CHANGES WILL BE OVERWRITTEN
;

; This allows Gravity to keep track of which units it controls and should not be changed
; GRAVITY={gravity_config_hash}

[Unit]
Description={systemd_description}
After=network.target
After=time-sync.target
Wants={systemd_target_wants}

[Install]
WantedBy=multi-user.target
"""


class SystemdService:
    # converts between different formats
    def __init__(self, config, service, use_instance_name):
        self.config = config
        self.service = service
        self._use_instance_name = use_instance_name

        if use_instance_name:
            prefix_instance_name = f"-{config.instance_name}"
            description_instance_name = f" {config.instance_name}"
        else:
            prefix_instance_name = ""
            description_instance_name = ""

        if self.service.count > 1:
            description_process = " (process %i)"
        else:
            description_process = ""

        self.unit_prefix = f"{service.config_type}{prefix_instance_name}-{service.service_name}"
        self.description = f"{config.config_type.capitalize()}{description_instance_name} {service.service_name}{description_process}"

    @property
    def unit_file_name(self):
        instance_count = self.service.count
        if instance_count > 1:
            return f"{self.unit_prefix}@.service"
        else:
            return f"{self.unit_prefix}.service"

    @property
    def unit_names(self):
        """The representation when performing commands, after instance expansion"""
        instance_count = self.service.count
        if instance_count > 1:
            unit_names = [f"{self.unit_prefix}@{i}.service" for i in range(0, instance_count)]
        else:
            unit_names = [f"{self.unit_prefix}.service"]
        return unit_names


class SystemdProcessManager(BaseProcessManager):

    name = ProcessManager.systemd

    def __init__(self, foreground=False, **kwargs):
        super(SystemdProcessManager, self).__init__(**kwargs)
        self.user_mode = not self.config_manager.is_root

    @property
    def __systemd_unit_dir(self):
        unit_path = os.environ.get("GRAVITY_SYSTEMD_UNIT_PATH")
        if not unit_path:
            unit_path = "/etc/systemd/system" if not self.user_mode else os.path.expanduser("~/.config/systemd/user")
        return unit_path

    def __systemctl(self, *args, ignore_rc=None, not_found_rc=None, capture=False, **kwargs):
        args = list(args)
        not_found_rc = not_found_rc or ()
        call = subprocess.check_call
        extra_args = os.environ.get("GRAVITY_SYSTEMCTL_EXTRA_ARGS")
        if extra_args:
            args = shlex.split(extra_args) + args
        if self.user_mode:
            args = ["--user"] + args
        gravity.io.debug("Calling systemctl with args: %s", args)
        if capture:
            call = subprocess.check_output
        try:
            return call(["systemctl"] + args, text=True)
        except subprocess.CalledProcessError as exc:
            if exc.returncode in not_found_rc:
                gravity.io.exception("Some expected systemd units were not found, did you forget to run `galaxyctl update`?")
            if ignore_rc is None or exc.returncode not in ignore_rc:
                raise

    def __journalctl(self, *args, **kwargs):
        args = list(args)
        if self.user_mode:
            args = ["--user"] + args
        gravity.io.debug("Calling journalctl with args: %s", args)
        subprocess.check_call(["journalctl"] + args)

    def _service_default_path(self):
        environ = self.__systemctl("show-environment", capture=True)
        for line in environ.splitlines():
            if line.startswith("PATH="):
                return line.split("=", 1)[1]

    def _service_environment_formatter(self, environment, format_vars):
        return "\n".join("Environment={}={}".format(k, shlex.quote(v.format(**format_vars))) for k, v in environment.items())

    def terminate(self):
        # this is used to stop a foreground supervisord in the supervisor PM, so it is a no-op here
        pass

    def __target_unit_name(self, config):
        instance_name = f"-{config.instance_name}" if self._use_instance_name else ""
        return f"{config.config_type}{instance_name}.target"

    def __unit_files_to_active_unit_names(self, unit_files):
        unit_names = []
        for unit_file in unit_files:
            unit_file = os.path.basename(unit_file)
            if "@" in unit_file:
                at_position = unit_file.index("@")
                unit_arg = unit_file[:at_position + 1] + "*" + unit_file[at_position + 1:]
            else:
                unit_arg = unit_file
            list_output = self.__systemctl("list-units", "--plain", "--no-legend", unit_arg, capture=True)
            unit_names.extend(line.split()[0] for line in list_output.splitlines())
        return unit_names

    def _disable_and_remove_pm_files(self, unit_files):
        for target in [u for u in unit_files if u.endswith(".target")]:
            self.__systemctl("disable", "--now", os.path.basename(target))
        # stopping all the targets should also stop all the services, but we'll check to be sure
        active_unit_names = self.__unit_files_to_active_unit_names(unit_files)
        if active_unit_names:
            gravity.io.info(f"Stopping active units: {', '.join(active_unit_names)}")
            self.__systemctl("disable", "--now", *active_unit_names)
        if unit_files:
            gravity.io.info(f"Removing systemd configs: {', '.join(unit_files)}")
            list(map(os.unlink, unit_files))
            self._service_changes = True

    def __read_gravity_config_hash_from_target(self, target_path):
        # systemd has no mechanism for isolated unit dirs, so if you were to invoke gravity's update command on two
        # different gravity config files in succession, the second call would see the unit files written by the first as
        # "unintended" and remove them. there is also no way to separate such "foreign" unit files (from another gravity
        # config) from ones generated by this gravity config but left behind after the instance_name is changed. to deal
        # with this, gravity stores a hash of the path of the gravity config used to generate a target unit file in the
        # file, so that it can determine whether or not it "owns" a given set of unit files, and only clean those.
        with open(target_path) as fh:
            for line in fh:
                match = re.match(SYSTEMD_TARGET_HASH_RE, line)
                if match:
                    return match.group(1)

    def _present_pm_files_for_config(self, config):
        unit_files = set()
        instance_name = f"-{config.instance_name}" if self._use_instance_name else ""
        target = os.path.join(self.__systemd_unit_dir, f"{config.config_type}{instance_name}.target")
        if os.path.exists(target):
            target_hash = self.__read_gravity_config_hash_from_target(target)
            if target_hash == config.path_hash:
                unit_files.add(target)
                unit_files.update(glob(f"{os.path.splitext(target)[0]}-*.service"))
        return unit_files

    def _intended_pm_files_for_config(self, config):
        unit_files = set()
        for service in config.services:
            systemd_service = SystemdService(config, service, self._use_instance_name)
            unit_files.add(os.path.join(self.__systemd_unit_dir, systemd_service.unit_file_name))
        target_unit_name = self.__target_unit_name(config)
        unit_files.add(os.path.join(self.__systemd_unit_dir, target_unit_name))
        return unit_files

    def _all_present_pm_files(self):
        return (glob(os.path.join(self.__systemd_unit_dir, "galaxy-*.service")) +
                glob(os.path.join(self.__systemd_unit_dir, "galaxy-*.target")) +
                glob(os.path.join(self.__systemd_unit_dir, "galaxy.target")))

    def __update_service(self, config, service, systemd_service: SystemdService, force: bool):
        # under supervisor we expect that gravity is installed in the galaxy venv and the venv is active when gravity
        # runs, but under systemd this is not the case. we do assume $VIRTUAL_ENV is the galaxy venv if running as an
        # unprivileged user, though.
        virtualenv_dir = config.virtualenv
        environ_virtual_env = os.environ.get("VIRTUAL_ENV")
        if not virtualenv_dir and self.user_mode and environ_virtual_env:
            gravity.io.warn(f"Assuming Galaxy virtualenv is value of $VIRTUAL_ENV: {environ_virtual_env}")
            gravity.io.warn("Set `virtualenv` in Gravity configuration to override")
            virtualenv_dir = environ_virtual_env
        elif not virtualenv_dir:
            gravity.io.exception("The `virtualenv` Gravity config option must be set when using the systemd process manager")

        memory_limit = service.settings.get("memory_limit") or config.memory_limit
        if memory_limit:
            memory_limit = f"MemoryLimit={memory_limit}G"

        exec_reload = None
        if service.graceful_method == GracefulMethod.SIGHUP:
            exec_reload = "ExecReload=/bin/kill -HUP $MAINPID"

        # systemd-specific format vars
        systemd_format_vars = {
            "virtualenv_bin": shlex.quote(f'{os.path.join(virtualenv_dir, "bin")}{os.path.sep}'),
            "instance_number": "%i",
            "systemd_user_group": "",
            "systemd_exec_reload": exec_reload or "",
            "systemd_memory_limit": memory_limit or "",
            "systemd_description": systemd_service.description,
            "systemd_target": self.__target_unit_name(config),
        }
        if not self.user_mode:
            systemd_format_vars["systemd_user_group"] = f"User={config.galaxy_user}"
            if config.galaxy_group is not None:
                systemd_format_vars["systemd_user_group"] += f"\nGroup={config.galaxy_group}"

        format_vars = self._service_format_vars(config, service, systemd_format_vars)

        unit_file = systemd_service.unit_file_name
        conf = os.path.join(self.__systemd_unit_dir, unit_file)
        template = SYSTEMD_SERVICE_TEMPLATE
        contents = template.format(**format_vars)
        self._update_file(conf, contents, unit_file, "systemd unit", force)

    def __process_config(self, config, force):
        service_units = []
        for service in config.services:
            systemd_service = SystemdService(config, service, self._use_instance_name)
            self.__update_service(config, service, systemd_service, force)
            service_units.extend(systemd_service.unit_names)

        # create systemd target
        target_unit_name = self.__target_unit_name(config)
        target_conf = os.path.join(self.__systemd_unit_dir, target_unit_name)
        format_vars = {
            "gravity_config_hash": config.path_hash,
            "systemd_description": config.config_type.capitalize(),
            "systemd_target_wants": " ".join(service_units),
        }
        if self._use_instance_name:
            format_vars["systemd_description"] += f" {config.instance_name}"
        contents = SYSTEMD_TARGET_TEMPLATE.format(**format_vars)
        if self._update_file(target_conf, contents, target_unit_name, "systemd unit", force):
            self.__systemctl("enable", target_conf)

    def __process_configs(self, configs, force):
        for config in configs:
            self.__process_config(config, force)

    def __unit_names(self, configs, service_names, use_target=True, include_services=False):
        unit_names = []
        for config in configs:
            services = config.services
            if not service_names and use_target:
                unit_names.append(self.__target_unit_name(config))
                if not include_services:
                    services = []
            elif service_names:
                services = config.get_services(service_names)
            systemd_services = [SystemdService(config, s, self._use_instance_name) for s in services]
            for systemd_service in systemd_services:
                unit_names.extend(systemd_service.unit_names)
        return unit_names

    def follow(self, configs=None, service_names=None, quiet=False):
        """ """
        unit_names = self.__unit_names(configs, service_names, use_target=False)
        u_args = [i for sl in list(zip(["-u"] * len(unit_names), unit_names)) for i in sl]
        self.__journalctl("-f", *u_args)

    def start(self, configs=None, service_names=None):
        """ """
        self.update(configs=configs)
        unit_names = self.__unit_names(configs, service_names)
        self.__systemctl("start", *unit_names, not_found_rc=(5,))
        self.status(configs=configs, service_names=service_names)

    def stop(self, configs=None, service_names=None):
        """ """
        unit_names = self.__unit_names(configs, service_names)
        self.__systemctl("stop", *unit_names, not_found_rc=(5,))
        self.status(configs=configs, service_names=service_names)

    def restart(self, configs=None, service_names=None):
        """ """
        # this can result in a double restart if your configs changed, not ideal but we can't really control that
        self.update(configs=configs)
        unit_names = self.__unit_names(configs, service_names)
        self.__systemctl("restart", *unit_names, not_found_rc=(5,))
        self.status(configs=configs, service_names=service_names)

    def __graceful_service(self, config, service, service_names):
        systemd_service = SystemdService(config, service, self._use_instance_name)
        if service.graceful_method == GracefulMethod.ROLLING:
            restart_callbacks = list(partial(self.__systemctl, "reload-or-restart", u) for u in systemd_service.unit_names)
            service.rolling_restart(restart_callbacks)
        elif service.graceful_method != GracefulMethod.NONE:
            self.__systemctl("reload-or-restart", *systemd_service.unit_names, not_found_rc=(5,))
            gravity.io.info(f"Restarted: {', '.join(systemd_service.unit_names)}")

    def graceful(self, configs=None, service_names=None):
        """ """
        self.update(configs=configs)
        # reload-or-restart on a target does a restart on its services, so we use the services directly
        for config in configs:
            services = config.get_services(service_names)
            for service in services:
                self.__graceful_service(config, service, service_names)

    def status(self, configs=None, service_names=None):
        """ """
        unit_names = self.__unit_names(configs, service_names, include_services=True)
        if service_names:
            self.__systemctl("status", *unit_names, ignore_rc=(3,), not_found_rc=(4,))
        else:
            self.__systemctl("list-units", "--all", *unit_names)

    def update(self, configs=None, force=False, clean=False):
        """ """
        self._pre_update(configs, force, clean)
        if not clean:
            self.__process_configs(configs, force)
        if self._service_changes:
            self.__systemctl("daemon-reload")
        else:
            gravity.io.debug("No service changes, daemon-reload not performed")

    def shutdown(self):
        """ """
        if self._use_instance_name:
            configs = self.config_manager.get_configs(process_manager=self.name)
            self.__systemctl("stop", *[f"{c.config_type}-{c.instance_name}.target" for c in configs])
        else:
            self.__systemctl("stop", "galaxy.target")

    def pm(self, *args):
        """ """
        self.__systemctl(*args)
