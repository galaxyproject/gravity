""" Classes to represent and manipulate gravity's stored configuration and
state data.
"""
from __future__ import annotations
import enum
import hashlib
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
from gravity.util import http_check


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
    NONE = "none"


class ConfigFile(BaseModel):
    config_type: str
    app_config: Dict[str, Any]
    gravity_config_file: str
    galaxy_config_file: str
    instance_name: str
    process_manager: ProcessManager
    service_command_style: ServiceCommandStyle
    app_server: AppServer
    virtualenv: Optional[str]
    galaxy_root: Optional[str]
    galaxy_user: Optional[str]
    galaxy_group: Optional[str]
    umask: Optional[str]
    memory_limit: Optional[int]
    gravity_data_dir: str
    log_dir: str
    services: List[Service] = []

    def __hash__(self):
        return id(self)

    @property
    def path_hash(self):
        return hashlib.sha1(self.gravity_config_file.encode("UTF-8")).hexdigest()

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
        return self.get_services([service_name])[0]

    def get_services(self, service_names):
        if service_names:
            return [s for s in self.services if s.service_name in service_names]
        else:
            return self.services

    # this worked for me until it didn't, so we set exclude on the Service instead
    # def dict(self, *args, **kwargs):
    #     exclude = kwargs.pop("exclude", None) or {}
    #     exclude["services"] = {-1: {"config"}}
    #     return super().dict(*args, exclude=exclude, **kwargs)


class Service(BaseModel):
    config: ConfigFile
    # unfortunately as a class attribute this is now excluded from dict()
    _service_type: str = "service"
    service_name: str = "_default_"

    settings: Dict[str, Any]

    config_type: str = None

    _default_environment: Dict[str, str] = {}

    _settings_from: Optional[str] = None
    _enable_attribute = "enable"
    _service_list_allowed = False

    _graceful_method: GracefulMethod = GracefulMethod.DEFAULT
    _add_virtualenv_to_path = True
    _command_arguments: Dict[str, str] = {}
    _command_template: str = None

    @classmethod
    def services_if_enabled(cls, config, gravity_settings=None, settings=None, service_name=None):
        settings_from = cls._settings_from or cls._service_type
        settings = settings or getattr(gravity_settings, settings_from)
        service_name = service_name or cls._service_type
        services = []
        if isinstance(settings, list):
            if not cls._service_list_allowed:
                gravity.io.exception(
                    f"Settings for {cls._service_type} is a list, but lists are not allowed for this service type")
            for i, instance_settings in enumerate(settings):
                services.extend(cls.services_if_enabled(config, settings=instance_settings, service_name=f"{service_name}{i}"))
            if gravity_settings.use_service_instances:
                services = [ServiceList(services=services, service_name=service_name)]
        elif isinstance(settings, dict) and settings[cls._enable_attribute]:
            # settings is already a dict e.g. in the case of handlers
            services = [cls(config=config, settings=settings, service_name=service_name)]
        elif getattr(settings, cls._enable_attribute):
            services = [cls(config=config, settings=settings.dict(), service_name=service_name)]
        return services

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config_type = self.config.config_type

    @property
    def service_type(self):
        return self._service_type

    @property
    def default_environment(self):
        return self._default_environment.copy()

    @property
    def count(self):
        return 1

    @property
    def environment(self):
        environment = self.default_environment
        if self.config.virtualenv:
            environment["VIRTUAL_ENV"] = self.config.virtualenv
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
                    rval[setting] = self.command_arguments[setting].format(**format_vars)
                else:
                    rval[setting] = ""
            else:
                rval[setting] = value
        return rval

    def dict(self, *args, **kwargs):
        exclude = kwargs.pop("exclude", None) or {}
        exclude = {"config"}
        return super().dict(*args, exclude=exclude, **kwargs)


