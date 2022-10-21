""" Galaxy Process Management superclass and utilities
"""
import contextlib
import logging
import os
import xml.etree.ElementTree as elementtree
from os import pardir
from os.path import abspath, dirname, exists, isabs, join
from typing import Union

from yaml import safe_load

from gravity.settings import Settings
from gravity.io import debug, error, exception, warn
from gravity.state import (
    ConfigFile,
    service_for_service_type,
)
from gravity.util import recursive_update

log = logging.getLogger(__name__)

DEFAULT_JOB_CONFIG_FILE = "config/job_conf.xml"
if "XDG_CONFIG_HOME" in os.environ:
    DEFAULT_STATE_DIR = join(os.environ["XDG_CONFIG_HOME"], "galaxy-gravity")


@contextlib.contextmanager
def config_manager(config_file=None, state_dir=None):
    yield ConfigManager(config_file=config_file, state_dir=state_dir)


class ConfigManager(object):
    galaxy_server_config_section = "galaxy"
    gravity_config_section = "gravity"
    app_config_file_option = "galaxy_config_file"

    def __init__(self, config_file=None, state_dir=None):
        self.__configs = {}
        self.state_dir = state_dir

        debug(f"Gravity state dir: {state_dir}")

        if config_file is not None:
            self.load_config_file(config_file)
        else:
            self.auto_load()

    @property
    def is_root(self):
        return os.geteuid() == 0

    def load_config_file(self, config_file):
        with open(config_file) as config_fh:
            try:
                config_dict = safe_load(config_fh)
            except Exception as exc:
                # this should always be a parse error, access errors will be caught by click
                error(f"Failed to parse config: {config_file}")
                exception(exc)

        if type(config_dict) is not dict:
            exception(f"Config file does not look like valid Galaxy or Gravity configuration file: {config_file}")

        gravity_config_dict = config_dict.get(self.gravity_config_section) or {}

        if type(gravity_config_dict) is list:
            self.__load_config_list(config_file, config_dict)
            return

        app_config = None
        server_section = self.galaxy_server_config_section
        if self.gravity_config_section in config_dict and server_section not in config_dict:
            app_config_file = config_dict[self.gravity_config_section].get(self.app_config_file_option)
            if app_config_file:
                app_config = self.__load_app_config_file(config_file, app_config_file)
            else:
                warn(
                    f"Config file appears to be a Gravity config but contains no {server_section} section, "
                    f"Galaxy defaults will be used: {config_file}")
        elif self.gravity_config_section not in config_dict and server_section in config_dict:
            warn(
                f"Config file appears to be a Galaxy config but contains no {self.gravity_config_section} section, "
                f"Gravity defaults will be used: {config_file}")
        elif self.gravity_config_section not in config_dict and server_section not in config_dict:
            exception(f"Config file does not look like valid Galaxy or Gravity configuration file: {config_file}")

        app_config = app_config or config_dict.get(server_section) or {}
        gravity_config_dict["__file__"] = config_file
        self.__load_config(gravity_config_dict, app_config)

    def __load_app_config_file(self, gravity_config_file, app_config_file):
        server_section = self.galaxy_server_config_section
        if not isabs(app_config_file):
            app_config_file = join(dirname(gravity_config_file), app_config_file)
        try:
            with open(app_config_file) as config_fh:
                _app_config_dict = safe_load(config_fh)
                if server_section not in _app_config_dict:
                    # we let a missing galaxy config slide in other scenarios but if you set the option to something
                    # that doesn't contain a galaxy section that's almost surely a mistake
                    exception(f"Galaxy config file does not contain a {server_section} section: {app_config_file}")
            app_config = _app_config_dict[server_section] or {}
            app_config["__file__"] = app_config_file
            return app_config
        except Exception as exc:
            exception(exc)

    def __load_config_list(self, config_file, config_dict):
        try:
            assert self.galaxy_server_config_section not in config_dict, (
                "Multiple Gravity configurations in a shared Galaxy configuration file is ambiguous, set "
                f"`{self.app_config_file_option}` and remove the Galaxy configuration: {config_file}"
            )
            for gravity_config_dict in config_dict[self.gravity_config_section]:
                assert "galaxy_config_file" in gravity_config_dict, (
                    "The `{self.app_config_file_option}` option must be set when multiple Gravity configurations are "
                    f"present: {config_file}"
                )
                app_config = self.__load_app_config_file(config_file, gravity_config_dict[self.app_config_file_option])
                gravity_config_dict["__file__"] = config_file
                self.__load_config(gravity_config_dict, app_config)
        except AssertionError as exc:
            exception(exc)

    def __load_config(self, gravity_config_dict, app_config):
        defaults = {}
        gravity_config = Settings(**recursive_update(defaults, gravity_config_dict))

        config = ConfigFile()
        config.attribs = {}
        config.services = []

        config.__file__ = gravity_config_dict["__file__"]
        config.galaxy_config_file = app_config.get("__file__", config.__file__)

        if gravity_config.instance_name in self.__configs:
            error(
                f"Galaxy instance {gravity_config.instance_name} already loaded from file: "
                f"{self.__configs[gravity_config.instance_name].__file__}")
            exception(f"Duplicate instance name {gravity_config.instance_name}, instance names must be unique")

        config.instance_name = gravity_config.instance_name
        config.config_type = self.galaxy_server_config_section
        config.process_manager = gravity_config.process_manager
        config.service_command_style = gravity_config.service_command_style
        config.attribs["galaxy_infrastructure_url"] = app_config.get("galaxy_infrastructure_url", "").rstrip("/")
        config.attribs["app_server"] = gravity_config.app_server
        config.attribs["virtualenv"] = gravity_config.virtualenv
        config.attribs["gunicorn"] = gravity_config.gunicorn.dict()
        config.attribs["tusd"] = gravity_config.tusd.dict()
        config.attribs["celery"] = gravity_config.celery.dict()
        config.attribs["reports"] = gravity_config.reports.dict()
        config.attribs["handlers"] = gravity_config.handlers
        config.attribs["galaxy_user"] = gravity_config.galaxy_user
        config.attribs["galaxy_group"] = gravity_config.galaxy_group
        config.attribs["memory_limit"] = gravity_config.memory_limit

        # shortcut for galaxy configs in the standard locations
        config.galaxy_root = gravity_config.galaxy_root or app_config.get("root")
        if config.galaxy_root is None:
            if os.environ.get("GALAXY_ROOT_DIR"):
                config.galaxy_root = abspath(os.environ["GALAXY_ROOT_DIR"])
            elif exists(join(dirname(config.galaxy_config_file), pardir, "lib", "galaxy")):
                config.galaxy_root = abspath(join(dirname(config.galaxy_config_file), pardir))
            elif config.galaxy_config_file.endswith(join("galaxy", "config", "sample", "galaxy.yml.sample")):
                config.galaxy_root = abspath(join(dirname(config.galaxy_config_file), pardir, pardir, pardir, pardir))
            else:
                exception(
                    "Cannot locate Galaxy root directory: set $GALAXY_ROOT_DIR, the Gravity `galaxy_root` option, or "
                    "`root' in the Galaxy config")

        # TODO: document that the default state_dir is data_dir/gravity and that setting state_dir overrides this
        data_dir = app_config.get("data_dir", "database")
        if not isabs(data_dir):
            data_dir = abspath(join(config.galaxy_root, data_dir))
        config.gravity_data_dir = self.state_dir or join(data_dir, "gravity")

        if gravity_config.log_dir is None:
            gravity_config.log_dir = join(config.gravity_data_dir, "log")
        config.attribs["log_dir"] = gravity_config.log_dir

        if gravity_config.tusd.enable and not config.attribs["galaxy_infrastructure_url"]:
            exception("To run the tusd server you need to set galaxy_infrastructure_url in the galaxy section of galaxy.yml")
        if gravity_config.gunicorn.enable:
            if config.attribs["gunicorn"]["preload"] is None:
                config.attribs["gunicorn"]["preload"] = config.attribs["app_server"] != "unicornherder"
            config.services.append(service_for_service_type(config.attribs["app_server"])(config_type=config.config_type))
        if gravity_config.celery.enable:
            config.services.append(service_for_service_type("celery")(config_type=config.config_type))
        if gravity_config.celery.enable_beat:
            config.services.append(service_for_service_type("celery-beat")(config_type=config.config_type))
        if gravity_config.tusd.enable:
            config.services.append(service_for_service_type("tusd")(config_type=config.config_type))
        if gravity_config.reports.enable:
            reports_config_file = config.attribs["reports"]["config_file"]
            if not isabs(config.attribs["reports"]["config_file"]):
                reports_config_file = join(dirname(config.galaxy_config_file), reports_config_file)
                config.attribs["reports"]["config_file"] = reports_config_file
            if not exists(reports_config_file):
                exception(f"Reports enabled but reports config file does not exist: {reports_config_file}")
            config.services.append(service_for_service_type("reports")(config_type=config.config_type))

        if not app_config.get("job_config_file") and app_config.get("job_config"):
            # config embedded directly in Galaxy config
            job_config = app_config["job_config"]
        else:
            # If this is a Galaxy config, parse job_conf.xml for any *static* standalone handlers
            # TODO: use galaxy config parsing ?
            job_config = app_config.get("job_config_file", DEFAULT_JOB_CONFIG_FILE)
            if not isabs(job_config):
                # FIXME: relative to root
                job_config = abspath(join(config["galaxy_root"], job_config))
                if not exists(job_config):
                    job_config = None
        if config.config_type == "galaxy" and job_config:
            for handler_settings in ConfigManager.get_job_config(job_config):
                config.services.append(service_for_service_type("standalone")(
                    config_type=config.config_type,
                    service_name=handler_settings["service_name"],
                    environment=handler_settings.get("environment"),
                    memory_limit=handler_settings.get("memory_limit"),
                    start_timeout=handler_settings.get("start_timeout"),
                    stop_timeout=handler_settings.get("stop_timeout")
                ))

        # FIXME: This should imply explicit configuration of the handler assignment method. If not explicitly set, the
        # web process will be a handler, which is not desirable when dynamic handlers are used. Currently Gravity
        # doesn't parse that part of the job config. See logic in lib/galaxy/web_stack/handlers.py _get_is_handler() to
        # see how this is determined.
        self.create_handler_services(gravity_config, config)
        self.create_gxit_services(gravity_config, app_config, config)
        self.__configs[config.instance_name] = config
        debug(f"Loaded instance {config.instance_name} from Gravity config file: {config.__file__}")
        return config

    def create_handler_services(self, gravity_config: Settings, config):
        # we pull push environment from settings to services but the rest of the services pull their env options from
        # settings directly. this can be a bit confusing but is probably ok since there are 3 ways to configure
        # handlers, and gravity is only 1 of them.
        expanded_handlers = self.expand_handlers(gravity_config, config)
        for service_name, handler_settings in expanded_handlers.items():
            pools = handler_settings.get('pools')
            environment = handler_settings.get("environment")
            # TODO: add these to Galaxy docs
            start_timeout = handler_settings.get("start_timeout")
            stop_timeout = handler_settings.get("stop_timeout")
            memory_limit = handler_settings.get("memory_limit")
            config.services.append(
                service_for_service_type("standalone")(
                    config_type=config.config_type,
                    service_name=service_name,
                    server_pools=pools,
                    environment=environment,
                    start_timeout=start_timeout,
                    stop_timeout=stop_timeout,
                    memory_limit=memory_limit
                ))

    def create_gxit_services(self, gravity_config: Settings, app_config, config):
        interactivetools_enable = app_config.get("interactivetools_enable")
        if gravity_config.gx_it_proxy.enable and not interactivetools_enable:
            exception("To run the gx-it-proxy server you need to set interactivetools_enable in the galaxy section of galaxy.yml")
        if gravity_config.gx_it_proxy.enable:
            # TODO: resolve against data_dir, or bring in galaxy-config ?
            # CWD in supervisor template is galaxy_root, so this should work for simple cases as is
            gxit_config = gravity_config.gx_it_proxy
            gxit_config.sessions = app_config.get("interactivetools_map", gxit_config.sessions)
            gxit_config.verbose = '--verbose' if gxit_config.verbose else ''
            config.services.append(service_for_service_type("gx-it-proxy")(config_type=config.config_type))
        config.attribs["gx-it-proxy"] = gravity_config.gx_it_proxy.dict()

    @staticmethod
    def expand_handlers(gravity_config: Settings, config):
        handlers = gravity_config.handlers or {}
        expanded_handlers = {}
        default_name_template = "{name}_{process}"
        for service_name, handler_config in handlers.items():
            count = handler_config.get("processes", 1)
            name_template = handler_config.get("name_template")
            if name_template is None:
                if count == 1 and service_name[-1].isdigit():
                    # Assume we have an explicit handler name, don't apply pattern
                    expanded_handlers[service_name] = handler_config
                    continue
            name_template = (name_template or default_name_template).strip()
            for index in range(count):
                expanded_service_name = name_template.format(name=service_name, process=index, instance_name=config.instance_name)
                if expanded_service_name not in expanded_handlers:
                    expanded_handlers[expanded_service_name] = handler_config
        return expanded_handlers

    @staticmethod
    def get_job_config(conf: Union[str, dict]):
        """Extract handler names from job_conf.xml"""
        # TODO: use galaxy job conf parsing
        rval = []
        if isinstance(conf, str):
            if conf.endswith('.xml'):
                root = elementtree.parse(conf).getroot()
                for handler in (root.find("handlers") or []):
                    rval.append({"service_name": handler.attrib["id"]})
                return rval
            elif conf.endswith(('.yml', '.yaml')):
                with open(conf) as job_conf_fh:
                    conf = safe_load(job_conf_fh.read())
            else:
                exception(f"Unknown job config file type: {conf}")
        if isinstance(conf, dict):
            handling = conf.get('handling') or {}
            processes = handling.get('processes') or {}
            for handler_name, handler_options in processes.items():
                rval.append({
                    "service_name": handler_name,
                    "environment": (handler_options or {}).get("environment", None)
                })
        return rval

    @property
    def instance_count(self):
        """The number of configured instances"""
        return len(self.__configs)

    @property
    def single_instance(self):
        """Indicate if there is only one configured instance"""
        return self.instance_count == 1

    def is_loaded(self, config_file):
        return config_file in self.get_configured_files()

    def get_configs(self, instances=None, process_manager=None):
        """Return the persisted values of all config files registered with the config manager."""
        rval = []
        for instance_name, config in list(self.__configs.items()):
            if ((instances is not None and instance_name in instances) or instances is None) and (
                (process_manager is not None and config["process_manager"] == process_manager) or process_manager is None
            ):
                rval.append(config)
        return rval

    def get_config(self, instance_name=None):
        if instance_name is None:
            if self.instance_count > 1:
                exception("An instance name is required when more than one instance is configured")
            elif self.instance_count == 0:
                exception("No configured Galaxy instances")
            instance_name = list(self.__configs.keys())[0]
        try:
            return self.__configs[instance_name]
        except KeyError:
            exception(f"Unknown instance name: {instance_name}")

    def get_configured_service_names(self):
        rval = set()
        for config in self.get_configs():
            for service in config["services"]:
                rval.add(service["service_name"])
        return rval

    def get_configured_instance_names(self):
        return list(self.__configs.keys())

    def get_configured_files(self):
        return list(c["__file__"] for c in self.__configs.values())

    def auto_load(self):
        """Attempt to automatically load a config file if none are loaded."""
        if self.instance_count == 0:
            if os.environ.get("GALAXY_CONFIG_FILE"):
                configs = [os.environ["GALAXY_CONFIG_FILE"]]
            else:
                configs = (os.path.join("config", "galaxy.yml"), os.path.join("config", "galaxy.yml.sample"))
            for config in configs:
                if exists(config):
                    self.load_config_file(abspath(config))
                    return
