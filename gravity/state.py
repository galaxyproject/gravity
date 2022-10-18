""" Classes to represent and manipulate gravity's stored configuration and
state data.
"""
import enum
import errno
import os
import sys
from collections import defaultdict

import yaml

from gravity import __version__
from gravity.io import debug
from gravity.util import AttributeDict


GALAXY_YML_SAMPLE_PATH = "lib/galaxy/config/sample/galaxy.yml.sample"
DEFAULT_GALAXY_ENVIRONMENT = {
    "PYTHONPATH": "lib",
    "GALAXY_CONFIG_FILE": "{galaxy_conf}",
}
CELERY_BEAT_DB_FILENAME = "celery-beat-schedule"


class GracefulMethod(enum.Enum):
    DEFAULT = 0
    SIGHUP = 1


class Service(AttributeDict):
    service_type = "service"
    service_name = "_default_"
    environment_from = None
    settings_from = None
    default_environment = {}
    add_virtualenv_to_path = False
    graceful_method = GracefulMethod.DEFAULT
    command_arguments = {}

    def __init__(self, *args, **kwargs):
        super(Service, self).__init__(*args, **kwargs)
        if "service_type" not in kwargs:
            self["service_type"] = self.__class__.service_type
        if "service_name" not in kwargs:
            self["service_name"] = self.__class__.service_name

    def __eq__(self, other):
        return self["config_type"] == other["config_type"] and self["service_type"] == other["service_type"] and self["service_name"] == other["service_name"]

    def full_match(self, other):
        return set(self.keys()) == set(other.keys()) and all([self[k] == other[k] for k in self if not k.startswith("_")])

    def get_graceful_method(self, attribs):
        return self.graceful_method

    def get_environment(self):
        return self.default_environment.copy()

    def get_command_arguments(self, attribs, format_vars):
        rval = {}
        for setting, value in attribs.get(self.settings_from or self.service_type, {}).items():
            if setting in self.command_arguments:
                # FIXME: this truthiness testing of value is probably not the best
                if value:
                    rval[setting] = self.command_arguments[setting].format(**format_vars)
                else:
                    rval[setting] = ""
            else:
                rval[setting] = value
        return rval

    def get_settings(self, attribs, format_vars):
        return attribs[self.settings_from or self.service_type].copy()


