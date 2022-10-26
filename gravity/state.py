""" Classes to represent and manipulate gravity's stored configuration and
state data.
"""
from __future__ import annotations
import enum
import os
import sys
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, validator

import gravity.io
from gravity.settings import (
    AppServer,
    ProcessManager,
    ServiceCommandStyle,
)
from gravity.util import classproperty, http_check


DEFAULT_GALAXY_ENVIRONMENT = {
    "PYTHONPATH": "lib",
    "GALAXY_CONFIG_FILE": "{galaxy_conf}",
}
CELERY_BEAT_DB_FILENAME = "celery-beat-schedule"


def relative_to_galaxy_root(cls, v, values):
    if not os.path.isabs(v):
        v = os.path.abspath(os.path.join(values["galaxy_root"], v))
    return v


class GracefulMethod(str, enum.Enum):
    DEFAULT = "default"
    SIGHUP = "sighup"
    ROLLING = "rolling"


class ConfigFile(BaseModel):
    config_type: str
    gravity_config_file: str
    galaxy_config_file: str
    instance_name: str
    process_manager: ProcessManager
    service_command_style: ServiceCommandStyle
    app_server: AppServer
    virtualenv: Optional[str]
    galaxy_infrastructure_url: str
    galaxy_root: Optional[str]
    galaxy_user: Optional[str]
    galaxy_group: Optional[str]
    umask: Optional[str]
    memory_limit: Optional[int]
    gravity_data_dir: str
    log_dir: str
    services: List[Service] = []

    @property
    def galaxy_version(self):
        galaxy_version_file = os.path.join(self.galaxy_root, "lib", "galaxy", "version.py")
        with open(galaxy_version_file) as fh:
            locs = {}
            exec(fh.read(), {}, locs)
            return locs["VERSION"]

    @validator("galaxy_root")
    def _galaxy_root_required(cls, v, values):
        if v is None:
            galaxy_config_file = values["galaxy_config_file"]
            if os.environ.get("GALAXY_ROOT_DIR"):
                v = os.path.abspath(os.environ["GALAXY_ROOT_DIR"])
            elif os.path.exists(os.path.join(os.path.dirname(galaxy_config_file), os.pardir, "lib", "galaxy")):
                v = os.path.abspath(os.path.join(os.path.dirname(galaxy_config_file), os.pardir))
            elif galaxy_config_file.endswith(os.path.join("galaxy", "config", "sample", "galaxy.yml.sample")):
                v = os.path.abspath(os.path.join(os.path.dirname(galaxy_config_file), os.pardir, os.pardir, os.pardir, os.pardir))
            else:
                gravity.io.exception(
                    "Cannot locate Galaxy root directory: set $GALAXY_ROOT_DIR, the Gravity `galaxy_root` option, or "
                    "`root' in the Galaxy config")
        return v

    _validate_gravity_data_dir = validator("gravity_data_dir", allow_reuse=True)(relative_to_galaxy_root)
    _validate_log_dir = validator("log_dir", allow_reuse=True)(relative_to_galaxy_root)

    def get_service(self, service_name):
        return [s for s in self.services if s.service_name == service_name][0]

    # this worked for me until it didn't, so we set exclude on the Service instead
    # def dict(self, *args, **kwargs):
    #     exclude = kwargs.pop("exclude", None) or {}
    #     exclude["services"] = {-1: {"config", "service_settings"}}
    #     return super().dict(*args, exclude=exclude, **kwargs)


