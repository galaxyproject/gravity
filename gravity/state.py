""" Classes to represent and manipulate gravity's stored configuration and
state data.
"""
import json
import errno

from gravity.io import info, warn, error
from gravity.util import AttributeDict


class Service(AttributeDict):

    def __cmp__(self, other):
        return self['config_type'] == other['config_type'] \
                and self['service_type'] == other['service_type'] \
                and self['service_name'] == other['service_name']


class ConfigFile(AttributeDict):

    def __init__(self, *args, **kwargs):
        super(ConfigFile, self).__init__(*args, **kwargs)
        services = []
        for service in self.get('services', []):
            services.append(Service(service))
        self.services = services

    @property
    def defaults(self):
        return { 'instance_name' : self['instance_name'],
                 'galaxy_root' : self['attribs']['galaxy_root'],
                 'log_dir' : self['attribs']['log_dir'],
                 'virtualenv' : self['attribs']['virtualenv'] }


class GravityState(AttributeDict):

    @classmethod
    def open(cls, name):
        try:
            s = cls.loads(open(name).read())
        except (OSError, IOError) as exc:
            if exc.errno == errno.ENOENT:
                json.dump({}, open(name, 'w'))
                s = cls()
        s._name = name
        return s

    def __init__(self, *args, **kwargs):
        super(GravityState, self).__init__(*args, **kwargs)
        for key in ('config_files', 'remove_configs'):
            if key not in self:
                self[key] = {}
            for config_file, config_dict in self[key].items():
                self[key][config_file] = ConfigFile(config_dict)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        open(self._name, 'w').write(self.dumps())
        #self.dump(open(self._name, 'w'))

    def set_name(self, name):
        self._name = name
