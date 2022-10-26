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
from gravity.settings import ServiceCommandStyle, Settings
from gravity.state import (
    ConfigFile,
    service_for_service_type,
)
from gravity.util import recursive_update

log = logging.getLogger(__name__)

DEFAULT_JOB_CONFIG_FILE = "config/job_conf.xml"
if "XDG_CONFIG_HOME" in os.environ:
    DEFAULT_STATE_DIR = os.path.join(os.environ["XDG_CONFIG_HOME"], "galaxy-gravity")


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
            gravity_config = Settings(**recursive_update(defaults, gravity_config_dict))
        except ValidationError as exc:
            # suppress the traceback and just report the error
            gravity.io.exception(exc)

        if gravity_config.instance_name in self.__configs:
            gravity.io.error(
                f"Galaxy instance {gravity_config.instance_name} already loaded from file: "
                f"{self.__configs[gravity_config.instance_name].gravity_config_file}")
            gravity.io.exception(f"Duplicate instance name {gravity_config.instance_name}, instance names must be unique")

        gravity_config_file = gravity_config_dict["__file__"]
        galaxy_config_file = app_config.get("__file__", gravity_config_file)

        service_settings = {}
        if isinstance(gravity_config.gunicorn, list):
            service_settings["gunicorn"] = [g.dict() for g in gravity_config.gunicorn]
        else:
            service_settings["gunicorn"] = gravity_config.gunicorn.dict()
        service_settings["tusd"] = gravity_config.tusd.dict()
        service_settings["celery"] = gravity_config.celery.dict()
        service_settings["reports"] = gravity_config.reports.dict()

        galaxy_root = gravity_config.galaxy_root or app_config.get("root")

        # TODO: document that the default state_dir is data_dir/gravity and that setting state_dir overrides this
        gravity_data_dir = self.state_dir or os.path.join(app_config.get("data_dir", "database"), "gravity")
        log_dir = gravity_config.log_dir or os.path.join(gravity_data_dir, "log")

        config = ConfigFile(
            config_type=self.galaxy_server_config_section,
            gravity_config_file=gravity_config_file,
            galaxy_config_file=galaxy_config_file,
            instance_name=gravity_config.instance_name,
            process_manager=gravity_config.process_manager,
            service_command_style=gravity_config.service_command_style,
            app_server=gravity_config.app_server,
            virtualenv=gravity_config.virtualenv,
            galaxy_infrastructure_url=app_config.get("galaxy_infrastructure_url", "").rstrip("/"),
            galaxy_root=galaxy_root,
            galaxy_user=gravity_config.galaxy_user,
            galaxy_group=gravity_config.galaxy_group,
            umask=gravity_config.umask,
            memory_limit=gravity_config.memory_limit,
            gravity_data_dir=gravity_data_dir,
            log_dir=log_dir,
        )

        service_kwargs = {
            "config": config,
            "service_settings": service_settings,
        }

        # TODO: don't allow gunicorn list + unicornherder
        # TODO: do this better
        if isinstance(gravity_config.gunicorn, list):
            gunicorn_services = []
            for i, gunicorn in enumerate(gravity_config.gunicorn):
                if gunicorn.enable:
                    settings = service_settings["gunicorn"][i]
                    service_kwargs = {"config": config, "settings": settings}
                    gunicorn_services.append(service_for_service_type("gunicorn")(**service_kwargs))
            if gravity_config.service_command_style == ServiceCommandStyle.direct:
                # service instances have to be separate files if writing direct, since command lines vary by more than
                # just a single templatable integer/string
                # TODO: test this
                config.services.extend(gunicorn_services)
            else:
                config.services.append(service_for_service_type("_list_")(services=gunicorn_services, service_name="gunicorn"))
        elif gravity_config.gunicorn.enable:
            settings = service_settings["gunicorn"]
            service_kwargs = {"config": config, "settings": settings}
            config.services.append(service_for_service_type(config.app_server)(**service_kwargs))

        if gravity_config.celery.enable:
            settings = service_settings["celery"]
            service_kwargs = {"config": config, "settings": settings}
            config.services.append(service_for_service_type("celery")(**service_kwargs))
        if gravity_config.celery.enable_beat:
            settings = service_settings["celery"]
            service_kwargs = {"config": config, "settings": settings}
            config.services.append(service_for_service_type("celery-beat")(**service_kwargs))
        if gravity_config.tusd.enable:
            settings = service_settings["tusd"]
            service_kwargs = {"config": config, "settings": settings}
            config.services.append(service_for_service_type("tusd")(**service_kwargs))
        if gravity_config.reports.enable:
            settings = service_settings["reports"]
            service_kwargs = {"config": config, "settings": settings}
            config.services.append(service_for_service_type("reports")(**service_kwargs))

        # FIXME: handlers

        if not app_config.get("job_config_file") and app_config.get("job_config"):
            # config embedded directly in Galaxy config
            job_config = app_config["job_config"]
        else:
            # If this is a Galaxy config, parse job_conf.xml for any *static* standalone handlers
            job_config = app_config.get("job_config_file", DEFAULT_JOB_CONFIG_FILE)
            if not os.path.isabs(job_config):
                job_config = os.path.abspath(os.path.join(os.path.dirname(config.galaxy_config_file), job_config))
                if not os.path.exists(job_config):
                    job_config = None
        if config.config_type == "galaxy" and job_config:
            for handler_settings in ConfigManager.get_job_config(job_config):
                config.services.append(service_for_service_type("standalone")(
                    config=config,
                    service_name=handler_settings.pop("service_name"),
                    service_settings={"standalone": handler_settings},
                ))

        # FIXME: This should imply explicit configuration of the handler assignment method. If not explicitly set, the
        # web process will be a handler, which is not desirable when dynamic handlers are used. Currently Gravity
        # doesn't parse that part of the job config. See logic in lib/galaxy/web_stack/handlers.py _get_is_handler() to
        # see how this is determined.
        self.create_handler_services(gravity_config, config)
        self.create_gxit_services(gravity_config, app_config, config)
        self.__configs[config.instance_name] = config
        gravity.io.debug(f"Loaded instance {config.instance_name} from Gravity config file: {config.gravity_config_file}")
        return config

    def create_handler_services(self, gravity_config: Settings, config):
        # we pull push environment from settings to services but the rest of the services pull their env options from
        # settings directly. this can be a bit confusing but is probably ok since there are 3 ways to configure
        # handlers, and gravity is only 1 of them.
        expanded_handlers = self.expand_handlers(gravity_config, config)
        for service_name, handler_settings in expanded_handlers.items():
            if "pools" in handler_settings:
                handler_settings["server_pools"] = handler_settings.pop("pools")
            config.services.append(
                service_for_service_type("standalone")(
                    config=config,
                    service_name=service_name,
                    service_settings={"standalone": handler_settings},
                ))

    def create_gxit_services(self, gravity_config: Settings, app_config, config):
        interactivetools_enable = app_config.get("interactivetools_enable")
        if gravity_config.gx_it_proxy.enable and not interactivetools_enable:
            gravity.io.exception("To run the gx-it-proxy server you need to set interactivetools_enable in the galaxy section of galaxy.yml")
        if gravity_config.gx_it_proxy.enable:
            # TODO: resolve against data_dir, or bring in galaxy-config ?
            # CWD in supervisor template is galaxy_root, so this should work for simple cases as is
            gxit_config = gravity_config.gx_it_proxy
            gxit_config.sessions = app_config.get("interactivetools_map", gxit_config.sessions)
            # technically the tusd service doesn't have access to the rest of the settings like other services do, but it doesn't need it
            service_kwargs = dict(config=config, service_settings={"gx-it-proxy": gravity_config.gx_it_proxy.dict()})
            config.services.append(service_for_service_type("gx-it-proxy")(**service_kwargs))

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
                gravity.io.exception(f"Unknown job config file type: {conf}")
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
