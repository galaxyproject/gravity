"""
"""
import errno
import os
import shlex
import shutil
import subprocess
import time
from os.path import exists, join

from gravity.io import debug, error, info, warn
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

# TODO: with more templating you only need one of these
SUPERVISORD_SERVICE_TEMPLATES = {}
SUPERVISORD_SERVICE_TEMPLATES["unicornherder"] = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[program:{program_name}]
command         = {command}
directory       = {galaxy_root}
umask           = {galaxy_umask}
autostart       = true
autorestart     = true
startsecs       = 15
stopwaitsecs    = 65
environment     = {environment}
numprocs        = 1
stdout_logfile  = {log_file}
redirect_stderr = true
{process_name_opt}
"""

SUPERVISORD_SERVICE_TEMPLATES["gunicorn"] = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[program:{program_name}]
command         = {command}
directory       = {galaxy_root}
umask           = {galaxy_umask}
autostart       = true
autorestart     = true
startsecs       = 15
stopwaitsecs    = 65
environment     = {environment}
numprocs        = 1
stdout_logfile  = {log_file}
redirect_stderr = true
{process_name_opt}
"""

SUPERVISORD_SERVICE_TEMPLATES["celery"] = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[program:{program_name}]
command         = {command}
directory       = {galaxy_root}
umask           = {galaxy_umask}
autostart       = true
autorestart     = true
startsecs       = 10
stopwaitsecs    = 10
environment     = {environment}
numprocs        = 1
stdout_logfile  = {log_file}
redirect_stderr = true
{process_name_opt}
"""

SUPERVISORD_SERVICE_TEMPLATES["celery-beat"] = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[program:{program_name}]
command         = {command}
directory       = {galaxy_root}
umask           = {galaxy_umask}
autostart       = true
autorestart     = true
startsecs       = 10
stopwaitsecs    = 10
environment     = {environment}
numprocs        = 1
stdout_logfile  = {log_file}
redirect_stderr = true
{process_name_opt}
"""

SUPERVISORD_SERVICE_TEMPLATES["tusd"] = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;
[program:{program_name}]
command         = {command}
directory       = {galaxy_root}
umask           = {galaxy_umask}
autostart       = true
autorestart     = true
startsecs       = 10
stopwaitsecs    = 10
environment     = {environment}
numprocs        = 1
stdout_logfile  = {log_file}
redirect_stderr = true
{process_name_opt}
"""

SUPERVISORD_SERVICE_TEMPLATES["gx-it-proxy"] = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[program:{program_name}]
command         = {command}
directory       = {galaxy_root}
umask           = {galaxy_umask}
autostart       = true
autorestart     = true
startsecs       = 10
stopwaitsecs    = 10
environment     = {environment}
numprocs        = 1
stdout_logfile  = {log_file}
redirect_stderr = true
{process_name_opt}
"""

SUPERVISORD_SERVICE_TEMPLATES["standalone"] = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[program:{program_name}]
command         = {command}
directory       = {galaxy_root}
autostart       = true
autorestart     = true
startsecs       = 20
stopwaitsecs    = 65
environment     = {environment}
numprocs        = 1
stdout_logfile  = {log_file}
redirect_stderr = true
{process_name_opt}
"""

SUPERVISORD_GROUP_TEMPLATE = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[group:{instance_name}]
programs = {programs}
"""


