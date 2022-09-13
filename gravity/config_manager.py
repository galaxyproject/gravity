""" Galaxy Process Management superclass and utilities
"""
import contextlib
import errno
import hashlib
import logging
import os
import shutil
import xml.etree.ElementTree as elementtree
from os import pardir
from os.path import abspath, dirname, exists, expanduser, isabs, join
from typing import Union

import packaging.version
from yaml import safe_load

from gravity.settings import Settings
from gravity.io import debug, error, exception, info, warn
from gravity.state import (
    ConfigFile,
    GravityState,
    service_for_service_type,
)
from gravity.util import recursive_update, yaml_safe_load_with_include

log = logging.getLogger(__name__)

DEFAULT_JOB_CONFIG_FILE = "config/job_conf.xml"
DEFAULT_STATE_DIR = join("~", ".config", "galaxy-gravity")
if "XDG_CONFIG_HOME" in os.environ:
    DEFAULT_STATE_DIR = join(os.environ["XDG_CONFIG_HOME"], "galaxy-gravity")


@contextlib.contextmanager
def config_manager(state_dir=None, python_exe=None):
    yield ConfigManager(state_dir=state_dir, python_exe=python_exe)


class ConfigManager(object):
    galaxy_server_config_section = "galaxy"
    gravity_config_section = "gravity"

    def __init__(self, state_dir=None, python_exe=None):
        if state_dir is None:
            state_dir = DEFAULT_STATE_DIR
        self.state_dir = abspath(expanduser(state_dir))
        debug(f"Gravity state dir: {self.state_dir}")
        self.__configs = {}
        self.config_state_path = join(self.state_dir, "configstate.yaml")
        self.python_exe = python_exe
        try:
            os.makedirs(self.state_dir)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
        self.__convert_config()

    def __copy_config(self, old_path):
        with GravityState.open(old_path) as state:
            state.set_name(self.config_state_path)
        # copies on __exit__

    def __backup_config(self, backup_ext):
        backup_path = f"{self.config_state_path}.{backup_ext}"
        info(f"Previous Gravity config state saved in: {backup_path}")
        shutil.copy(self.config_state_path, backup_path)

    def __convert_config(self):
        # the gravity version has been included in the configstate since 0.10.0, but it was previously a configfile
        # attrib, which doesn't really make sense, and 1.0.0 removes persisted configfile attribs anyway
        state_version = self.state.get("gravity_version")
        debug(f"Gravity state version: {state_version}")
        if not state_version or (packaging.version.parse(state_version) < packaging.version.parse("1.0.0")):
            # this hardcoded versioning suffices for now, might have to get fancier in the future
            with self.state as state:
                self.__convert_config_1_0(state)

    def __convert_config_1_0(self, state):
        info("Converting Gravity config state to 1.0 format, this will only occur once")
        self.__backup_config("pre-1.0")
        for config_file, config in state.config_files.items():
            try:
                config.galaxy_root = config.attribs["galaxy_root"]
            except KeyError:
                warn(f"Unable to read 'galaxy_root' from attribs: {config.attribs}")
            for key in list(config.keys()):
                if key not in ConfigFile.persist_keys:
                    del config[key]
            state.config_files[config_file] = config

    def get_config(self, conf, defaults=None):
        if conf in self.__configs:
            return self.__configs[conf]

        defaults = defaults or {}
        server_section = self.galaxy_server_config_section
        with open(conf) as config_fh:
            config_dict = yaml_safe_load_with_include(config_fh)
        _gravity_config = config_dict.get(self.gravity_config_section) or {}
        gravity_config = Settings(**recursive_update(defaults, _gravity_config))
        if gravity_config.log_dir is None:
            gravity_config.log_dir = join(expanduser(self.state_dir), "log")

        if server_section not in config_dict and self.gravity_config_section not in config_dict:
            error(f"Config file {conf} does not look like valid Galaxy, Reports or Tool Shed configuration file")
            return None

        app_config = config_dict.get(server_section) or {}

        config = ConfigFile()
        config.attribs = {}
        config.services = []
        config.__file__ = conf
        config.instance_name = gravity_config.instance_name
        config.config_type = server_section
        config.process_manager = gravity_config.process_manager
        # FIXME: should this be attribs?
        config.attribs["galaxy_infrastructure_url"] = app_config.get("galaxy_infrastructure_url", "").rstrip("/")
        if gravity_config.tusd.enable and not config.attribs["galaxy_infrastructure_url"]:
            exception("To run the tusd server you need to set galaxy_infrastructure_url in the galaxy section of galaxy.yml")
        config.attribs["app_server"] = gravity_config.app_server
        config.attribs["log_dir"] = gravity_config.log_dir
        config.attribs["virtualenv"] = gravity_config.virtualenv
        config.attribs["gunicorn"] = gravity_config.gunicorn.dict()
        config.attribs["tusd"] = gravity_config.tusd.dict()
        config.attribs["celery"] = gravity_config.celery.dict()
        config.attribs["handlers"] = gravity_config.handlers
        # Store gravity version, in case we need to convert old setting
        webapp_service_names = []

        # shortcut for galaxy configs in the standard locations -- explicit arg ?
        config["galaxy_root"] = app_config.get("root") or gravity_config.galaxy_root
        if config["galaxy_root"] is None:
            if os.environ.get("GALAXY_ROOT_DIR"):
                config["galaxy_root"] = abspath(os.environ["GALAXY_ROOT_DIR"])
            elif exists(join(dirname(conf), pardir, "lib", "galaxy")):
                config["galaxy_root"] = abspath(join(dirname(conf), pardir))
            elif conf.endswith(join('galaxy', 'config', 'sample', 'galaxy.yml.sample')):
                config["galaxy_root"] = abspath(join(dirname(conf), pardir, pardir, pardir, pardir))
            else:
                exception(f"Cannot locate Galaxy root directory: set $GALAXY_ROOT_DIR or `root' in the `galaxy' section of {conf}")

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
            for handler_settings in [x for x in ConfigManager.get_job_config(job_config) if x["service_name"] not in webapp_service_names]:
                config.services.append(service_for_service_type("standalone")(
                    config_type=config.config_type,
                    service_name=handler_settings["service_name"],
                    environment=handler_settings.get("environment")
                ))

        # FIXME: This should imply explicit configuration of the handler assignment method. If not explicitly set, the
        # web process will be a handler, which is not desirable when dynamic handlers are used. Currently Gravity
        # doesn't parse that part of the job config. See logic in lib/galaxy/web_stack/handlers.py _get_is_handler() to
        # see how this is determined.
        self.create_handler_services(gravity_config, config)
        self.create_gxit_services(gravity_config, app_config, config)
        self.__configs[conf] = config
        return config

    def create_handler_services(self, gravity_config: Settings, config):
        expanded_handlers = self.expand_handlers(gravity_config, config)
        for service_name, handler_settings in expanded_handlers.items():
            pools = handler_settings.get('pools')
            environment = handler_settings.get("environment")
            config.services.append(
                service_for_service_type("standalone")(
                    config_type=config.config_type,
                    service_name=service_name,
                    server_pools=pools,
                    environment=environment
                ))

    def create_gxit_services(self, gravity_config: Settings, app_config, config):
        if app_config.get("interactivetools_enable") and gravity_config.gx_it_proxy.enable:
            # TODO: resolve against data_dir, or bring in galaxy-config ?
            # CWD in supervisor template is galaxy_root, so this should work for simple cases as is
            gxit_config = gravity_config.gx_it_proxy
            gxit_config.sessions = app_config.get("interactivetools_map", gxit_config.sessions)
            gxit_config.verbose = '--verbose' if gxit_config.verbose else ''
            config.services.append(service_for_service_type("gx-it-proxy")(config_type=config.config_type))
        config.attribs["gx_it_proxy"] = gravity_config.gx_it_proxy.dict()

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

    def _register_config_file(self, key, val):
        """Persist a newly added config file, or update (overwrite) the value
        of a previously persisted config.
        """
        with self.state as state:
            state.config_files[key] = val

    def _deregister_config_file(self, key):
        """Deregister a previously registered config file.  The caller should
        ensure that it was previously registered.
        """
        with self.state as state:
            del state.config_files[key]

    @property
    def state(self):
        """Public property to access persisted config state"""
        return GravityState.open(self.config_state_path)

    @property
    def instance_count(self):
        """The number of configured instances"""
        return len(self.state.config_files)

    @property
    def single_instance(self):
        """Indicate if there is only one configured instance"""
        return self.instance_count == 1

    def get_registered_configs(self, instances=None):
        """Return the persisted values of all config files registered with the config manager."""
        rval = []
        config_files = self.state.config_files
        for config_file, config in list(config_files.items()):
            if (instances is not None and config["instance_name"] in instances) or instances is None:
                rval.append(self.get_config(config_file))
        return rval

    def get_registered_config(self, config_file):
        """Return the persisted value of the named config file."""
        if config_file in self.state.config_files:
            return self.get_config(config_file)
        return None

    def get_registered_instance_names(self):
        return [c["instance_name"] for c in self.state.config_files.values()]

    def auto_register(self):
        """Attempt to automatically register a config file if none are registered."""
        if self.instance_count == 0:
            if os.environ.get("GALAXY_CONFIG_FILE"):
                configs = [os.environ["GALAXY_CONFIG_FILE"]]
            else:
                configs = (os.path.join("config", "galaxy.yml"), os.path.join("config", "galaxy.yml.sample"))
            for config in configs:
                if exists(config):
                    # This should always be the case if instance_count == 0
                    if not self.is_registered(abspath(config)):
                        self.add([config])
                    return

    def is_registered(self, config_file):
        return config_file in self.state.config_files

    def add(self, config_files, galaxy_root=None):
        """Public method to add (register) config file(s)."""
        for config_file in config_files:
            config_file = abspath(expanduser(config_file))
            if self.is_registered(config_file):
                warn("%s is already registered", config_file)
                continue
            defaults = None
            if galaxy_root is not None:
                defaults = {"galaxy_root": galaxy_root}
            conf = self.get_config(config_file, defaults=defaults)
            if conf is None:
                exception(f"Cannot add {config_file}: File is unknown type")
            if conf["instance_name"] is None:
                conf["instance_name"] = conf["config_type"] + "-" + hashlib.md5(os.urandom(32)).hexdigest()[:12]
            conf_data = {}
            for key in ConfigFile.persist_keys:
                conf_data[key] = conf[key]
            self._register_config_file(config_file, conf_data)
            info("Registered %s config: %s", conf["config_type"], config_file)

    def rename(self, old, new):
        if not self.is_registered(old):
            error("%s is not registered", old)
            return
        conf = self.get_config(new)
        if conf is None:
            exception(f"Cannot add {new}: File is unknown type")
        with self.state as state:
            state.config_files[new] = state.config_files.pop(old)
        info("Reregistered config %s as %s", old, new)

    def remove(self, config_files):
        # FIXME: paths are checked by click now
        # allow the arg to be instance names
        configs_by_instance = self.get_registered_configs(instances=config_files)
        if configs_by_instance:
            supplied_config_files = []
            config_files = list(configs_by_instance.keys())
        else:
            supplied_config_files = [abspath(cf) for cf in config_files]
            config_files = []
        for config_file in supplied_config_files:
            if not self.is_registered(config_file):
                warn("%s is not registered", config_file)
            else:
                config_files.append(config_file)
        for config_file in config_files:
            self._deregister_config_file(config_file)
            info("Deregistered config: %s", config_file)
