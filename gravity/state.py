""" Classes to represent and manipulate gravity's stored configuration and
state data.
"""
import enum
import errno

import yaml

from gravity.util import AttributeDict


class GracefulMethod(enum.Enum):
    DEFAULT = 0
    SIGHUP = 1


class Service(AttributeDict):
    service_type = "service"
    service_name = "_default_"
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


class GalaxyGunicornService(Service):
    service_type = "gunicorn"
    service_name = "gunicorn"
    graceful_method = GracefulMethod.SIGHUP
    command_template = "gunicorn 'galaxy.webapps.galaxy.fast_factory:factory()' --timeout 300" \
                       " --pythonpath lib -k galaxy.webapps.galaxy.workers.Worker -b {bind_address}:{bind_port}"


class GalaxyUnicornHerderService(Service):
    service_type = "unicornherder"
    service_name = "unicornherder"
    graceful_method = GracefulMethod.SIGHUP
    command_template = "unicornherder --pidfile {supervisor_state_dir}/{program_name}.pid --" \
                       " 'galaxy.webapps.galaxy.fast_factory:factory()' --timeout 300" \
                       " --pythonpath lib -k galaxy.webapps.galaxy.workers.Worker -b {bind_address}:{bind_port}" \
                       " --access-logfile {log_dir}/gunicorn.access.log" \
                       " --error-logfile {log_dir}/gunicorn.error.log --capture-output"


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
    command_template = "python ./lib/galaxy/main.py -c {galaxy_conf} --server-name={server_name}{attach_to_pool_opt}" \
                       " --pid-file={supervisor_state_dir}/{program_name}.pid"


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
            "bind_address": self["attribs"]["bind_address"],
            "bind_port": self["attribs"]["bind_port"],
        }


class GravityState(AttributeDict):
    @classmethod
    def open(cls, name):
        try:
            s = cls.loads(open(name).read())
        except (OSError, IOError) as exc:
            if exc.errno == errno.ENOENT:
                yaml.dump({}, open(name, "w"))
                s = cls()
        s._name = name
        return s

    def __init__(self, *args, **kwargs):
        super(GravityState, self).__init__(*args, **kwargs)
        for key in ("config_files",):
            if key not in self:
                self[key] = {}
            for config_file, config_dict in self[key].items():
                self[key][config_file] = ConfigFile(config_dict)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
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
    "standalone": GalaxyStandaloneService,
}
