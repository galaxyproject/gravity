""" Classes to represent and manipulate gravity's stored configuration and
state data.
"""
import json
import errno

from gravity.util import AttributeDict


class Service(AttributeDict):
    service_type = "service"
    service_name = "_default_"

    def __init__(self, *args, **kwargs):
        super(Service, self).__init__(*args, **kwargs)
        if "service_type" not in kwargs:
            self["service_type"] = self.__class__.service_type
        if "service_name" not in kwargs:
            self["service_name"] = self.__class__.service_name

    def __eq__(self, other):
        return self["config_type"] == other["config_type"] and self["service_type"] == other["service_type"] and self["service_name"] == other["service_name"]

    def full_match(self, other):
        return set(self.keys()) == set(other.keys()) and all([self[k] == other[k] for k in self])


class GalaxyGunicornService(Service):
    service_type = "gunicorn"
    service_name = "gunicorn"
    command_template = "gunicorn 'galaxy.webapps.galaxy.fast_factory:factory()' --timeout 300 --pythonpath lib -k galaxy.webapps.galaxy.workers.Worker -b {bind_address}:{bind_port}"

    def __init__(self, *args, **kwargs):
        super(GalaxyGunicornService, self).__init__(*args, **kwargs)
        if not kwargs.get("bind_address"):
            self["bind_address"] = self.defaults["bind_address"]
        if not kwargs.get("bind_port"):
            self["bind_port"] = self.defaults["bind_port"]

    @property
    def defaults(self):
        return {
            "bind_address": "localhost",
            "bind_port": 8080,
        }


class GalaxyCeleryService(Service):
    service_type = "celery"
    service_name = "celery"
    command_template = "celery --app galaxy.celery worker --concurrency 2 -l debug"


class GalaxyCeleryBeatService(Service):
    service_type = "celery-beat"
    service_name = "celery-beat"
    command_template = "celery --app galaxy.celery beat -l debug"


class GalaxyStandaloneService(Service):
    service_type = "standalone"
    service_name = "standalone"
    # FIXME: supervisor-specific
    command_template = "python ./lib/galaxy/main.py -c {galaxy_conf} --server-name={server_name}{attach_to_pool_opt} --pid-file={supervisor_state_dir}/{program_name}.pid"


class ConfigFile(AttributeDict):
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
            "instance_name": self["instance_name"],
            "galaxy_root": self["attribs"]["galaxy_root"],
            "log_dir": self["attribs"]["log_dir"],
        }


class GravityState(AttributeDict):
    @classmethod
    def open(cls, name):
        try:
            s = cls.loads(open(name).read())
        except (OSError, IOError) as exc:
            if exc.errno == errno.ENOENT:
                json.dump({}, open(name, "w"))
                s = cls()
        s._name = name
        return s

    def __init__(self, *args, **kwargs):
        super(GravityState, self).__init__(*args, **kwargs)
        for key in ("config_files", "remove_configs"):
            if key not in self:
                self[key] = {}
            for config_file, config_dict in self[key].items():
                self[key][config_file] = ConfigFile(config_dict)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        open(self._name, "w").write(self.dumps())
        # self.dump(open(self._name, 'w'))

    def set_name(self, name):
        self._name = name


# TODO: better to pull this from __class__.service_type
SERVICE_CLASS_MAP = {
    "gunicorn": GalaxyGunicornService,
    "celery": GalaxyCeleryService,
    "celery-beat": GalaxyCeleryBeatService,
    "standalone": GalaxyStandaloneService,
}