class Service(BaseModel):
    config: ConfigFile
    # unfortunately as a class attribute this is now excluded from dict()
    _service_type: str = "service"
    service_name: str = "_default_"
    #service_settings: Dict[str, Any]

    var_formatter: Callable[[ConfigFile, Service], Dict[str, str]] = None

    settings: Dict[str, Any]

    config_type: str = None

    _default_environment: Dict[str, str] = {}
    _settings_from: Optional[str] = None
    _graceful_method: GracefulMethod = GracefulMethod.DEFAULT
    _add_virtualenv_to_path = False
    _command_arguments: Dict[str, str] = {}
    _command_template: str = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config_type = self.config.config_type
        # this ensures it's included in dict()
        #self.settings = self.service_settings[self.settings_from].copy()

    # these are class "properties" because they are accessed by validators
    @classproperty
    def service_type(cls):
        return cls._service_type

    @classproperty
    def settings_from(cls):
        return cls._settings_from or cls.service_type

    @classproperty
    def default_environment(cls):
        return cls._default_environment.copy()

    @property
    def count(self):
        return 1

    # @property
    # def settings(self):
    #     return self.service_settings[self.settings_from].copy()

    @property
    def environment(self):
        environment = self.default_environment
        environment.update(self.settings.get("environment") or {})
        return environment

    @property
    def graceful_method(self):
        return self._graceful_method

    @property
    def add_virtualenv_to_path(self):
        return self._add_virtualenv_to_path

    @property
    def command_arguments(self):
        return self._command_arguments

    @property
    def command_template(self):
        return self._command_template

    def __eq__(self, other):
        return self.config_type == other.config_type and self.service_type == other.service_type and self.service_name == other.service_name

    def get_command_arguments(self, format_vars):
        """Convert settings into their command line arguments."""
        rval = {}
        for setting, value in self.settings.items():
            if setting in self.command_arguments:
                if value:
                    # FIXME: this should be unnecessary
                    # recursively format until there are no more template placeholders left
                    rval[setting] = self.command_arguments[setting]
                    while "{" in rval[setting] and "}" in rval[setting]:
                        rval[setting] = rval[setting].format(**format_vars)
                else:
                    rval[setting] = ""
            else:
                rval[setting] = value
        return rval

    def dict(self, *args, **kwargs):
        exclude = kwargs.pop("exclude", None) or {}
        #exclude = {"config", "service_settings"}
        exclude = {"config"}
        return super().dict(*args, exclude=exclude, **kwargs)

    # FIXME: probably don't need to do all this
    def get_format_vars(self):
        if "_format_vars" in self.__dict__:
            return self.__dict__["_format_vars"]
        else:
            self.var_formatter(self)
            return self.__dict__["_format_vars"]
            #raise RuntimeError("Attempt to access format_vars before they have been set")

    def set_format_vars(self, value):
        self.__dict__["_format_vars"] = value

    format_vars = property(get_format_vars, set_format_vars)


class ServiceList(BaseModel):
    config = ConfigFile
    _service_type = "_list_"
    service_name = "_list_"
    services: List[Service] = []
    var_formatter: Callable[[ConfigFile, Service], Dict[str, str]] = None

    # ServiceList is *only* used when service_command_style = gravity, meaning that the only case we need to do anything
    # special with is galaxyctl exec

    @property
    def graceful_method(self):
        if self.count > 1:
            return GracefulMethod.ROLLING
        else:
            return self.services[0].graceful_method

    @property
    def count(self):
        return len(self.services)

    def get_service_instance(self, instance_number):
        return self.services[instance_number]

    def rolling_restart(self, restart_callbacks):
        gravity.io.info(f"Performing rolling restart on service: {self.service_name}")
        for instance_number, service_instance in enumerate(self.services):
            if not service_instance.is_ready(quiet=False):
                gravity.io.exception(f"Refusing to continue rolling restart, instance {instance_number} was down before restart")
            gravity.io.debug(f"Calling restart callback {instance_number}: {restart_callbacks[instance_number]}")
            restart_callbacks[instance_number]()
            start = time.time()
            timeout = service_instance.settings["restart_timeout"]
            instance_is_ready = service_instance.is_ready()
            while not instance_is_ready and ((time.time() - start) < timeout):
                gravity.io.debug(f"{program_name} not ready...")
                time.sleep(2)
                instance_is_ready = service_instance.is_ready()
            if not instance_is_ready:
                gravity.io.exception(f"Refusing to continue rolling restart, instance failed to respond after {timeout} seconds")


    # everything else falls through to the first configured service
    def __getattr__(self, name):
        return getattr(self.services[0], name)


