""" Galaxy Process Management superclass and utilities
"""
import contextlib
import errno
import hashlib
import logging
import os
import xml.etree.ElementTree as elementtree
from os import pardir
from os.path import abspath, dirname, exists, expanduser, isabs, join
from typing import Union

from yaml import safe_load

from gravity import __version__
from gravity.settings import Settings
from gravity.io import debug, error, exception, info, warn
from gravity.state import (
    ConfigFile,
    GravityState,
    service_for_service_type,
)
from gravity.util import recursive_update

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

    def __convert_config(self):
        config_state_json = join(self.state_dir, "configstate.json")
        if exists(config_state_json) and not exists(self.config_state_path):
            warn(f"Converting {config_state_json} to {self.config_state_path}")
            json_state = GravityState.open(config_state_json)
            self.__copy_config(config_state_json)
            assert exists(self.config_state_path), f"Conversion failed ({self.config_state_path} does not exist)"
            yaml_state = GravityState.open(self.config_state_path)
            assert json_state == yaml_state, f"Converted config differs from previous config, remove {self.config_state_path} to retry"
            os.unlink(config_state_json)

    def get_config(self, conf, defaults=None):
        defaults = defaults or {}
        server_section = self.galaxy_server_config_section
        with open(conf) as config_fh:
            config_dict = safe_load(config_fh)
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
        config.instance_name = gravity_config.instance_name
        config.config_type = server_section
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
        config.attribs['gravity_version'] = __version__
        webapp_service_names = []

        # shortcut for galaxy configs in the standard locations -- explicit arg ?
        config.attribs["galaxy_root"] = app_config.get("root") or gravity_config.galaxy_root
        if config.attribs["galaxy_root"] is None:
            if os.environ.get("GALAXY_ROOT_DIR"):
                config.attribs["galaxy_root"] = abspath(os.environ["GALAXY_ROOT_DIR"])
            elif exists(join(dirname(conf), pardir, "lib", "galaxy")):
                config.attribs["galaxy_root"] = abspath(join(dirname(conf), pardir))
            elif conf.endswith(join('galaxy', 'config', 'sample', 'galaxy.yml.sample')):
                config.attribs["galaxy_root"] = abspath(join(dirname(conf), pardir, pardir, pardir, pardir))
            else:
                exception(f"Cannot locate Galaxy root directory: set $GALAXY_ROOT_DIR or `root' in the `galaxy' section of {conf}")

        config.services.append(service_for_service_type(config.attribs["app_server"])(config_type=config.config_type))
        config.services.append(service_for_service_type("celery")(config_type=config.config_type))
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
                job_config = abspath(join(config.attribs["galaxy_root"], job_config))
                if not exists(job_config):
                    job_config = None
        if config.config_type == "galaxy" and job_config:
            for service_name in [x["service_name"] for x in ConfigManager.get_job_config(job_config) if x["service_name"] not in webapp_service_names]:
                config.services.append(service_for_service_type("standalone")(config_type=config.config_type, service_name=service_name))

        # Dynamic job handlers are configured using `job_handler_count` in galaxy.yml.
        #
        # FIXME: This should imply explicit configuration of the handler assignment method. If not explicitly set, the
        # web process will be a handler, which is not desirable when dynamic handlers are used. Currently Gravity
        # doesn't parse that part of the job config. See logic in lib/galaxy/web_stack/handlers.py _get_is_handler() to
        # see how this is determined.
        self.create_handler_services(gravity_config, config)
        self.create_gxit_services(gravity_config, app_config, config)
        return config

    def create_handler_services(self, gravity_config: Settings, config):
        expanded_handlers = self.expand_handlers(gravity_config, config)
        for service_name, handler_settings in expanded_handlers.items():
            pools = handler_settings.get('pools')
            config.services.append(
                service_for_service_type("standalone")(config_type=config.config_type, service_name=service_name, server_pools=pools))

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
            processes = handling.get('processes') or []
            for handler in processes:
                rval.append({"service_name": handler})
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
            if "remove_configs" not in state:
                state.remove_configs = {}
            state.remove_configs[key] = state.config_files.pop(key)

    def _purge_config_file(self, key):
        """Forget a previously deregister config file.  The caller should
        ensure that it was previously deregistered.
        """
        with self.state as state:
            del state.remove_configs[key]
            if not state.remove_configs:
                del state["remove_configs"]

    def determine_config_changes(self):
        """The magic: Determine what has changed since the last time.

        Caller should pass the returned config to register_config_changes to persist.
        """
        # 'update' here is synonymous with 'add or update'
        instances = set()
        new_configs = {}
        meta_changes = {"changed_instances": set(), "remove_instances": [], "remove_configs": self.get_remove_configs()}
        for config_file, stored_config in self.get_registered_configs().items():
            new_config = stored_config
            try:
                ini_config = self.get_config(config_file, defaults=stored_config.defaults)
            except OSError as exc:
                warn("Unable to read %s (hint: use `rename` or `remove` to fix): %s", config_file, exc)
                new_configs[config_file] = stored_config
                instances.add(stored_config["instance_name"])
                continue
            if ini_config["instance_name"] is not None:
                # instance name is explicitly set in the config
                instance_name = ini_config["instance_name"]
                if ini_config["instance_name"] != stored_config["instance_name"]:
                    # instance name has changed
                    # (removal of old instance will happen later if no other config references it)
                    new_config["update_instance_name"] = instance_name
                meta_changes["changed_instances"].add(instance_name)
            else:
                # instance name is dynamically generated
                instance_name = stored_config["instance_name"]
            if ini_config["attribs"] != stored_config["attribs"]:
                new_config["update_attribs"] = ini_config["attribs"]
                meta_changes["changed_instances"].add(instance_name)
            # make sure this instance isn't removed
            instances.add(instance_name)
            services = []
            for service in ini_config["services"]:
                for stored_service in stored_config["services"]:
                    if service.full_match(stored_service):
                        # service is configured and has no changes
                        break
                else:
                    # instance has a new service or service has config change
                    if "update_services" not in new_config:
                        new_config["update_services"] = []
                    new_config["update_services"].append(service)
                    meta_changes["changed_instances"].add(instance_name)
                # make sure this service isn't removed
                services.append(service)
            for service in stored_config["services"]:
                if service not in services:
                    if "remove_services" not in new_config:
                        new_config["remove_services"] = []
                    new_config["remove_services"].append(service)
                    meta_changes["changed_instances"].add(instance_name)
            new_configs[config_file] = new_config
        # once finished processing all configs, find any instances which have been deleted
        for instance_name in self.get_registered_instances(include_removed=True):
            if instance_name not in instances:
                meta_changes["remove_instances"].append(instance_name)
        return new_configs, meta_changes

    def register_config_changes(self, configs, meta_changes):
        """Persist config changes to the JSON state file. When a config
        changes, a process manager may perform certain actions based on these
        changes. This method can be called once the actions are complete.
        """
        for config_file in meta_changes["remove_configs"].keys():
            self._purge_config_file(config_file)
        for config_file, config in configs.items():
            if "update_attribs" in config:
                config["attribs"] = config.pop("update_attribs")
            if "update_instance_name" in config:
                config["instance_name"] = config.pop("update_instance_name")
            if "update_services" in config or "remove_services" in config:
                remove = config.pop("remove_services", [])
                services = config.pop("update_services", [])
                # need to prevent old service defs from overwriting new ones
                for service in config["services"]:
                    if service not in remove and service not in services:
                        services.append(service)
                config["services"] = services
            self._register_config_file(config_file, config)

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
        configs = self.state.config_files
        if instances is not None:
            for config_file, config in list(configs.items()):
                if config["instance_name"] not in instances:
                    configs.pop(config_file)
        return configs

    def get_remove_configs(self):
        """Return the persisted values of all config files pending removal by the process manager."""
        return self.state.get("remove_configs", {})

    def get_registered_config(self, config_file):
        """Return the persisted value of the named config file."""
        return self.state.config_files.get(config_file, None)

    def get_registered_instances(self, include_removed=False):
        """Return the persisted names of all instances across all registered configs."""
        rval = []
        configs = list(self.state.config_files.values())
        if include_removed:
            configs.extend(list(self.get_remove_configs().values()))
        for config in configs:
            if config["instance_name"] not in rval:
                rval.append(config["instance_name"])
        return rval

    def get_instance_config(self, instance_name):
        for config in list(self.state.config_files.values()):
            if config["instance_name"] == instance_name:
                return config
        exception(f'Instance "{instance_name}" unknown, known instance(s) are {", ".join(self.get_registered_instance_names())}.')

    def get_registered_instance_names(self):
        return [c['instance_name'] for c in self.state.config_files.values()]

    def get_instance_services(self, instance_name):
        return self.get_instance_config(instance_name)["services"]

    def get_registered_services(self):
        rval = []
        for config_file, config in self.state.config_files.items():
            for service in config["services"]:
                service["config_file"] = config_file
                service["instance_name"] = config["instance_name"]
                rval.append(service)
        return rval

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
        return config_file in self.get_registered_configs()

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
            conf_data = {
                "config_type": conf["config_type"],
                "instance_name": conf["instance_name"],
                "attribs": conf["attribs"],
                "services": [],  # services will be populated by the update method
            }
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
