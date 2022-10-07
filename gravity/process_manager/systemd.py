"""
"""
import errno
import os
import shlex
import subprocess
from glob import glob

from gravity.io import debug, error, exception, info, warn
from gravity.process_manager import BaseProcessManager
from gravity.settings import ProcessManager

SYSTEMD_SERVICE_TEMPLATES = {}
DEFAULT_SYSTEMD_SERVICE_TEMPLATE = """;
; This file is maintained by Gravity - CHANGES WILL BE OVERWRITTEN
;

[Unit]
Description=Galaxy {program_name}
After=network.target
After=time-sync.target

[Service]
UMask={galaxy_umask}
Type=simple
{systemd_user_group}
WorkingDirectory={galaxy_root}
TimeoutStartSec=15
ExecStart={command}
#ExecReload=
#ExecStop=
{environment}
#MemoryLimit=
Restart=always

MemoryAccounting=yes
CPUAccounting=yes
BlockIOAccounting=yes

[Install]
WantedBy=multi-user.target
"""

SYSTEMD_SERVICE_TEMPLATES["gunicorn"] = DEFAULT_SYSTEMD_SERVICE_TEMPLATE
SYSTEMD_SERVICE_TEMPLATES["celery"] = DEFAULT_SYSTEMD_SERVICE_TEMPLATE
SYSTEMD_SERVICE_TEMPLATES["celery-beat"] = DEFAULT_SYSTEMD_SERVICE_TEMPLATE
SYSTEMD_SERVICE_TEMPLATES["standalone"] = DEFAULT_SYSTEMD_SERVICE_TEMPLATE
SYSTEMD_SERVICE_TEMPLATES["gx-it-proxy"] = DEFAULT_SYSTEMD_SERVICE_TEMPLATE
SYSTEMD_SERVICE_TEMPLATES["tusd"] = DEFAULT_SYSTEMD_SERVICE_TEMPLATE