class GalaxyGunicornService(Service):
    _service_type = "gunicorn"
    service_name = "gunicorn"
    _default_environment = DEFAULT_GALAXY_ENVIRONMENT
    _command_arguments = {
        "preload": "--preload",
    }
    _command_template = "{virtualenv_bin}gunicorn 'galaxy.webapps.galaxy.fast_factory:factory()'" \
                        " --timeout {settings[timeout]}" \
                        " --pythonpath lib" \
                        " -k galaxy.webapps.galaxy.workers.Worker" \
                        " -b {settings[bind]}" \
                        " --workers={settings[workers]}" \
                        " --config python:galaxy.web_stack.gunicorn_config" \
                        " {command_arguments[preload]}" \
                        " {settings[extra_args]}"

    @validator("settings")
    def _normalize_settings(cls, v, values):
        # TODO: should be copy?
        #settings = v[cls.settings_from]
        settings = v
        if settings["preload"] is None:
            settings["preload"] = True
        return v

    @property
    def graceful_method(self):
        if self.settings.get("preload"):
            return GracefulMethod.DEFAULT
        else:
            return GracefulMethod.SIGHUP

    @property
    def environment(self):
        # Works around https://github.com/galaxyproject/galaxy/issues/11821
        environment = self.default_environment
        if sys.platform == 'darwin':
            environment["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        environment.update(self.settings.get("environment", {}))
        return environment

    def is_ready(self, quiet=True):
        bind = self.settings["bind"]
        # FIXME: insert app.galaxy_url_prefix
        try:
            response = http_check(bind, "/api/version")
            version = response.json()
        except Exception as exc:
            if not quiet:
                gravity.io.error(exc)
            return False
        live_version = f"{version['version_major']}.{version['version_minor']}"
        disk_version = self.config.galaxy_version
        gravity.io.info(f"Gunicorn on {bind} running, version: {live_version} (disk version: {disk_version})")
        return True


class GalaxyUnicornHerderService(Service):
    _service_type = "unicornherder"
    service_name = "unicornherder"
    _settings_from = "gunicorn"
    _graceful_method = GracefulMethod.SIGHUP
    _default_environment = DEFAULT_GALAXY_ENVIRONMENT
    _command_template = "{virtualenv_bin}unicornherder --" \
                        " 'galaxy.webapps.galaxy.fast_factory:factory()'" \
                        " --timeout {settings[timeout]}" \
                        " --pythonpath lib" \
                        " -k galaxy.webapps.galaxy.workers.Worker" \
                        " -b {settings[bind]}" \
                        " --workers={settings[workers]}" \
                        " --config python:galaxy.web_stack.gunicorn_config" \
                        " {command_arguments[preload]}" \
                        " {settings[extra_args]}"

    @validator("settings")
    def _normalize_settings(cls, v, values):
        # TODO: should be copy?
        #settings = v[cls.settings_from]
        settings = v
        if settings["preload"] is None:
            settings["preload"] = False
        return v

    environment = GalaxyGunicornService.environment
    command_arguments = GalaxyGunicornService.command_arguments


class GalaxyCeleryService(Service):
    _service_type = "celery"
    service_name = "celery"
    _default_environment = DEFAULT_GALAXY_ENVIRONMENT
    _command_template = "{virtualenv_bin}celery" \
                        " --app galaxy.celery worker" \
                        " --concurrency {settings[concurrency]}" \
                        " --loglevel {settings[loglevel]}" \
                        " --pool {settings[pool]}" \
                        " --queues {settings[queues]}" \
                        " {settings[extra_args]}"


class GalaxyCeleryBeatService(Service):
    _service_type = "celery-beat"
    service_name = "celery-beat"
    _settings_from = "celery"
    _default_environment = DEFAULT_GALAXY_ENVIRONMENT
    _command_template = "{virtualenv_bin}celery" \
                        " --app galaxy.celery" \
                        " beat" \
                        " --loglevel {settings[loglevel]}" \
                        " --schedule {gravity_data_dir}/" + CELERY_BEAT_DB_FILENAME


class GalaxyGxItProxyService(Service):
    _service_type = "gx-it-proxy"
    service_name = "gx-it-proxy"
    _default_environment = {
        "npm_config_yes": "true",
    }
    # the npx shebang is $!/usr/bin/env node, so $PATH has to be correct
    _add_virtualenv_to_path = True
    _command_arguments = {
        "verbose": "--verbose",
        "forward_ip": "--forwardIP {settings[forward_ip]}",
        "forward_port": "--forwardPort {settings[forward_port]}",
        "reverse_proxy": "--reverseProxy",
    }
    _command_template = "{virtualenv_bin}npx gx-it-proxy --ip {settings[ip]} --port {settings[port]}" \
                        " --sessions {settings[sessions]} {command_arguments[verbose]}" \
                        " {command_arguments[forward_ip]} {command_arguments[forward_port]}" \
                        " {command_arguments[reverse_proxy]}"


class GalaxyTUSDService(Service):
    _service_type = "tusd"
    service_name = "tusd"
    _command_template = "{settings[tusd_path]} -host={settings[host]} -port={settings[port]}" \
                        " -upload-dir={settings[upload_dir]}" \
                        " -hooks-http={galaxy_infrastructure_url}/api/upload/hooks" \
                        " -hooks-http-forward-headers=X-Api-Key,Cookie {settings[extra_args]}" \
                        " -hooks-enabled-events {settings[hooks_enabled_events]}"

    @validator("settings")
    def _validate_settings(cls, v, values):
        if not values["config"].galaxy_infrastructure_url:
            gravity.io.exception("To run the tusd server you need to set galaxy_infrastructure_url in the galaxy section of galaxy.yml")
        return v


class GalaxyReportsService(Service):
    _service_type = "reports"
    service_name = "reports"
    _graceful_method = GracefulMethod.SIGHUP
    _default_environment = {
        "PYTHONPATH": "lib",
        "GALAXY_REPORTS_CONFIG": "{settings[config_file]}",
    }
    _command_arguments = {
        "url_prefix": "--env SCRIPT_NAME={settings[url_prefix]}",
    }
    _command_template = "{virtualenv_bin}gunicorn 'galaxy.webapps.reports.fast_factory:factory()'" \
                        " --timeout {settings[timeout]}" \
                        " --pythonpath lib" \
                        " -k uvicorn.workers.UvicornWorker" \
                        " -b {settings[bind]}" \
                        " --workers={settings[workers]}" \
                        " --config python:galaxy.web_stack.gunicorn_config" \
                        " {command_arguments[url_prefix]}" \
                        " {settings[extra_args]}"

    @validator("settings")
    def _validate_settings(cls, v, values):
        #settings = v[cls.settings_from]
        settings = v
        reports_config_file = settings["config_file"]
        if not os.path.isabs(reports_config_file):
            reports_config_file = os.path.join(os.path.dirname(values["config"]["galaxy_config_file"]), reports_config_file)
        if not os.path.exists(reports_config_file):
            gravity.io.exception(f"Reports enabled but reports config file does not exist: {reports_config_file}")
        settings["config_file"] = reports_config_file
        return v


class GalaxyStandaloneService(Service):
    _service_type = "standalone"
    service_name = "standalone"
    # TODO: add these to Galaxy docs, test that they are settable in all the ways they should be
    _default_settings = {
        "start_timeout": 20,
        "stop_timeout": 65,
    }
    _command_template = "{virtualenv_bin}python ./lib/galaxy/main.py -c {galaxy_conf} --server-name={server_name}" \
                        " {command_arguments[attach_to_pool]}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # overwrite the default method of setting settings, we need to include defaults sinc standalone does not have
        # gravity settings
        self.settings = self._default_settings.copy()
        self.settings.update(self.service_settings[self.settings_from])

    def get_command_arguments(self, format_vars):
        # full override to do the join
        command_arguments = {
            "attach_to_pool": "",
        }
        server_pools = self.settings.get("server_pools")
        if server_pools:
            _attach_to_pool = " ".join(f"--attach-to-pool={server_pool}" for server_pool in server_pools)
            # Insert a single leading space
            command_arguments["attach_to_pool"] = f" {_attach_to_pool}"
        return command_arguments


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
    "reports": GalaxyReportsService,
    "standalone": GalaxyStandaloneService,
    "_list_": ServiceList,
}

VALID_SERVICE_NAMES = set(SERVICE_CLASS_MAP)
