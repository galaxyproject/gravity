""" Classes to represent and manipulate gravity's stored configuration and
state data.
"""
import json
import errno

from gravity.io import info, warn, error
from gravity.util import AttributeDict
from gravity.util.contextdict import ContextDict


class ConfigDict(AttributeDict):

    def __init__(self, *args, **kwargs):
        super(ConfigDict, self).__init__(*args, **kwargs)
        if 'config' not in self:
            self['config'] = {}
        self._config = ContextDict(self['config'], parent=kwargs.get('_config', None))

    @property
    def config(self):
        return self._config


class Service(ConfigDict):

    def __cmp__(self, other):
        return self['config_type'] == other['config_type'] \
                and self['service_type'] == other['service_type'] \
                and self['service_name'] == other['service_name']


class ConfigFile(ConfigDict):

    def __init__(self, *args, **kwargs):
        super(ConfigFile, self).__init__(*args, **kwargs)
        if 'services' not in self:
            self['services'] = {}
        for service_name, service_dict in self.get('services', {}).items():
            self.services[service_name] = Service(service_dict, _config=self._config)
        #services = []
        #for service in self.get('services', []):
        #    services.append(Service(service))
        #self.services = services

    @property
    def defaults(self):
        return { 'instance_name' : self['instance_name'],
                 'galaxy_root' : self['attribs']['galaxy_root'],
                 'log_dir' : self['attribs']['log_dir'],
                 'virtualenv' : self['attribs']['virtualenv'] }


class Instance(ConfigDict):

    def __init__(self, *args, **kwargs):
        super(Instance, self).__init__(*args, **kwargs)
        if 'config_files' not in self:
            self['config_files'] = {}
        for config_file, config_dict in self.get('config_files', {}).items():
            self.config_files[config_file] = ConfigFile(config_dict, _config=self._config)


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
        #for key in ('config_files', 'remove_configs', 'instances'):
        for key in ('instances',):
            if key not in self:
                self[key] = {}
        #for key in ('config_files', 'remove_configs'):
        #    for config_file, config_dict in self[key].items():
        #        self[key][config_file] = ConfigFile(config_dict)
        for instance_name, instance_data in self.instances.items():
            self.instances[instance_name] = Instance(instance_data)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        # In case there's a serialization error, don't wipe out the config
        if exc_type is None:
            s = self.dumps()
            open(self._name, 'w').write(s)
        #self.dump(open(self._name, 'w'))

    def set_name(self, name):
        self._name = name
