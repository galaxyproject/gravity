""" Galaxy Process Management superclass and utilities
"""
import contextlib
import glob
import logging
import os
import xml.etree.ElementTree as elementtree
from typing import Union

from pydantic import ValidationError
from yaml import safe_load

import gravity.io
from gravity.settings import Settings
from gravity.state import (
    ConfigFile,
    service_for_service_type,
)
from gravity.util import recursive_update

log = logging.getLogger(__name__)

# Falling back to job_conf.xml when job_config_file is unset and job_conf.yml doesn't exist is deprecated in Galaxy, and
# support for it can be removed from Gravity when it is removed from Galaxy
DEFAULT_JOB_CONFIG_FILES = ("job_conf.yml", "job_conf.xml")
if "XDG_CONFIG_HOME" in os.environ:
    DEFAULT_STATE_DIR = os.path.join(os.environ["XDG_CONFIG_HOME"], "galaxy-gravity")

OPTIONAL_APP_KEYS = (
    "interactivetools_map",
    "interactivetools_base_path",
    "interactivetools_prefix",
    "galaxy_url_prefix",
)


@contextlib.contextmanager
def config_manager(config_file=None, state_dir=None):
    yield ConfigManager(config_file=config_file, state_dir=state_dir)


class ConfigManager(object):
    galaxy_server_config_section = "galaxy"
    gravity_config_section = "gravity"
    app_config_file_option = "galaxy_config_file"

    def __init__(self, config_file=None, state_dir=None):
        self.__configs = {}
        self.state_dir = None
        if state_dir is not None:
            # convert from pathlib.Path
            self.state_dir = str(state_dir)

        gravity.io.debug(f"Gravity state dir: {state_dir}")

        if config_file:
            for cf in config_file:
                self.load_config_file(cf)
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
                gravity.io.error(f"Failed to parse config: {config_file}")
                gravity.io.exception(exc)

        if type(config_dict) is not dict:
            gravity.io.exception(f"Config file does not look like valid Galaxy or Gravity configuration file: {config_file}")

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
                gravity.io.warn(
                    f"Config file appears to be a Gravity config but contains no {server_section} section, "
                    f"Galaxy defaults will be used: {config_file}")
        elif self.gravity_config_section not in config_dict and server_section in config_dict:
            gravity.io.warn(
                f"Config file appears to be a Galaxy config but contains no {self.gravity_config_section} section, "
                f"Gravity defaults will be used: {config_file}")
        elif self.gravity_config_section not in config_dict and server_section not in config_dict:
            gravity.io.exception(f"Config file does not look like valid Galaxy or Gravity configuration file: {config_file}")

        app_config = app_config or config_dict.get(server_section) or {}
        gravity_config_dict["__file__"] = config_file
        self.__load_config(gravity_config_dict, app_config)

    def __load_app_config_file(self, gravity_config_file, app_config_file):
        server_section = self.galaxy_server_config_section
        if not os.path.isabs(app_config_file):
            app_config_file = os.path.join(os.path.dirname(gravity_config_file), app_config_file)
        try:
            with open(app_config_file) as config_fh:
                _app_config_dict = safe_load(config_fh)
                if server_section not in _app_config_dict:
                    # we let a missing galaxy config slide in other scenarios but if you set the option to something
                    # that doesn't contain a galaxy section that's almost surely a mistake
                    gravity.io.exception(f"Galaxy config file does not contain a {server_section} section: {app_config_file}")
            app_config = _app_config_dict[server_section] or {}
            app_config["__file__"] = app_config_file
            return app_config
        except Exception as exc:
            gravity.io.exception(exc)

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
            gravity.io.exception(exc)

    def __load_config(self, gravity_config_dict, app_config):
        defaults = {}
        try:
            gravity_settings = Settings(**recursive_update(defaults, gravity_config_dict))
        except ValidationError as exc:
            # suppress the traceback and just report the error
            gravity.io.exception(exc)

        if gravity_settings.instance_name in self.__configs:
            gravity.io.error(
                f"Galaxy instance {gravity_settings.instance_name} already loaded from file: "
                f"{self.__configs[gravity_settings.instance_name].gravity_config_file}")
            gravity.io.exception(f"Duplicate instance name {gravity_settings.instance_name}, instance names must be unique")

        gravity_config_file = gravity_config_dict["__file__"]
        galaxy_config_file = app_config.get("__file__", gravity_config_file)
        galaxy_root = gravity_settings.galaxy_root or app_config.get("root")

        # TODO: document that the default state_dir is data_dir/gravity and that setting state_dir overrides this
        gravity_data_dir = self.state_dir or os.path.join(app_config.get("data_dir", "database"), "gravity")
        log_dir = gravity_settings.log_dir or os.path.join(gravity_data_dir, "log")

        # TODO: this should use galaxy.util.properties.load_app_properties() so that env vars work
        app_config_dict = {
            "galaxy_infrastructure_url": app_config.get("galaxy_infrastructure_url", "").rstrip("/"),
            "interactivetools_enable": app_config.get("interactivetools_enable"),
        }

        # some things should only be included if set
        for app_key in OPTIONAL_APP_KEYS:
            if app_key in app_config:
                app_config_dict[app_key] = app_config[app_key]

        config = ConfigFile(
            config_type=self.galaxy_server_config_section,
            app_config=app_config_dict,
            gravity_config_file=gravity_config_file,
            galaxy_config_file=galaxy_config_file,
            instance_name=gravity_settings.instance_name,
            process_manager=gravity_settings.process_manager,
            service_command_style=gravity_settings.service_command_style,
            app_server=gravity_settings.app_server,
            virtualenv=gravity_settings.virtualenv,
            galaxy_root=galaxy_root,
            galaxy_user=gravity_settings.galaxy_user,
            galaxy_group=gravity_settings.galaxy_group,
            umask=gravity_settings.umask,
            memory_limit=gravity_settings.memory_limit,
            gravity_data_dir=gravity_data_dir,
            log_dir=log_dir,
        )

        # add standard services if enabled
        for service_type in (config.app_server, "celery", "celery-beat", "tusd", "gx-it-proxy", "reports"):
            config.services.extend(service_for_service_type(service_type).services_if_enabled(config, gravity_settings))

        # load any static handlers defined in the galaxy job config
        assign_with = self.create_static_handler_services(config, app_config)

        # load any dynamic handlers defined in the gravity config
        self.create_dynamic_handler_services(gravity_settings, config, assign_with)

        for service in config.services:
            gravity.io.debug(f"Configured {service.service_type} type service: {service.service_name}")
        gravity.io.debug(f"Loaded instance {config.instance_name} from Gravity config file: {config.gravity_config_file}")

        self.__configs[config.instance_name] = config
        return config

    def create_static_handler_services(self, config: ConfigFile, app_config: dict):
        assign_with = None
        if not app_config.get("job_config_file") and app_config.get("job_config"):
            # config embedded directly in Galaxy config
            job_config = app_config["job_config"]
        else:
            # config in an external file
            config_dir = os.path.dirname(config.galaxy_config_file)
            job_config = app_config.get("job_config_file")
            if not job_config:
                for job_config in [os.path.abspath(os.path.join(config_dir, c)) for c in DEFAULT_JOB_CONFIG_FILES]:
                    if os.path.exists(job_config):
                        break
                else:
                    job_config = None
            elif not os.path.isabs(job_config):
                job_config = os.path.abspath(os.path.join(config_dir, job_config))
                if not os.path.exists(job_config):
                    job_config = None
        if job_config:
            # parse job conf for any *static* standalone handlers
            assign_with, handler_settings_list = ConfigManager.get_job_config(job_config)
            for handler_settings in handler_settings_list:
                config.services.append(service_for_service_type("standalone")(
                    config=config,
                    service_name=handler_settings.pop("service_name"),
                    settings=handler_settings,
                ))
        return assign_with

    def create_dynamic_handler_services(self, gravity_settings: Settings, config: ConfigFile, assign_with):
        # we push environment from settings to services but the rest of the services pull their env options from
        # settings directly. this can be a bit confusing but is probably ok since there are 3 ways to configure
        # handlers, and gravity is only 1 of them.
        assign_with = assign_with or []
        expanded_handlers = self.expand_handlers(gravity_settings, config)
        if expanded_handlers and "db-skip-locked" not in assign_with and "db-transaction-isolation" not in assign_with:
            gravity.io.warn(
                "Dynamic handlers are configured in Gravity but Galaxy is not configured to assign jobs to handlers "
                "dynamically, so these handlers will not handle jobs. Set the job handler assignment method in the "
                "Galaxy job configuration to `db-skip-locked` or `db-transaction-isolation` to fix this.")
        for service_name, handler_settings in expanded_handlers.items():
            config.services.extend(
                service_for_service_type("standalone").services_if_enabled(
                    config,
                    gravity_settings=gravity_settings,
                    settings=handler_settings,
                    service_name=service_name,
                ))

    @staticmethod
    def expand_handlers(gravity_settings: Settings, config: ConfigFile):
        use_list = gravity_settings.use_service_instances
        handlers = gravity_settings.handlers or {}
        expanded_handlers = {}
        default_name_template = "{name}_{process}"
        for service_name, handler_config in handlers.items():
            handler_config["enable"] = True
            count = handler_config.get("processes", 1)
            if "pools" in handler_config:
                handler_config["server_pools"] = handler_config.pop("pools")
            name_template = handler_config.get("name_template")
            if name_template is None:
                if count == 1 and service_name[-1].isdigit():
                    # Assume we have an explicit handler name, don't apply pattern
                    expanded_handlers[service_name] = handler_config
                    continue
            name_template = (name_template or default_name_template).strip()
            instances = []
            for index in range(count):
                expanded_service_name = name_template.format(name=service_name, process=index, instance_name=config.instance_name)
                if use_list:
                    instance = handler_config.copy()
                    instance["server_name"] = expanded_service_name
                    instances.append(instance)
                elif expanded_service_name not in expanded_handlers:
                    expanded_handlers[expanded_service_name] = handler_config
                else:
                    gravity.io.warn(f"Duplicate handler name after expansion: {expanded_service_name}")
            if use_list:
                expanded_handlers[service_name] = instances
        return expanded_handlers

    @staticmethod
    def get_job_config(conf: Union[str, dict]):
        """Extract handler names from job_conf.xml"""
        # TODO: use galaxy job conf parsing
        assign_with = None
        rval = []
        if isinstance(conf, str):
            if conf.endswith('.xml'):
                root = elementtree.parse(conf).getroot()
                handlers = root.find("handlers")
                assign_with = (handlers or {}).get("assign_with")
                if assign_with:
                    assign_with = [a.strip() for a in assign_with.split(",")]
                for handler in (handlers or []):
                    rval.append({"service_name": handler.attrib["id"]})
            elif conf.endswith(('.yml', '.yaml')):
                with open(conf) as job_conf_fh:
                    conf = safe_load(job_conf_fh.read())
            else:
                gravity.io.exception(f"Unknown job config file type: {conf}")
        if isinstance(conf, dict):
            handling = conf.get('handling') or {}
            assign_with = handling.get('assign', [])
            processes = handling.get('processes') or {}
            for handler_name, handler_options in processes.items():
                rval.append({
                    "service_name": handler_name,
                    "environment": (handler_options or {}).get("environment", None)
                })
        return (assign_with, rval)

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
                (process_manager is not None and config.process_manager == process_manager) or process_manager is None
            ):
                rval.append(config)
        return rval

    def get_config(self, instance_name=None):
        if instance_name is None:
            if self.instance_count > 1:
                gravity.io.exception("An instance name is required when more than one instance is configured")
            elif self.instance_count == 0:
                gravity.io.exception("No configured Galaxy instances")
            instance_name = list(self.__configs.keys())[0]
        try:
            return self.__configs[instance_name]
        except KeyError:
            gravity.io.exception(f"Unknown instance name: {instance_name}")

    def get_configured_service_names(self):
        rval = set()
        for config in self.get_configs():
            for service in config.services:
                rval.add(service.service_name)
        return rval

    def get_configured_instance_names(self):
        return list(self.__configs.keys())

    def get_configured_files(self):
        return list(c.gravity_config_file for c in self.__configs.values())

    def auto_load(self):
        """Attempt to automatically load a config file if none are loaded."""
        load_all = False
        if self.instance_count != 0:
            return
        if os.environ.get("GALAXY_CONFIG_FILE"):
            configs = [os.environ["GALAXY_CONFIG_FILE"]]
        elif self.is_root:
            load_all = True
            configs = (
                "/etc/galaxy/gravity.yml",
                "/etc/galaxy/galaxy.yml",
                *glob.glob("/etc/galaxy/gravity.d/*.yml"),
                *glob.glob("/etc/galaxy/gravity.d/*.yaml"),
            )
        else:
            configs = (os.path.join("config", "galaxy.yml"), os.path.join("config", "galaxy.yml.sample"))
        for config in configs:
            if os.path.exists(config):
                self.load_config_file(os.path.abspath(config))
                if not load_all:
                    return
