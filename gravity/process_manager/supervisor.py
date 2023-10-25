"""
"""
import os
import shlex
import subprocess
import time
from functools import partial
from glob import glob

import gravity.io
from gravity.process_manager import BaseProcessManager
from gravity.settings import ProcessManager
from gravity.state import GracefulMethod
from gravity.util import which

from supervisor import supervisorctl  # type: ignore

SUPERVISORD_START_TIMEOUT = 60
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
stopasgroup     = true
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

DEFAULT_STATE_DIR = os.path.expanduser(os.path.join("~", ".config", "galaxy-gravity"))
if "XDG_CONFIG_HOME" in os.environ:
    DEFAULT_STATE_DIR = os.path.join(os.environ["XDG_CONFIG_HOME"], "galaxy-gravity")


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
        self.log_file_name_template = self.config_program_name

        if self.config_numprocs > 1:
            if self._use_instance_name:
                self.config_process_name = f"{service.service_name}%(process_num)d"
            else:
                self.config_process_name = "%(program_name)s_%(process_num)d"
            self.config_instance_program_name += "_%(process_num)d"
            self.log_file_name_template += "_{instance_number}"
        self.log_file_name_template += ".log"

    @property
    def config_file_name(self):
        service = self.service
        return f"{service.config_type}_{service.service_type}_{service.service_name}.conf"

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
    def config_log_file_name(self):
        return self.config_instance_program_name + ".log"

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

    @property
    def log_file_names(self):
        return list(self.log_file_name_template.format(instance_number=i) for i in range(0, self.config_numprocs))


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
        self.supervisor_state_dir = os.path.join(state_dir, "supervisor")
        self.supervisord_conf_path = os.path.join(self.supervisor_state_dir, "supervisord.conf")
        self.supervisord_conf_dir = os.path.join(self.supervisor_state_dir, "supervisord.conf.d")
        self.supervisord_pid_path = os.path.join(self.supervisor_state_dir, "supervisord.pid")
        self.supervisord_sock_path = os.environ.get("SUPERVISORD_SOCKET", os.path.join(self.supervisor_state_dir, "supervisor.sock"))
        self.__supervisord_popen = None
        self.foreground = foreground

    @property
    def log_file(self):
        return os.path.join(self.supervisor_state_dir, "supervisord.log")

    def __supervisord_is_running(self):
        try:
            assert os.path.exists(self.supervisord_pid_path)
            assert os.path.exists(self.supervisord_sock_path)
            os.kill(int(open(self.supervisord_pid_path).read()), 0)
            return True
        except Exception:
            return False

    def __supervisord(self):
        format_vars = {"supervisor_state_dir": self.supervisor_state_dir, "supervisord_conf_dir": self.supervisord_conf_dir}
        supervisord_cmd = [self.supervisord_exe, "-c", self.supervisord_conf_path]
        if self.foreground:
            supervisord_cmd.append('--nodaemon')
        if not self.__supervisord_is_running():
            # any time that supervisord is not running, let's rewrite supervisord.conf
            if not os.path.exists(self.supervisord_conf_dir):
                os.makedirs(self.supervisord_conf_dir)
            open(self.supervisord_conf_path, "w").write(SUPERVISORD_CONF_TEMPLATE.format(**format_vars))
            self.__supervisord_popen = subprocess.Popen(supervisord_cmd, env=os.environ)
            rc = self.__supervisord_popen.poll()
            if rc:
                gravity.io.error("supervisord exited with code %d" % rc)
            start = time.time()
            while not os.path.exists(self.supervisord_pid_path) or not os.path.exists(self.supervisord_sock_path):
                if (time.time() - start) > SUPERVISORD_START_TIMEOUT:
                    gravity.io.exception("Timed out waiting for supervisord to start")
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

    def terminate(self):
        if self.foreground:
            # if running in foreground, if terminate is called, then supervisord should've already received a SIGINT
            self.__supervisord_popen and self.__supervisord_popen.wait()

    def _disable_and_remove_pm_files(self, pm_files):
        # don't need to stop anything - `supervisorctl update` afterward will take care of it
        if pm_files:
            gravity.io.info(f"Removing supervisor configs: {', '.join(pm_files)}")
            list(map(os.unlink, pm_files))
        for instance_dir in set(os.path.dirname(f) for f in pm_files):
            # should maybe warn if the intent was to remove the entire instance
            if not os.listdir(instance_dir):
                gravity.io.info(f"Removing empty instance dir: {instance_dir}")
                os.rmdir(instance_dir)

    def _present_pm_files_for_config(self, config):
        pm_files = set()
        instance_name = config.instance_name
        instance_conf_dir = os.path.join(self.supervisord_conf_dir, f"{instance_name}.d")
        group_file = os.path.join(self.supervisord_conf_dir, f"group_{instance_name}.conf")
        if os.path.exists(group_file):
            pm_files.add(group_file)
        pm_files.update(glob(os.path.join(instance_conf_dir, "*")))
        return pm_files

    def _intended_pm_files_for_config(self, config):
        pm_files = set()
        instance_name = config.instance_name
        instance_conf_dir = os.path.join(self.supervisord_conf_dir, f"{instance_name}.d")
        for service in config.services:
            program = SupervisorProgram(config, service, self._use_instance_name)
            pm_files.add(os.path.join(instance_conf_dir, program.config_file_name))
        if self._use_instance_name:
            pm_files.add(os.path.join(self.supervisord_conf_dir, f"group_{instance_name}.conf"))
        return pm_files

    def _all_present_pm_files(self):
        return (glob(os.path.join(self.supervisord_conf_dir, "*.d", "*")) +
                glob(os.path.join(self.supervisord_conf_dir, "group_*.conf")))

    def __update_service(self, config, service, instance_conf_dir, instance_name, force):
        program = SupervisorProgram(config, service, self._use_instance_name)
        # supervisor-specific format vars
        supervisor_format_vars = {
            "log_dir": config.log_dir,
            "log_file": os.path.join(config.log_dir, program.config_log_file_name),
            "instance_number": "%(process_num)d",
            "supervisor_program_name": program.config_program_name,
            "supervisor_process_name": program.config_process_name,
            "supervisor_numprocs_start": program.config_numprocs_start,
        }

        format_vars = self._service_format_vars(config, service, supervisor_format_vars)

        conf = os.path.join(instance_conf_dir, program.config_file_name)
        template = SUPERVISORD_SERVICE_TEMPLATE
        contents = template.format(**format_vars)
        name = service.service_name if not self._use_instance_name else f"{instance_name}:{service.service_name}"
        if self._update_file(conf, contents, name, "service", force):
            self.supervisorctl('reread')
        return conf

    def __process_config(self, config, force):
        """Perform necessary supervisor config updates as per current Galaxy/Gravity configuration.

        Does not call ``supervisorctl update``.
        """
        instance_name = config.instance_name
        instance_conf_dir = os.path.join(self.supervisord_conf_dir, f"{instance_name}.d")

        programs = []
        for service in config.services:
            self.__update_service(config, service, instance_conf_dir, instance_name, force)
            programs.append(f"{instance_name}_{service.config_type}_{service.service_type}_{service.service_name}")

        group_conf = os.path.join(self.supervisord_conf_dir, f"group_{instance_name}.conf")
        if self._use_instance_name:
            format_vars = {"instance_name": instance_name, "programs": ",".join(programs)}
            contents = SUPERVISORD_GROUP_TEMPLATE.format(**format_vars)
            if self._update_file(group_conf, contents, instance_name, "supervisor group", force):
                self.supervisorctl('reread')
        elif os.path.exists(group_conf):
            os.unlink(group_conf)

    def __process_configs(self, configs, force):
        for config in configs:
            self.__process_config(config, force)
            if not os.path.exists(config.log_dir):
                os.makedirs(config.log_dir)

    def __supervisor_programs(self, config, service_names):
        services = config.get_services(service_names)
        return [SupervisorProgram(config, service, self._use_instance_name) for service in services]

    def __supervisor_program_names(self, config, service_names):
        program_names = []
        for program in self.__supervisor_programs(config, service_names):
            program_names.extend(program.program_names)
        return program_names

    def __op_on_programs(self, op, configs, service_names):
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
            services = config.get_services(service_names)
            for service in services:
                program = self.__supervisor_programs(config, [service.service_name])[0]
                graceful_method = service.graceful_method
                if graceful_method == GracefulMethod.SIGHUP:
                    self.supervisorctl("signal", "SIGHUP", *program.program_names)
                elif graceful_method == GracefulMethod.ROLLING:
                    self.__rolling_restart(config, service, program)
                elif graceful_method != GracefulMethod.NONE:
                    self.supervisorctl("restart", *program.program_names)

    def __rolling_restart(self, config, service, program):
        restart_callbacks = list(partial(self.supervisorctl, "restart", p) for p in program.program_names)
        service.rolling_restart(restart_callbacks)

    def follow(self, configs=None, service_names=None, quiet=False):
        # supervisor has a built-in tail command but it only works on a single log file. `galaxyctl pm tail ...` can be
        # used if desired, though
        if not self.tail:
            gravity.io.exception("`tail` not found on $PATH, please install it")
        log_files = []
        if quiet:
            cmd = [self.tail, "-f", self.log_file]
            tail_popen = subprocess.Popen(cmd)
            tail_popen.wait()
        else:
            for config in configs:
                log_dir = config.log_dir
                programs = self.__supervisor_programs(config, service_names)
                for program in programs:
                    log_files.extend(os.path.join(log_dir, f) for f in program.log_file_names)
            cmd = [self.tail, "-f"] + log_files
            tail_popen = subprocess.Popen(cmd)
            tail_popen.wait()

    def start(self, configs=None, service_names=None):
        self.update(configs=configs)
        self.__supervisord()
        self.__op_on_programs("start", configs, service_names)
        self.supervisorctl("status")

    def stop(self, configs=None, service_names=None):
        self.__op_on_programs("stop", configs, service_names)
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
        self.update(configs=configs)
        if not self.__supervisord_is_running():
            self.__supervisord()
            gravity.io.warn("supervisord was not previously running; it has been started, so the 'restart' command has been ignored")
        else:
            self.__op_on_programs("restart", configs, service_names)

    def graceful(self, configs=None, service_names=None):
        self.update(configs=configs)
        if not self.__supervisord_is_running():
            self.__supervisord()
            gravity.io.warn("supervisord was not previously running; it has been started, so the 'graceful' command has been ignored")
        else:
            self.__reload_graceful(configs, service_names)

    def status(self, configs=None, service_names=None):
        # TODO: create our own formatted output
        # supervisor = self.get_supervisor()
        # all_infos = supervisor.getAllProcessInfo()
        self.__op_on_programs("status", configs, service_names)

    def shutdown(self):
        self.supervisorctl("shutdown")
        while self.__supervisord_is_running():
            gravity.io.debug("Waiting for supervisord to terminate")
            time.sleep(0.5)
        gravity.io.info("supervisord has terminated")

    def update(self, configs=None, force=False, clean=False):
        """Add newly defined servers, remove any that are no longer present"""
        self._pre_update(configs, force, clean)
        if not clean:
            self.__process_configs(configs, force)
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
        program_names = [f"{service_name}:{service_name}_{i + instance_number_start}" for i in range(0, instance_count)]
    else:
        program_names = [service_name]

    if instance_name is not None:
        return [f"{instance_name}:{program_name}" for program_name in program_names]
    else:
        return program_names
