"""
"""
import errno
import os
import shlex
import shutil
import subprocess
import time
from functools import partial
from os.path import exists, expanduser, join

import gravity.io
from gravity.process_manager import BaseProcessManager
from gravity.settings import ProcessManager
from gravity.state import GracefulMethod
from gravity.util import which

from supervisor import supervisorctl  # type: ignore

DEFAULT_SUPERVISOR_SOCKET_PATH = os.environ.get("SUPERVISORD_SOCKET", '%(here)s/supervisor.sock')

SUPERVISORD_CONF_TEMPLATE = f""";
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[unix_http_server]
file = {DEFAULT_SUPERVISOR_SOCKET_PATH}

[supervisord]
logfile = %(here)s/supervisord.log
pidfile = %(here)s/supervisord.pid
loglevel = info
nodaemon = false

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl = unix://{DEFAULT_SUPERVISOR_SOCKET_PATH}

[include]
files = supervisord.conf.d/*.d/*.conf supervisord.conf.d/*.conf
"""

SUPERVISORD_SERVICE_TEMPLATE = """;
; This file is maintained by Gravity - CHANGES WILL BE OVERWRITTEN
;

[program:{supervisor_program_name}]
command         = {command}
directory       = {galaxy_root}
umask           = {galaxy_umask}
autostart       = true
autorestart     = true
startsecs       = {settings[start_timeout]}
stopwaitsecs    = {settings[stop_timeout]}
environment     = {environment}
numprocs        = {service_instance_count}
numprocs_start  = {supervisor_numprocs_start}
process_name    = {supervisor_process_name}
stdout_logfile  = {log_file}
redirect_stderr = true
"""