class ServiceList(BaseModel):
    config = ConfigFile
    _service_type = "_list_"
    service_name = "_list_"
    services: List[Service] = []

    # ServiceList is *only* used when service_command_style = gravity, meaning that the only case we need to do anything
    # special with is galaxyctl exec

    @property
    def graceful_method(self):
        if self.count > 1 and hasattr(self.services[0], "is_ready"):
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
                gravity.io.exception(f"Refusing to continue rolling restart, instance {instance_number} check failed before restart")
            gravity.io.debug(f"Calling restart callback {instance_number}: {restart_callbacks[instance_number]}")
            gravity.io.info(f"Restarting {self.service_name} instance {instance_number}")
            restart_callbacks[instance_number]()
            gravity.io.info(f"Restarted {self.service_name} instance {instance_number}, waiting for readiness check...")
            start = time.time()
            timeout = service_instance.settings["restart_timeout"]
            instance_is_ready = service_instance.is_ready()
            while not instance_is_ready and ((time.time() - start) < timeout):
                gravity.io.debug(f"{self.service_name}@{instance_number} not ready...")
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
    _service_list_allowed = True
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
        if v["preload"] is None:
            v["preload"] = True
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
        if self.config.virtualenv:
            environment["VIRTUAL_ENV"] = self.config.virtualenv
        environment.update(self.settings.get("environment", {}))
        return environment

    def is_ready(self, quiet=True):
        bind = self.settings["bind"]
        prefix = self.config.app_config.get("galaxy_url_prefix") or ""
        if prefix:
            prefix = prefix.rstrip("/")
        try:
            response = http_check(bind, f"{prefix}/api/version")
            version = response.json()
        except Exception as exc:
            if not quiet:
                gravity.io.error(exc)
            return False
        live_version = f"{version['version_major']}.{version['version_minor']}"
        disk_version = self.config.galaxy_version
        gravity.io.info(f"Gunicorn on {bind} running, version: {live_version} (disk version: {disk_version})", bright=False)
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
        if v["preload"] is None:
            v["preload"] = False
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
    _enable_attribute = "enable_beat"
    _default_environment = DEFAULT_GALAXY_ENVIRONMENT
    _command_template = "{virtualenv_bin}celery" \
                        " --app galaxy.celery" \
                        " beat" \
                        " --loglevel {settings[loglevel]}" \
                        " --schedule {gravity_data_dir}/" + CELERY_BEAT_DB_FILENAME


class GalaxyGxItProxyService(Service):
    _service_type = "gx-it-proxy"
    service_name = "gx-it-proxy"
    _settings_from = "gx_it_proxy"
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
        "proxy_path_prefix": "--proxyPathPrefix {settings[proxy_path_prefix]}",
    }
    _command_template = "{virtualenv_bin}npx gx-it-proxy@{settings[version]} --ip {settings[ip]} --port {settings[port]}" \
                        " --sessions {settings[sessions]} {command_arguments[verbose]}" \
                        " {command_arguments[forward_ip]} {command_arguments[forward_port]}" \
                        " {command_arguments[reverse_proxy]} {command_arguments[proxy_path_prefix]}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # override from Galaxy config if set
        self.settings["sessions"] = self.config.app_config.get("interactivetools_map", self.settings["sessions"])
        # this can only be set in Galaxy config
        it_base_path = self.config.app_config.get("interactivetools_base_path", "/")
        it_base_path = "/" + f"/{it_base_path.strip('/')}/".lstrip("/")
        it_prefix = self.config.app_config.get("interactivetools_prefix", "interactivetool")
        self.settings["proxy_path_prefix"] = f"{it_base_path}{it_prefix}/ep"

    @validator("settings")
    def _validate_settings(cls, v, values):
        if not values["config"].app_config["interactivetools_enable"]:
            gravity.io.exception("To run gx-it-proxy you need to set interactivetools_enable in the galaxy section of galaxy.yml")
        return v


class GalaxyTUSDService(Service):
    _service_type = "tusd"
    service_name = "tusd"
    _graceful_method = GracefulMethod.NONE
    _command_template = "{settings[tusd_path]} -host={settings[host]} -port={settings[port]}" \
                        " -upload-dir={settings[upload_dir]}" \
                        " -hooks-http={app_config[galaxy_infrastructure_url]}/api/upload/hooks" \
                        " -hooks-http-forward-headers=X-Api-Key,Cookie {settings[extra_args]}" \
                        " -hooks-enabled-events {settings[hooks_enabled_events]}"

    @validator("settings")
    def _validate_settings(cls, v, values):
        if not values["config"].app_config["galaxy_infrastructure_url"]:
            gravity.io.exception("To run tusd syou need to set galaxy_infrastructure_url in the galaxy section of galaxy.yml")
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
        reports_config_file = v["config_file"]
        if not os.path.isabs(reports_config_file):
            reports_config_file = os.path.join(os.path.dirname(values["config"]["galaxy_config_file"]), reports_config_file)
        if not os.path.exists(reports_config_file):
            gravity.io.exception(f"Reports enabled but reports config file does not exist: {reports_config_file}")
        v["config_file"] = reports_config_file
        return v


class GalaxyStandaloneService(Service):
    _service_type = "standalone"
    service_name = "standalone"
    # TODO: add these to Galaxy docs
    _default_settings = {
        "start_timeout": 20,
        "stop_timeout": 65,
    }
    _service_list_allowed = True
    _command_template = "{virtualenv_bin}python ./lib/galaxy/main.py -c {galaxy_conf}" \
                        " --server-name={settings[server_name]}{command_arguments[attach_to_pool]}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # ensure defaults are part of settings, this is not automatic since standalone does not have gravity settings
        settings = self._default_settings.copy()
        settings.update(self.settings)
        self.settings = settings
        if "server_name" not in self.settings:
            self.settings["server_name"] = self.service_name

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
}

VALID_SERVICE_NAMES = set(SERVICE_CLASS_MAP)