class GalaxyGunicornService(Service):
    service_type = "gunicorn"
    service_name = "gunicorn"
    default_environment = DEFAULT_GALAXY_ENVIRONMENT
    command_arguments = {
        "preload": "--preload"
    }
    command_template = "{virtualenv_bin}gunicorn 'galaxy.webapps.galaxy.fast_factory:factory()'" \
                       " --timeout {settings[timeout]}" \
                       " --pythonpath lib" \
                       " -k galaxy.webapps.galaxy.workers.Worker" \
                       " -b {settings[bind]}" \
                       " --workers={settings[workers]}" \
                       " --config python:galaxy.web_stack.gunicorn_config" \
                       " {command_arguments[preload]}" \
                       " {settings[extra_args]}"

    # TODO: services should maybe have access to settings or attribs, and should maybe template their own command lines
    def get_graceful_method(self, attribs):
        if attribs["gunicorn"].get("preload"):
            return GracefulMethod.DEFAULT
        else:
            return GracefulMethod.SIGHUP

    def get_environment(self):
        # Works around https://github.com/galaxyproject/galaxy/issues/11821
        environment = self.default_environment.copy()
        if sys.platform == 'darwin':
            environment["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        return environment


class GalaxyUnicornHerderService(Service):
    service_type = "unicornherder"
    service_name = "unicornherder"
    environment_from = "gunicorn"
    settings_from = "gunicorn"
    graceful_method = GracefulMethod.SIGHUP
    default_environment = DEFAULT_GALAXY_ENVIRONMENT
    command_arguments = GalaxyGunicornService.command_arguments
    command_template = "{virtualenv_bin}unicornherder --pidfile {state_dir}/{program_name}.pid --" \
                       " 'galaxy.webapps.galaxy.fast_factory:factory()'" \
                       " --timeout {settings[timeout]}" \
                       " --pythonpath lib" \
                       " -k galaxy.webapps.galaxy.workers.Worker" \
                       " -b {settings[bind]}" \
                       " --workers={settings[workers]}" \
                       " --config python:galaxy.web_stack.gunicorn_config" \
                       " {command_arguments[preload]}" \
                       " {settings[extra_args]}"

    def get_environment(self):
        environment = self.default_environment.copy()
        if sys.platform == 'darwin':
            environment["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        environment["GALAXY_CONFIG_LOG_DESTINATION"] = "{log_dir}/gunicorn.log"
        return environment


class GalaxyCeleryService(Service):
    service_type = "celery"
    service_name = "celery"
    default_environment = DEFAULT_GALAXY_ENVIRONMENT
    command_template = "{virtualenv_bin}celery" \
                       " --app galaxy.celery worker" \
                       " --concurrency {settings[concurrency]}" \
                       " --loglevel {settings[loglevel]}" \
                       " --pool {settings[pool]}" \
                       " --queues {settings[queues]}" \
                       " {settings[extra_args]}"


class GalaxyCeleryBeatService(Service):
    service_type = "celery-beat"
    service_name = "celery-beat"
    settings_from = "celery"
    default_environment = DEFAULT_GALAXY_ENVIRONMENT
    command_template = "{virtualenv_bin}celery" \
                       " --app galaxy.celery" \
                       " beat" \
                       " --loglevel {settings[loglevel]}" \
                       " --schedule {state_dir}/" + CELERY_BEAT_DB_FILENAME


class GalaxyGxItProxyService(Service):
    service_type = "gx-it-proxy"
    service_name = "gx-it-proxy"
    default_environment = {
        "npm_config_yes": "true",
    }
    # the npx shebang is $!/usr/bin/env node, so $PATH has to be correct
    add_virtualenv_to_path = True
    command_arguments = {
        "forward_ip": "--forwardIP {settings[forward_ip]}",
        "forward_port": "--forwardPort {settings[forward_port]}",
        "reverse_proxy": "--reverseProxy",
    }
    command_template = "{virtualenv_bin}npx gx-it-proxy --ip {settings[ip]} --port {settings[port]}" \
                       " --sessions {settings[sessions]} {settings[verbose]}" \
                       " {command_arguments[forward_ip]} {command_arguments[forward_port]}" \
                       " {command_arguments[reverse_proxy]}"


class GalaxyTUSDService(Service):
    service_type = "tusd"
    service_name = "tusd"
    command_template = "{settings[tusd_path]} -host={settings[host]} -port={settings[port]}" \
                       " -upload-dir={settings[upload_dir]}" \
                       " -hooks-http={galaxy_infrastructure_url}/api/upload/hooks" \
                       " -hooks-http-forward-headers=X-Api-Key,Cookie {settings[extra_args]}" \
                       " -hooks-enabled-events {settings[hooks_enabled_events]}"


class GalaxyStandaloneService(Service):
    service_type = "standalone"
    service_name = "standalone"
    default_start_timeout = 20
    default_stop_timeout = 65
    command_template = "{virtualenv_bin}python ./lib/galaxy/main.py -c {galaxy_conf} --server-name={server_name}" \
                       " {command_arguments[attach_to_pool]} {command_arguments[pid_file]}"

    def get_environment(self):
        return self.get("environment") or {}

    def get_command_arguments(self, attribs, format_vars):
        # full override because standalone doesn't have settings
        command_arguments = {
            "attach_to_pool": "",
            "pid_file": " --pid-file={state_dir}/{program_name}.pid".format(**format_vars),
        }
        server_pools = self.get("server_pools")
        if server_pools:
            _attach_to_pool = " ".join(f"--attach-to-pool={server_pool}" for server_pool in server_pools)
            # Insert a single leading space
            command_arguments["attach_to_pool"] = f" {_attach_to_pool}"
        return command_arguments

    def get_settings(self, attribs, format_vars):
        return {
            "start_timeout": self.start_timeout or self.default_start_timeout,
            "stop_timeout": self.stop_timeout or self.default_stop_timeout,
        }


class ConfigFile(AttributeDict):
    persist_keys = (
        "config_type",
        "instance_name",
        "galaxy_root",
    )

    def __init__(self, *args, **kwargs):
        super(ConfigFile, self).__init__(*args, **kwargs)
        services = []
        for service in self.get("services", []):
            service_class = SERVICE_CLASS_MAP.get(service["service_type"], Service)
            services.append(service_class(**service))
        self.services = services

    @property
    def defaults(self):
        return {
            "process_manager": self["process_manager"],
            "instance_name": self["instance_name"],
            "galaxy_root": self["galaxy_root"],
            "log_dir": self["attribs"]["log_dir"],
            "gunicorn":  self.gunicorn_config,
        }

    @property
    def gunicorn_config(self):
        # We used to store bind_address and bind_port instead of a gunicorn config key, so restore from here
        gunicorn = self["attribs"].get("gunicorn")
        if not gunicorn and 'bind_address' in self["attribs"]:
            return {'bind': f'{self["attribs"]["bind_address"]}:{self["attribs"]["bind_port"]}'}
        return gunicorn


class GravityState(AttributeDict):
    init_contents = {
        "gravity_version": __version__,
        "config_files": {},
    }


class GravityStateDict(GravityState):
    contents = None

    @classmethod
    def open(cls, name):
        if GravityStateDict.contents is None:
            GravityStateDict.contents = cls(**GravityState.init_contents)
        return GravityStateDict.contents

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass


class GravityStateFile(GravityState):
    @classmethod
    def open(cls, name):
        try:
            s = cls.loads(open(name).read())
        except (OSError, IOError) as exc:
            if exc.errno == errno.ENOENT:
                debug(f"Initializing Gravity config state: {name}")
                yaml.dump(GravityState.init_contents, open(name, "w"))
                s = cls(**GravityState.init_contents)
        s._name = name
        return s

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        normalized_state = defaultdict(dict)
        for config_file, config_dict in self["config_files"].items():
            # resolve path, so we always deal with absolute and symlink-resolved paths
            config_file = os.path.realpath(config_file)
            if config_file.endswith(GALAXY_YML_SAMPLE_PATH):
                root_dir = config_dict['galaxy_root']
                non_sample_path = os.path.join(root_dir, 'config', 'galaxy.yml')
                if os.path.exists(non_sample_path):
                    config_file = non_sample_path
            normalized_state["config_files"][config_file] = ConfigFile(config_dict)
        self.update(normalized_state)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self["gravity_version"] = __version__
        with open(self._name, "w") as fh:
            self.dump(fh)

    def set_name(self, name):
        self._name = name


def service_for_service_type(service_type):
    try:
        return SERVICE_CLASS_MAP[service_type]
    except KeyError:
        raise RuntimeError(f"Unknown service type: {service_type}")


def gravity_state(state_path):
    if state_path:
        return GravityStateFile
    else:
        return GravityStateDict


# TODO: better to pull this from __class__.service_type
SERVICE_CLASS_MAP = {
    "gunicorn": GalaxyGunicornService,
    "unicornherder": GalaxyUnicornHerderService,
    "celery": GalaxyCeleryService,
    "celery-beat": GalaxyCeleryBeatService,
    "gx-it-proxy": GalaxyGxItProxyService,
    "tusd": GalaxyTUSDService,
    "standalone": GalaxyStandaloneService,
}

VALID_SERVICE_NAMES = set(SERVICE_CLASS_MAP)