SUPERVISORD_GROUP_TEMPLATE = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[group:{instance_name}]
programs = {programs}
"""

DEFAULT_STATE_DIR = expanduser(join("~", ".config", "galaxy-gravity"))
if "XDG_CONFIG_HOME" in os.environ:
    DEFAULT_STATE_DIR = join(os.environ["XDG_CONFIG_HOME"], "galaxy-gravity")


class SupervisorProgram:
    # converts between different formats
    def __init__(self, config, service, use_instance_name):
        self.config = config
        self.service = service
        self._use_instance_name = use_instance_name

        self.config_process_name = "%(program_name)s"
        if self._use_instance_name:
            self.config_process_name = service.service_name

        self.config_numprocs = service.count
        self.config_numprocs_start = 0

        self.config_instance_program_name = self.config_program_name

        if self.config_numprocs > 1:
            if self._use_instance_name:
                self.config_process_name = f"{service.service_name}%(process_num)d"
            else:
                self.config_process_name = "%(process_num)d"
            self.config_instance_program_name += "_%(process_num)d"
            # gets from the first
            try:
                self.config_numprocs_start = int(service.settings["instance_name"])
            except (TypeError, ValueError) as exc:
                gravity.io.exception(f"Invalid value for instance_name (must be an integer with supervisor): {exc}")

    @property
    def config_program_name(self):
        """The representation in [program:NAME] in the supervisor config"""
        service = self.service
        if self._use_instance_name:
            instance_name = self.config.instance_name
            return f"{instance_name}_{service.config_type}_{service.service_type}_{service.service_name}"
        else:
            return service.service_name

    @property
    def program_names(self):
        """The representation when performing commands, after group and procnums expansion"""
        instance_name = None
        if self._use_instance_name:
            instance_name = self.config.instance_name
        service_name = self.service.service_name
        instance_count = self.config_numprocs
        instance_number_start = self.config_numprocs_start
        return supervisor_program_names(service_name, instance_count, instance_number_start, instance_name=instance_name)

    def instance_number(self, instance_name):
        try:
            return int(instance_name) - self.config_numprocs_start
        except (TypeError, ValueError) as exc:
            gravity.io.exception(f"Invalid value for instance_name (must be an integer with supervisor): {exc}")

    #@property
    #def program_instances(self):
    #    """ """
    #    #instance_count = service_settings.get("instance_count", 1)
    #    instance_number_start = self.service.settings.get("instance_number_start", 0)
    #    return [(instance_number_start + i, name) for i, name in enumerate(self.program_names)]



class SupervisorProcessManager(BaseProcessManager):

    name = ProcessManager.supervisor

    def __init__(self, foreground=False, **kwargs):
        super().__init__(**kwargs)

        if self.config_manager.state_dir is not None:
            state_dir = self.config_manager.state_dir
        elif self.config_manager.instance_count > 1:
            state_dir = DEFAULT_STATE_DIR
            gravity.io.info(f"Supervisor configuration will be stored in {state_dir}, set --state-dir ($GRAVITY_STATE_DIR) to override")
        else:
            state_dir = self.config_manager.get_config().gravity_data_dir

        self.supervisord_exe = which("supervisord")
        self.supervisor_state_dir = join(state_dir, "supervisor")
        self.supervisord_conf_path = join(self.supervisor_state_dir, "supervisord.conf")
        self.supervisord_conf_dir = join(self.supervisor_state_dir, "supervisord.conf.d")
        self.supervisord_pid_path = join(self.supervisor_state_dir, "supervisord.pid")
        self.supervisord_sock_path = os.environ.get("SUPERVISORD_SOCKET", join(self.supervisor_state_dir, "supervisor.sock"))
        self.__supervisord_popen = None
        self.foreground = foreground

        if not exists(self.supervisord_conf_dir):
            os.makedirs(self.supervisord_conf_dir)

    @property
    def log_file(self):
        return join(self.supervisor_state_dir, "supervisord.log")

    def __supervisord_is_running(self):
        try:
            assert exists(self.supervisord_pid_path)
            assert exists(self.supervisord_sock_path)
            os.kill(int(open(self.supervisord_pid_path).read()), 0)
            return True
        except Exception:
            return False

    def __supervisord(self):
        format_vars = {"supervisor_state_dir": self.supervisor_state_dir, "supervisord_conf_dir": self.supervisord_conf_dir}
        supervisord_cmd = [self.supervisord_exe, "-c", self.supervisord_conf_path]
        self._remove_invalid_configs()
        if self.foreground:
            supervisord_cmd.append('--nodaemon')
        if not self.__supervisord_is_running():
            # any time that supervisord is not running, let's rewrite supervisord.conf
            open(self.supervisord_conf_path, "w").write(SUPERVISORD_CONF_TEMPLATE.format(**format_vars))
            self.__supervisord_popen = subprocess.Popen(supervisord_cmd, env=os.environ)
            rc = self.__supervisord_popen.poll()
            if rc:
                gravity.io.error("supervisord exited with code %d" % rc)
            # FIXME: don't wait forever
            while not exists(self.supervisord_pid_path) or not exists(self.supervisord_sock_path):
                gravity.io.debug(f"Waiting for {self.supervisord_pid_path}")
                time.sleep(0.5)

    def __get_supervisor(self):
        """Return the supervisor proxy object

        Should probably use this more rather than supervisorctl directly
        """
        options = supervisorctl.ClientOptions()
        options.realize(args=["-c", self.supervisord_conf_path])
        return supervisorctl.Controller(options).get_supervisor()

    def _service_default_path(self):
        return "%(ENV_PATH)s"

    def _service_environment_formatter(self, environment, format_vars):
        return ",".join("{}={}".format(k, shlex.quote(v.format(**format_vars))) for k, v in environment.items())

    def service_instance_number(self, config, service, instance_name):
        program = SupervisorProgram(config, service, self._use_instance_name)
        return program.instance_number(instance_name)

    def terminate(self):
        if self.foreground:
            # if running in foreground, if terminate is called, then supervisord should've already received a SIGINT
            self.__supervisord_popen and self.__supervisord_popen.wait()

    def service_format_vars(self, config, service):
        program = SupervisorProgram(config, service, self._use_instance_name)
        # supervisor-specific format vars
        supervisor_format_vars = {
            "log_dir": config.log_dir,
            "log_file": self._service_log_file(config.log_dir, program.config_instance_program_name),
            "instance_number": "%(process_num)d",
            "supervisor_program_name": program.config_program_name,
            "supervisor_process_name": program.config_process_name,
            "supervisor_numprocs_start": program.config_numprocs_start,
        }

        return self._service_format_vars(config, service, supervisor_format_vars)

    def __update_service(self, config, service, instance_conf_dir, instance_name):
        conf = join(instance_conf_dir, f"{service.config_type}_{service.service_type}_{service.service_name}.conf")
        template = SUPERVISORD_SERVICE_TEMPLATE
        # FIXME: uses var_formatter magic in the route decorator
        #contents = template.format(**service.format_vars)
        contents = template.format(**self.service_format_vars(config, service))
        name = service.service_name if not self._use_instance_name else f"{instance_name}:{service.service_name}"
        self._update_file(conf, contents, name, "service")
        return conf

    def _process_config(self, config):
        """Perform necessary supervisor config updates as per current Galaxy/Gravity configuration.

        Does not call ``supervisorctl update``.
        """
        instance_name = config.instance_name
        instance_conf_dir = join(self.supervisord_conf_dir, f"{instance_name}.d")
        intended_configs = set()
        try:
            os.makedirs(instance_conf_dir)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise

        programs = []
        for service in config.services:
            intended_configs.add(self.__update_service(config, service, instance_conf_dir, instance_name))
            programs.append(f"{instance_name}_{service.config_type}_{service.service_type}_{service.service_name}")

        # TODO: test group mode
        group_conf = join(self.supervisord_conf_dir, f"group_{instance_name}.conf")
        if self._use_instance_name:
            format_vars = {"instance_name": instance_name, "programs": ",".join(programs)}
            contents = SUPERVISORD_GROUP_TEMPLATE.format(**format_vars)
            self._update_file(group_conf, contents, instance_name, "supervisor group")
        elif os.path.exists(group_conf):
            os.unlink(group_conf)

        present_configs = set([join(instance_conf_dir, f) for f in os.listdir(instance_conf_dir)])

        for file in (present_configs - intended_configs):
            gravity.io.info("Removing service config %s", file)
            os.unlink(file)

        # ensure log dir exists only if configs exist
        if intended_configs and not exists(config.log_dir):
            os.makedirs(config.log_dir)

    def _remove_invalid_configs(self, valid_configs=None, invalid_configs=None):
        if not valid_configs:
            valid_configs = self.config_manager.get_configs(process_manager=self.name)
        if invalid_configs is not None:
            valid_configs = [c for c in valid_configs if c not in invalid_configs]
        valid_names = [c.instance_name for c in valid_configs]
        valid_instance_dirs = [f"{name}.d" for name in valid_names]
        valid_group_confs = []
        if self._use_instance_name:
            valid_group_confs = [f"group_{name}.conf" for name in valid_names]
        for entry in os.listdir(self.supervisord_conf_dir):
            path = join(self.supervisord_conf_dir, entry)
            if entry.startswith("group_") and entry not in valid_group_confs:
                gravity.io.info(f"Removing group config {path}")
                os.unlink(path)
            elif entry.endswith(".d") and entry not in valid_instance_dirs:
                gravity.io.info(f"Removing instance directory {path}")
                shutil.rmtree(path)

    def __supervisor_programs(self, config, service_names):
        services = [s for s in config.services if s.service_name in service_names]
        return [SupervisorProgram(config, service, self._use_instance_name) for service in services]

    def __supervisor_program_names(self, config, service_names):
        #return [p.program_names for p in self.__supervisor_programs(config, service_names) for p.program_names in p]
        program_names = []
        for program in self.__supervisor_programs(config, service_names):
            program_names.extend(program.program_names)
        return program_names

    def __start_stop(self, op, configs, service_names):
        targets = []
        for config in configs:
            if service_names:
                targets.extend(self.__supervisor_program_names(config, service_names))
            elif self._use_instance_name:
                targets.append(f"{config.instance_name}:*")
            else:
                targets.append("all")
        self.supervisorctl(op, *targets)

    def __reload_graceful(self, configs, service_names):
        for config in configs:
            if service_names:
                services = [s for s in config.services if s.service_name in service_names]
            else:
                services = config.services
            for service in services:
                program = self.__supervisor_programs(config, [service.service_name])[0]
                graceful_method = service.graceful_method
                if graceful_method == GracefulMethod.SIGHUP:
                    self.supervisorctl("signal", "SIGHUP", *program.program_names)
                elif graceful_method == GracefulMethod.ROLLING:
                    self.__rolling_restart(config, service, program)
                else:
                    self.supervisorctl("restart", *program.program_names)

    def __rolling_restart(self, config, service, program):
        restart_callbacks = list(partial(self.supervisorctl, "restart", p) for p in program.program_names)
        service.rolling_restart(restart_callbacks)

    def start(self, configs=None, service_names=None):
        self.__supervisord()
        self.__start_stop("start", configs, service_names)
        self.supervisorctl("status")

    def stop(self, configs=None, service_names=None):
        self.__start_stop("stop", configs, service_names)
        # Exit supervisor if all processes are stopped
        supervisor = self.__get_supervisor()
        if self.__supervisord_is_running():
            proc_infos = supervisor.getAllProcessInfo()
            if all([i["state"] == 0 for i in proc_infos]):
                gravity.io.info("All processes stopped, supervisord will exit")
                self.shutdown()
            else:
                gravity.io.info("Not all processes stopped, supervisord not shut down (hint: see `galaxyctl status`)")

    def restart(self, configs=None, service_names=None):
        if not self.__supervisord_is_running():
            self.__supervisord()
            gravity.io.warn("supervisord was not previously running; it has been started, so the 'restart' command has been ignored")
        else:
            self.__start_stop("restart", configs, service_names)

    def graceful(self, configs=None, service_names=None):
        if not self.__supervisord_is_running():
            self.__supervisord()
            gravity.io.warn("supervisord was not previously running; it has been started, so the 'graceful' command has been ignored")
        else:
            self.__reload_graceful(configs, service_names)

    def status(self, configs=None, service_names=None):
        # TODO: create our own formatted output
        # supervisor = self.get_supervisor()
        # all_infos = supervisor.getAllProcessInfo()
        self.supervisorctl("status")

    def shutdown(self):
        self.supervisorctl("shutdown")
        while self.__supervisord_is_running():
            gravity.io.debug("Waiting for supervisord to terminate")
            time.sleep(0.5)
        gravity.io.info("supervisord has terminated")

    def update(self, configs=None, force=False, clean=False):
        """Add newly defined servers, remove any that are no longer present"""
        if force and os.listdir(self.supervisord_conf_dir):
            gravity.io.info(f"Removing supervisord conf dir due to --force option: {self.supervisord_conf_dir}")
            shutil.rmtree(self.supervisord_conf_dir)
            os.makedirs(self.supervisord_conf_dir)
        elif not force:
            self._remove_invalid_configs(valid_configs=configs)
        if clean:
            self._remove_invalid_configs(invalid_configs=configs)
        else:
            for config in configs:
                self._process_config(config)
        # only need to update if supervisord is running, otherwise changes will be picked up at next start
        if self.__supervisord_is_running():
            self.supervisorctl("update")

    def supervisorctl(self, *args):
        if not self.__supervisord_is_running():
            gravity.io.warn("supervisord is not running")
            return
        try:
            gravity.io.debug("Calling supervisorctl with args: %s", list(args))
            supervisorctl.main(args=["-c", self.supervisord_conf_path] + list(args))
        except SystemExit as e:
            # supervisorctl.main calls sys.exit(), so we catch that
            if e.code == 0:
                pass
            else:
                raise

    pm = supervisorctl


def supervisor_program_names(service_name, instance_count, instance_number_start, instance_name=None):
    # this is what supervisor turns the service name into depending on groups and numprocs
    if instance_count > 1 and instance_name is not None:
        return [f"{instance_name}:{service_name}{i + instance_number_start}" for i in range(0, instance_count)]

    if instance_count > 1:
        program_names = [f"{service_name}:{i + instance_number_start}" for i in range(0, instance_count)]
    else:
        program_names = [service_name]

    if instance_name is not None:
        return [f"{instance_name}:{program_name}" for program_name in program_names]
    else:
        return program_names
