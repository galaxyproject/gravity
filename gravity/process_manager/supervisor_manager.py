"""
"""
import errno
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from os.path import exists, join

import click

from gravity.io import error, info, warn
from gravity.process_manager import BaseProcessManager

from supervisor import supervisorctl


supervisord_conf_template = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[unix_http_server]
file = {supervisor_state_dir}/supervisor.sock

[supervisord]
logfile = {supervisor_state_dir}/supervisord.log
pidfile = {supervisor_state_dir}/supervisord.pid
loglevel = info
nodaemon = false

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl = unix://{supervisor_state_dir}/supervisor.sock

[include]
files = {supervisord_conf_dir}/*.d/*.conf {supervisord_conf_dir}/*.conf
"""

supervisord_galaxy_gunicorn_conf_template = """
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;


[program:{program_name}]
command         = gunicorn 'galaxy.webapps.galaxy.fast_factory:factory()' --timeout 300 --pythonpath lib -k galaxy.webapps.galaxy.workers.Worker -b {galaxy_bind_ip}:{galaxy_port}
directory       = {galaxy_root}
process_name    = gunicorn
umask           = {galaxy_umask}
autostart       = true
autorestart     = true
startsecs       = 15
stopwaitsecs    = 65
environment     = GALAXY_CONFIG_FILE={galaxy_conf}
numprocs        = 1
stdout_logfile  = {log_dir}/gunicorn.log
redirect_stderr = true
"""  # noqa: E501

supervisord_galaxy_standalone_conf_template = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[program:{program_name}]
command         = python ./lib/galaxy/main.py -c {galaxy_conf} --server-name={server_name} --pid-file={supervisor_state_dir}/{program_name}.pid
process_name    = {config_type}_{server_name}
directory       = {galaxy_root}
autostart       = false
autorestart     = true
startsecs       = 20
numprocs        = 1
stdout_logfile  = {log_dir}/{program_name}.log
redirect_stderr = true
"""

supervisord_galaxy_instance_group_conf_template = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[group:{instance_name}]
programs = {programs}
"""


def which(file):
    # http://stackoverflow.com/questions/5226958/which-equivalent-function-in-python
    if os.path.exists(os.path.dirname(sys.executable) + "/" + file):
        return os.path.dirname(sys.executable) + "/" + file
    for path in os.environ["PATH"].split(":"):
        if os.path.exists(path + "/" + file):
            return path + "/" + file

    return None


class SupervisorProcessManager(BaseProcessManager):
    def __init__(self, state_dir=None, start_daemon=True):
        super(SupervisorProcessManager, self).__init__(state_dir=state_dir)
        self.supervisord_exe = which("supervisord")
        self.supervisor_state_dir = join(self.state_dir, "supervisor")
        self.supervisord_conf_path = join(self.supervisor_state_dir, "supervisord.conf")
        self.supervisord_conf_dir = join(self.supervisor_state_dir, "supervisord.conf.d")

        if not exists(self.supervisord_conf_dir):
            os.makedirs(self.supervisord_conf_dir)

        if start_daemon:
            self.__supervisord()

    def __supervisord(self):
        format_vars = {"supervisor_state_dir": self.supervisor_state_dir, "supervisord_conf_dir": self.supervisord_conf_dir}
        supervisord_pid_path = join(self.supervisor_state_dir, "supervisord.pid")

        try:
            assert exists(supervisord_pid_path)
            os.kill(int(open(supervisord_pid_path).read()), 0)
        except Exception:
            # any time that supervisord is not running, let's rewrite supervisord.conf
            open(self.supervisord_conf_path, "w").write(supervisord_conf_template.format(**format_vars))
            popen = subprocess.Popen([self.supervisord_exe, "-c", self.supervisord_conf_path], env=os.environ)
            rc = popen.poll()
            if rc:
                error("supervisord exited with code %d" % rc)

    def __get_supervisor(self):
        """Return the supervisor proxy object

        Should probably use this more rather than supervisorctl directly
        """
        options = supervisorctl.ClientOptions()
        options.realize(args=["-c", self.supervisord_conf_path])
        return supervisorctl.Controller(options).get_supervisor()

    def __update_service(self, config_file, config, attribs, service, instance_conf_dir, instance_name):
        format_vars = {
            "log_dir": attribs["log_dir"],
            "config_type": service["config_type"],
            "server_name": service["service_name"],
            # TODO: Make config variables
            "galaxy_bind_ip": service.get("galaxy_bind_ip", "localhost"),
            "galaxy_port": service.get("galaxy_port", "8080"),
            "galaxy_umask": service.get("umask", "022"),
            "program_name": f"{instance_name}_{service['config_type']}_{service['service_type']}_{service['service_name']}",
            "galaxy_conf": config_file,
            "galaxy_root": attribs["galaxy_root"],
            "supervisor_state_dir": self.supervisor_state_dir,
        }
        conf = join(instance_conf_dir, f"{service['config_type']}_{service['service_type']}_{service['service_name']}.conf")

        if not exists(attribs["log_dir"]):
            os.makedirs(attribs["log_dir"])

        if service["service_type"] == "gunicorn":
            template = supervisord_galaxy_gunicorn_conf_template
        elif service["service_type"] == "standalone":
            template = supervisord_galaxy_standalone_conf_template
        else:
            raise Exception(f"Unknown service type: {service['service_type']}")

        with open(conf, "w") as out:
            out.write(template.format(**format_vars))

    def _process_config_changes(self, configs, meta_changes):
        # remove the services of any configs which have been removed
        for config in meta_changes["remove_configs"].values():
            instance_name = config.instance_name
            instance_conf_dir = join(self.supervisord_conf_dir, f"{instance_name}.d")
            for service in config["services"]:
                info("Removing service %s:%s_%s_%s", instance_name, service.config_type, service.service_type, service.service_name)
                conf = join(instance_conf_dir, f"{service.config_type}_{service.service_type}_{service.service_name}.conf")
                if exists(conf):
                    os.unlink(conf)

        # update things for existing or new configs
        for config_file, config in configs.items():
            instance_name = config["instance_name"]
            attribs = config["attribs"]
            update_all_configs = False

            # config attribs have changed (galaxy_root, virtualenv, etc.)
            if "update_attribs" in config:
                info(f"Updating all dependent services of config {config_file} due to changes")
                attribs = config["update_attribs"]
                update_all_configs = True

            # instance name has changed, so supervisor group config must change
            if "update_instance_name" in config:
                instance_name = config["update_instance_name"]
                info("Creating new instance for name change: %s -> %s", config["instance_name"], instance_name)
                update_all_configs = True

            # always attempt to make the config dir
            instance_conf_dir = join(self.supervisord_conf_dir, f"{instance_name}.d")
            try:
                os.makedirs(instance_conf_dir)
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    raise

            if update_all_configs:
                for service in config["services"]:
                    info("Updating service %s:%s_%s_%s", instance_name, service["config_type"], service["service_type"], service["service_name"])
                    self.__update_service(config_file, config, attribs, service, instance_conf_dir, instance_name)

            # new services
            if "update_services" in config:
                for service in config["update_services"]:
                    info("Creating service %s:%s_%s_%s", instance_name, service["config_type"], service["service_type"], service["service_name"])
                    self.__update_service(config_file, config, attribs, service, instance_conf_dir, instance_name)

            # deleted services
            if "remove_services" in config:
                for service in config["remove_services"]:
                    info("Removing service %s:%s_%s_%s", instance_name, service["config_type"], service["service_type"], service["service_name"])
                    conf = join(instance_conf_dir, f"{service['config_type']}_{service['service_type']}_{service['service_name']}.conf")
                    if exists(conf):
                        os.unlink(conf)

            # sanity check, make sure everything that should exist does exist
            for service in config["services"]:
                conf = join(instance_conf_dir, f"{service['config_type']}_{service['service_type']}_{service['service_name']}.conf")
                if service not in config.get("remove_services", []) and not exists(conf):
                    self.__update_service(config_file, config, attribs, service, instance_conf_dir, instance_name)
                    warn(f"Missing service config recreated: {conf}")

        # all configs referencing an instance name have been removed (or their
        # instance names have changed), nuke the group
        for instance_name in meta_changes["remove_instances"]:
            info("Removing instance %s", instance_name)
            instance_conf_dir = join(self.supervisord_conf_dir, f"{instance_name}.d")
            if exists(instance_conf_dir):
                shutil.rmtree(instance_conf_dir)
            conf = join(self.supervisord_conf_dir, f"group_{instance_name}.conf")
            if exists(conf):
                os.unlink(join(conf))

        # persist to the state file
        self.config_manager.register_config_changes(configs, meta_changes)

        # now we can create/update the instance group
        for instance_name in meta_changes["changed_instances"]:
            programs = []
            for service in self.config_manager.get_registered_services():
                if service["instance_name"] == instance_name and service["service_type"] != "uwsgi":
                    programs.append(f"{instance_name}_{service['config_type']}_{service['service_type']}_{service['service_name']}")
            conf = join(self.supervisord_conf_dir, f"group_{instance_name}.conf")
            if programs:
                format_vars = {"instance_conf_dir": instance_conf_dir, "instance_name": instance_name, "programs": ",".join(programs)}
                open(conf, "w").write(supervisord_galaxy_instance_group_conf_template.format(**format_vars))
            else:
                # no programs for the group, so it should be removed
                if exists(conf):
                    os.unlink(conf)

    def __start_stop(self, op, instance_names):
        self.update()
        instance_names, unknown_instance_names = self.get_instance_names(instance_names)
        for instance_name in instance_names:
            self.supervisorctl(op, f"{instance_name}:*")
            for service in self.config_manager.get_instance_services(instance_name):
                if service["service_type"] == "uwsgi":
                    self.supervisorctl(op, f"{instance_name}_{service['config_type']}_{service['service_name']}")
        # shortcut for just passing service names directly
        for name in unknown_instance_names:
            self.supervisorctl(op, name)

    def __reload_graceful(self, op, instance_names):
        self.update()
        for instance_name in self.get_instance_names(instance_names)[0]:
            if op == "reload":
                # restart everything but uwsgi
                self.supervisorctl("restart", f"{instance_name}:*")
            for service in self.config_manager.get_instance_services(instance_name):
                service_name = f"{instance_name}_{service.config_type}_{service.service_name}"
                group_service_name = f"{instance_name}:{service.config_type}_{service.service_name}"
                if service["service_type"] == "uwsgi":
                    procinfo = self.__get_supervisor().getProcessInfo(service_name)
                    # restart uwsgi
                    try:
                        os.kill(procinfo["pid"], signal.SIGHUP)
                        click.echo(f"{group_service_name}: sent HUP signal")
                    except Exception as exc:
                        warn("Attempt to reload %s failed: %s", service_name, exc)
                # graceful restarts
                elif op == "graceful" and service["service_type"] == "standalone":
                    self.supervisorctl("restart", group_service_name)
                elif op == "graceful" and service["service_type"] == "paste":
                    self.supervisorctl("restart", group_service_name)
                    url = "http://localhost:%d/" % service.paste_port
                    click.echo(f"{service_name}: waiting until {url} is accepting requests", end="")
                    while True:
                        try:
                            r = urllib.request.urlopen(url, None, 5)
                            assert r.getcode() == 200, f"{url} returned HTTP code: {r.getcode()}"
                            click.echo(" OK")
                            break
                        except AssertionError as exc:
                            click.echo()
                            error(exc)
                            return
                        except Exception:
                            click.echo(".", nl=False)
                            sys.stdout.flush()
                            time.sleep(1)

    def start(self, instance_names):
        super(SupervisorProcessManager, self).start(instance_names)
        self.__start_stop("start", instance_names)

    def stop(self, instance_names):
        self.__start_stop("stop", instance_names)

    def restart(self, instance_names):
        self.__start_stop("restart", instance_names)

    def reload(self, instance_names):
        self.__reload_graceful("reload", instance_names)

    def graceful(self, instance_names):
        self.__reload_graceful("graceful", instance_names)

    def status(self):
        # TODO: create our own formatted output
        # supervisor = self.get_supervisor()
        # all_infos = supervisor.getAllProcessInfo()
        self.supervisorctl("status")

    def shutdown(self):
        self.supervisorctl("shutdown")

    def update(self):
        """Add newly defined servers, remove any that are no longer present"""
        configs, meta_changes = self.config_manager.determine_config_changes()
        self._process_config_changes(configs, meta_changes)
        self.supervisorctl("update")

    def supervisorctl(self, *args, **kwargs):
        try:
            supervisorctl.main(args=["-c", self.supervisord_conf_path] + list(args))
        except SystemExit as e:
            if e.code == 0:
                pass
            else:
                raise