class SupervisorProcessManager(BaseProcessManager):

    name = ProcessManager.supervisor

    def __init__(self, state_dir=None, config_manager=None, start_daemon=True, foreground=False):
        super().__init__(state_dir=state_dir, config_manager=config_manager)
        self.supervisord_exe = which("supervisord")
        self.supervisor_state_dir = join(self.state_dir, "supervisor")
        self.supervisord_conf_path = join(self.supervisor_state_dir, "supervisord.conf")
        self.supervisord_conf_dir = join(self.supervisor_state_dir, "supervisord.conf.d")
        self.supervisord_pid_path = join(self.supervisor_state_dir, "supervisord.pid")
        self.supervisord_sock_path = os.environ.get("SUPERVISORD_SOCKET", join(self.supervisor_state_dir, "supervisor.sock"))
        self.__supervisord_popen = None
        self.foreground = foreground

        if not exists(self.supervisord_conf_dir):
            os.makedirs(self.supervisord_conf_dir)

        if start_daemon:
            self.__supervisord()

    @property
    def use_group(self):
        return not self.config_manager.single_instance

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
                error("supervisord exited with code %d" % rc)
            # FIXME: don't wait forever
            while not exists(self.supervisord_pid_path) or not exists(self.supervisord_sock_path):
                debug(f"Waiting for {self.supervisord_pid_path}")
                time.sleep(0.5)

    def __get_supervisor(self):
        """Return the supervisor proxy object

        Should probably use this more rather than supervisorctl directly
        """
        options = supervisorctl.ClientOptions()
        options.realize(args=["-c", self.supervisord_conf_path])
        return supervisorctl.Controller(options).get_supervisor()

    def terminate(self):
        if self.foreground:
            # if running in foreground, if terminate is called, then supervisord should've already received a SIGINT
            self.__supervisord_popen and self.__supervisord_popen.wait()

    def _service_program_name(self, instance_name, service):
        if self.use_group:
            return f"{instance_name}_{service['config_type']}_{service['service_type']}_{service['service_name']}"
        else:
            return service["service_name"]

    def __update_service(self, config_file, config, attribs, service, instance_conf_dir, instance_name):
        if self.use_group:
            process_name_opt = f"process_name    = {service['service_name']}"
        else:
            process_name_opt = ""

        program_name = self._service_program_name(instance_name, service)

        # used by the "standalone" service type
        attach_to_pool_opt = ""
        server_pools = service.get("server_pools")
        if server_pools:
            _attach_to_pool_opt = " ".join(f"--attach-to-pool={server_pool}" for server_pool in server_pools)
            # Insert a single leading space
            attach_to_pool_opt = f" {_attach_to_pool_opt}"

        virtualenv_dir = attribs.get("virtualenv")
        virtualenv_bin = f'{os.path.join(virtualenv_dir, "bin")}{os.path.sep}' if virtualenv_dir else ""
        gunicorn_options = attribs["gunicorn"].copy()
        gunicorn_options["preload"] = "--preload" if gunicorn_options["preload"] else ""

        format_vars = {
            "log_dir": attribs["log_dir"],
            "log_file": self._service_log_file(attribs["log_dir"], program_name),
            "config_type": service["config_type"],
            "server_name": service["service_name"],
            "attach_to_pool_opt": attach_to_pool_opt,
            "gunicorn": gunicorn_options,
            "celery": attribs["celery"],
            "galaxy_infrastructure_url": attribs["galaxy_infrastructure_url"],
            "tusd": attribs["tusd"],
            "gx_it_proxy": attribs["gx_it_proxy"],
            "galaxy_umask": service.get("umask", "022"),
            "program_name": program_name,
            "process_name_opt": process_name_opt,
            "galaxy_conf": config_file,
            "galaxy_root": config["galaxy_root"],
            "virtualenv_bin": virtualenv_bin,
            "supervisor_state_dir": self.supervisor_state_dir,
            "state_dir": self.state_dir,
        }
        format_vars["command"] = service.command_template.format(**format_vars)
        conf = join(instance_conf_dir, f"{service['config_type']}_{service['service_type']}_{service['service_name']}.conf")

        # FIXME: this should be done once, not on every service
        if not exists(attribs["log_dir"]):
            os.makedirs(attribs["log_dir"])

        template = SUPERVISORD_SERVICE_TEMPLATES.get(service["service_type"])
        if not template:
            raise Exception(f"Unknown service type: {service['service_type']}")

        environment = self._service_environment(service, attribs)
        if virtualenv_bin and service.add_virtualenv_to_path:
            path = environment.get("PATH", "%(ENV_PATH)s")
            environment["PATH"] = ":".join([virtualenv_bin, path])
        format_vars["environment"] = ",".join("{}={}".format(k, shlex.quote(v.format(**format_vars))) for k, v in environment.items())

        contents = template.format(**format_vars)
        service_name = self._service_program_name(instance_name, service)
        self._update_file(conf, contents, service_name, "service")

        return conf

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

    def _process_config(self, config):
        """Perform necessary supervisor config updates as per current Galaxy/Gravity configuration.

        Does not call ``supervisorctl update``.
        """
        instance_name = config["instance_name"]
        attribs = config["attribs"]
        config_file = config.__file__
        instance_conf_dir = join(self.supervisord_conf_dir, f"{instance_name}.d")
        intended_configs = set()
        try:
            os.makedirs(instance_conf_dir)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise

        programs = []
        for service in config["services"]:
            intended_configs.add(self.__update_service(config_file, config, attribs, service, instance_conf_dir, instance_name))
            programs.append(f"{instance_name}_{service['config_type']}_{service['service_type']}_{service['service_name']}")

        # TODO: test group mode
        group_conf = join(self.supervisord_conf_dir, f"group_{instance_name}.conf")
        if self.use_group:
            format_vars = {"instance_name": instance_name, "programs": ",".join(programs)}
            contents = SUPERVISORD_GROUP_TEMPLATE.format(**format_vars)
            self._update_file(group_conf, contents, instance_name, "supervisor group")
        elif os.path.exists(group_conf):
            os.unlink(group_conf)

        present_configs = set([join(instance_conf_dir, f) for f in os.listdir(instance_conf_dir)])

        for file in (present_configs - intended_configs):
            info("Removing service config %s", file)
            os.unlink(file)

    def _remove_invalid_configs(self):
        valid_names = [c.instance_name for c in self.config_manager.get_registered_configs()]
        valid_instance_dirs = [f"{name}.d" for name in valid_names]
        valid_group_confs = []
        if self.use_group:
            valid_group_confs = [f"group_{name}.conf" for name in valid_names]
        for entry in os.listdir(self.supervisord_conf_dir):
            path = join(self.supervisord_conf_dir, entry)
            if entry.startswith("group_") and entry not in valid_group_confs:
                info(f"Removing group config {path}")
                os.unlink(path)
            elif entry.endswith(".d") and entry not in valid_instance_dirs:
                info(f"Removing instance directory {path}")
                shutil.rmtree(path)

    def __start_stop(self, op, configs, service_names):
        self.update(configs=configs)
        for config in configs:
            if service_names:
                services = [s for s in config.services if s["service_name"] in service_names]
                for service in services:
                    program_name = self._service_program_name(config.instance_name, service)
                    self.supervisorctl(op, program_name)
            else:
                target = f"{config.instance_name}:*" if self.use_group else "all"
                self.supervisorctl(op, target)

    def __reload_graceful(self, op, configs, service_names):
        self.update(configs=configs)
        for config in configs:
            if service_names:
                services = [s for s in config.services if s["service_name"] in service_names]
            else:
                services = config.services
            for service in services:
                program_name = self._service_program_name(config.instance_name, service)
                if service.graceful_method == GracefulMethod.SIGHUP:
                    self.supervisorctl("signal", "SIGHUP", program_name)
                else:
                    self.supervisorctl("restart", program_name)

    def start(self, configs=None, service_names=None):
        self.__start_stop("start", configs, service_names)
        self.supervisorctl("status")

    def stop(self, configs=None, service_names=None):
        self.__start_stop("stop", configs, service_names)
        # Exit supervisor if all processes are stopped
        supervisor = self.__get_supervisor()
        proc_infos = supervisor.getAllProcessInfo()
        if all([i["state"] == 0 for i in proc_infos]):
            info("All processes stopped, supervisord will exit")
            self.shutdown()
        else:
            info("Not all processes stopped, supervisord not shut down (hint: see `galaxyctl status`)")

    def restart(self, configs=None, service_names=None):
        self.__start_stop("restart", configs, service_names)

    def reload(self, configs=None, service_names=None):
        self.__reload_graceful("reload", configs, service_names)

    def graceful(self, configs=None, service_names=None):
        self.__reload_graceful("graceful", configs, service_names)

    def status(self, configs=None, service_names=None):
        # TODO: create our own formatted output
        # supervisor = self.get_supervisor()
        # all_infos = supervisor.getAllProcessInfo()
        self.supervisorctl("status")

    def shutdown(self):
        self.supervisorctl("shutdown")
        while self.__supervisord_is_running():
            debug("Waiting for supervisord to terminate")
            time.sleep(0.5)
        info("supervisord has terminated")

    def update(self, configs=None, force=False, **kwargs):
        """Add newly defined servers, remove any that are no longer present"""
        if force:
            shutil.rmtree(self.supervisord_conf_dir)
            os.makedirs(self.supervisord_conf_dir)
        for config in configs:
            self._process_config(config)
        self._remove_invalid_configs()
        # only need to update if supervisord is running, otherwise changes will be picked up at next start
        if self.__supervisord_is_running():
            self.supervisorctl("update")

    def supervisorctl(self, *args, **kwargs):
        if not self.__supervisord_is_running():
            warn("supervisord is not running")
            return
        try:
            debug("Calling supervisorctl with args: %s", list(args))
            supervisorctl.main(args=["-c", self.supervisord_conf_path] + list(args))
        except SystemExit as e:
            # supervisorctl.main calls sys.exit(), so we catch that
            if e.code == 0:
                pass
            else:
                raise

    pm = supervisorctl