class SystemdProcessManager(BaseProcessManager):

    name = ProcessManager.systemd

    def __init__(self, state_dir=None, start_daemon=True, foreground=False, **kwargs):
        super(SystemdProcessManager, self).__init__(state_dir=state_dir, **kwargs)
        self.user_mode = not self.config_manager.is_root

    @property
    def __systemd_unit_dir(self):
        unit_path = os.environ.get("SYSTEMD_UNIT_PATH")
        if not unit_path:
            unit_path = "/etc/systemd/system" if not self.user_mode else os.path.expanduser("~/.config/systemd/user")
        return unit_path

    @property
    def __use_instance(self):
        #return not self.config_manager.single_instance
        return False

    def __systemctl(self, *args, ignore_rc=None, **kwargs):
        args = list(args)
        if self.user_mode:
            args = ["--user"] + args
        try:
            debug("Calling systemctl with args: %s", args)
            try:
                subprocess.check_call(["systemctl"] + args)
            except subprocess.CalledProcessError as exc:
                if ignore_rc is None or exc.returncode not in ignore_rc:
                    raise
        except:
            raise

    def terminate(self):
        """ """
        pass

    # FIXME: should be __service_program_name for follow()?
    def __unit_name(self, instance_name, service):
        unit_name = f"{service['config_type']}-"
        if self.__use_instance:
            unit_name += f"{instance_name}-"
        unit_name += f"{service['service_name']}.service"
        return unit_name

    def __update_service(self, config_file, config, attribs, service, instance_name):
        unit_name = self.__unit_name(instance_name, service)

        # used by the "standalone" service type
        attach_to_pool_opt = ""
        server_pools = service.get("server_pools")
        if server_pools:
            _attach_to_pool_opt = " ".join(f"--attach-to-pool={server_pool}" for server_pool in server_pools)
            # Insert a single leading space
            attach_to_pool_opt = f" {_attach_to_pool_opt}"

        # under supervisor we expect that gravity is installed in the galaxy venv and the venv is active when gravity
        # runs, but under systemd this is not the case. we do assume $VIRTUAL_ENV is the galaxy venv if running as an
        # unprivileged user, though.
        virtualenv_dir = attribs.get("virtualenv")
        environ_virtual_env = os.environ.get("VIRTUAL_ENV")
        if not virtualenv_dir and self.user_mode and environ_virtual_env:
            warn(f"Assuming Galaxy virtualenv is value of $VIRTUAL_ENV: {environ_virtual_env}")
            warn("Set `virtualenv` in Gravity configuration to override")
            virtualenv_dir = environ_virtual_env
        elif not virtualenv_dir:
            exception("The `virtualenv` Gravity config option must be set when using the systemd process manager")

        virtualenv_bin = f'{os.path.join(virtualenv_dir, "bin")}{os.path.sep}' if virtualenv_dir else ""
        gunicorn_options = attribs["gunicorn"].copy()
        gunicorn_options["preload"] = "--preload" if gunicorn_options["preload"] else ""

        format_vars = {
            #"log_dir": attribs["log_dir"],
            #"log_file": self._service_log_file(attribs["log_dir"], program_name),
            "program_name": service["service_name"],
            "systemd_user_group": "",
            "config_type": service["config_type"],
            "server_name": service["service_name"],
            "attach_to_pool_opt": attach_to_pool_opt,
            "pid_file_opt": "",
            "gunicorn": gunicorn_options,
            "celery": attribs["celery"],
            "galaxy_infrastructure_url": attribs["galaxy_infrastructure_url"],
            "tusd": attribs["tusd"],
            "gx_it_proxy": attribs["gx_it_proxy"],
            "galaxy_umask": service.get("umask", "022"),
            "galaxy_conf": config_file,
            "galaxy_root": config["galaxy_root"],
            "virtualenv_bin": virtualenv_bin,
            "state_dir": self.state_dir,
        }
        format_vars["command"] = service.command_template.format(**format_vars)
        if not format_vars["command"].startswith("/"):
            # FIXME: bit of a hack
            format_vars["command"] = f"{virtualenv_bin}/{format_vars['command']}"
        if not self.user_mode:
            format_vars["systemd_user_group"] = f"User={attribs['galaxy_user']}"
            if attribs["galaxy_group"] is not None:
                format_vars["systemd_user_group"] += f"\nGroup={attribs['galaxy_group']}"
        conf = os.path.join(self.__systemd_unit_dir, unit_name)

        template = SYSTEMD_SERVICE_TEMPLATES.get(service["service_type"])
        if not template:
            raise Exception(f"Unknown service type: {service['service_type']}")

        environment = self._service_environment(service, attribs)
        if virtualenv_bin and service.add_virtualenv_to_path:
            # FIXME: what should we use for a default here?
            path = environment.get("PATH", "%(ENV_PATH)s")
            environment["PATH"] = ":".join([virtualenv_bin, path])
        format_vars["environment"] = "\n".join("Environment={}={}".format(k, shlex.quote(v.format(**format_vars))) for k, v in environment.items())

        contents = template.format(**format_vars)
        self._update_file(conf, contents, unit_name, "service")

        return conf

    def _process_config(self, config, **kwargs):
        """ """
        instance_name = config["instance_name"]
        attribs = config["attribs"]
        config_file = config.__file__
        intended_configs = set()

        try:
            os.makedirs(self.__systemd_unit_dir)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise

        for service in config["services"]:
            intended_configs.add(self.__update_service(config_file, config, attribs, service, instance_name))

        return intended_configs

    def _process_configs(self, configs):
        intended_configs = set()

        for config in configs:
            intended_configs = intended_configs | self._process_config(config)

        # the unit dir might not exist if $SYSTEMD_UNIT_PATH is set (e.g. for tests), but this is fine if there are no
        # intended configs
        if not intended_configs and not os.path.exists(self.__systemd_unit_dir):
            return

        # FIXME: should use config_type, but that's per-service
        _present_configs = filter(lambda f: f.startswith("galaxy-"), os.listdir(self.__systemd_unit_dir))
        present_configs = set([os.path.join(self.__systemd_unit_dir, f) for f in _present_configs])

        for file in (present_configs - intended_configs):
            service_name = os.path.basename(os.path.splitext(file)[0])
            info(f"Ensuring service is stopped: {service_name}")
            self.__systemctl("stop", service_name)
            info("Removing service config %s", file)
            os.unlink(file)

    def __unit_names(self, configs, service_names):
        unit_names = []
        for config in configs:
            services = config.services
            if service_names:
                services = [s for s in config.services if s["service_name"] in service_names]
            unit_names.extend([self.__unit_name(config.instance_name, s) for s in services])
        return unit_names

    def start(self, configs=None, service_names=None):
        """ """
        unit_names = self.__unit_names(configs, service_names)
        self.__systemctl("start", *unit_names)

    def stop(self, configs=None, service_names=None):
        """ """
        unit_names = self.__unit_names(configs, service_names)
        self.__systemctl("stop", *unit_names)

    def restart(self, configs=None, service_names=None):
        """ """
        unit_names = self.__unit_names(configs, service_names)
        self.__systemctl("restart", *unit_names)

    def reload(self, configs=None, service_names=None):
        """ """
        unit_names = self.__unit_names(configs, service_names)
        self.__systemctl("reload", *unit_names)

    def graceful(self, configs=None, service_names=None):
        """ """
        unit_names = self.__unit_names(configs, service_names)
        self.__systemctl("reload", *unit_names)

    def status(self, configs=None, service_names=None):
        """ """
        unit_names = self.__unit_names(configs, service_names)
        self.__systemctl("status", "--lines=0", *unit_names, ignore_rc=(3,))

    def update(self, configs=None, force=False, **kwargs):
        """ """
        if force:
            for config in configs:
                service_units = glob(os.path.join(self.__systemd_unit_dir, f"{config.config_type}-*.service"))
                # TODO: would need to add targets here assuming we add one
                if service_units:
                    newline = '\n'
                    info(f"Removing systemd units due to --force option:{newline}{newline.join(service_units)}")
                    list(map(os.unlink, service_units))
        self._process_configs(configs)
        # TODO: only reload if there are changes
        self.__systemctl("daemon-reload")


    def shutdown(self):
        """ """
        debug(f"SHUTDOWN")

    def pm(self):
        """ """
