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
    default_environment = {}
    add_virtualenv_to_path = False
    graceful_method = GracefulMethod.DEFAULT

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

    def get_environment(self):
        return self.default_environment.copy()


class GalaxyGunicornService(Service):
    service_type = "gunicorn"
    service_name = "gunicorn"
    default_environment = DEFAULT_GALAXY_ENVIRONMENT
    graceful_method = GracefulMethod.SIGHUP
    command_template = "{virtualenv_bin}gunicorn 'galaxy.webapps.galaxy.fast_factory:factory()'" \
                       " --timeout {gunicorn[timeout]}" \
                       " --pythonpath lib" \
                       " -k galaxy.webapps.galaxy.workers.Worker" \
                       " -b {gunicorn[bind]}" \
                       " --workers={gunicorn[workers]}" \
                       " --config python:galaxy.web_stack.gunicorn_config" \
                       " {gunicorn[preload]}" \
                       " {gunicorn[extra_args]}"

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
    graceful_method = GracefulMethod.SIGHUP
    default_environment = DEFAULT_GALAXY_ENVIRONMENT
    command_template = "{virtualenv_bin}unicornherder --pidfile {supervisor_state_dir}/{program_name}.pid --" \
                       " 'galaxy.webapps.galaxy.fast_factory:factory()'" \
                       " --timeout {gunicorn[timeout]}" \
                       " --pythonpath lib" \
                       " -k galaxy.webapps.galaxy.workers.Worker" \
                       " -b {gunicorn[bind]}" \
                       " --workers={gunicorn[workers]}" \
                       " --config python:galaxy.web_stack.gunicorn_config" \
                       " {gunicorn[preload]}" \
                       " {gunicorn[extra_args]}"

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
                       " --concurrency {celery[concurrency]}" \
                       " --loglevel {celery[loglevel]}" \
                       " --pool {celery[pool]}" \
                       " --queues {celery[queues]}" \
                       " {celery[extra_args]}"


class GalaxyCeleryBeatService(Service):
    service_type = "celery-beat"
    service_name = "celery-beat"
    default_environment = DEFAULT_GALAXY_ENVIRONMENT
    command_template = "{virtualenv_bin}celery" \
                       " --app galaxy.celery" \
                       " beat" \
                       " --loglevel {celery[loglevel]}" \
                       " --schedule {state_dir}/" + CELERY_BEAT_DB_FILENAME


class GalaxyGxItProxyService(Service):
    service_type = "gx-it-proxy"
    service_name = "gx-it-proxy"
    default_environment = {
        "npm_config_yes": "true",
    }
    # the npx shebang is $!/usr/bin/env node, so $PATH has to be correct
    add_virtualenv_to_path = True
    command_template = "{virtualenv_bin}npx gx-it-proxy --ip {gx_it_proxy[ip]} --port {gx_it_proxy[port]}" \
                       " --sessions {gx_it_proxy[sessions]} {gx_it_proxy[verbose]}"


class GalaxyTUSDService(Service):
    service_type = "tusd"
    service_name = "tusd"
    command_template = "{tusd[tusd_path]} -host={tusd[host]} -port={tusd[port]} -upload-dir={tusd[upload_dir]}" \
                       " -hooks-http={galaxy_infrastructure_url}/api/upload/hooks" \
                       " -hooks-http-forward-headers=X-Api-Key,Cookie {tusd[extra_args]}" \
                       " -hooks-enabled-events {tusd[hooks_enabled_events]}"


class GalaxyStandaloneService(Service):
    service_type = "standalone"
    service_name = "standalone"
    # FIXME: supervisor-specific
    command_template = "{virtualenv_bin}python ./lib/galaxy/main.py -c {galaxy_conf} --server-name={server_name}{attach_to_pool_opt}" \
                       " --pid-file={supervisor_state_dir}/{program_name}.pid"

    def get_environment(self):
        return self.get("environment") or {}


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
        super(GravityState, self).__init__(*args, **kwargs)
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
