""" Classes to represent and manipulate gravity's stored configuration and
state data.
"""
import json
import errno

from os.path import join, abspath, exists, dirname, isabs

try:
    import ConfigParser as configparser
except:
    import configparser


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
    private_options = ()

    def __cmp__(self, other):
        return self['config_type'] == other['config_type'] \
                and self['service_type'] == other['service_type'] \
                and self['service_name'] == other['service_name']


class ConfigFile(ConfigDict):
    private_options = ('config_file',)

    @staticmethod
    def validate(option, value):
        if option == 'config_file':
            value = abspath(value)
            assert ConfigFile.load(value) is not None, '%s: file type is unknown' % value
            return value
        raise Exception('%s: invalid value for %s' % (value, option))

    @classmethod
    def load(cls, conf, defaults=None):
        factory_to_type = { 'galaxy.web.buildapp:app_factory' : 'galaxy',
                            'galaxy.webapps.reports.buildapp:app_factory' : 'reports',
                            'galaxy.webapps.tool_shed.buildapp:app_factory' : 'tool_shed' }

        defs = { 'job_config_file' : 'config/job_conf.xml' }
        parser = configparser.ConfigParser(defs)

        # will raise IOError if the path is wrong
        parser.readfp(open(conf))

        try:
            app_factory = parser.get('app:main', 'paste.app_factory')
            assert app_factory in factory_to_type
        except Exception as exc:
            error("Config file does not contain 'paste.app_factory' option in '[app:main]' section. Is this a Galaxy config?: %s", exc)
            return None

        config = cls()
        config.services = {}
        config.config_file = conf
        config.config_type = factory_to_type[app_factory]

        # Paste servers and uWSGI
        paste_service_names = []
        for section in parser.sections():
            if section.startswith('server:'):
                service_name = section.split(':', 1)[1]
                try:
                    port = int(parser.get(section, 'port'))
                except configparser.Error:
                    port = 8080
                config.services['paste_' + service_name] = Service( config_type=config.config_type, service_type='paste', service_name=service_name, paste_port=port )
                paste_service_names.append(service_name)
            elif section == 'uwsgi':
                # this makes it impossible to have >1 uwsgi of the config_type per instance. which is probably fine for now.
                config.services['uwsgi'] = Service( config_type=config.config_type, service_type='uwsgi', service_name='uwsgi' )

        # If this is a Galaxy config, parse job_conf.xml for any standalone handlers
        job_conf_xml = parser.get('app:main', 'job_config_file')
        if not isabs(job_conf_xml):
            job_conf_xml = abspath(join(dirname(conf), job_conf_xml))
        if config.config_type == 'galaxy' and exists(job_conf_xml):
            for service_name in [ x['service_name'] for x in ConfigFile.get_job_config(job_conf_xml) if x['service_name'] not in paste_service_names ]:
                config.services['standalone_' + service_name] = Service( config_type=config.config_type, service_type='standalone', service_name=service_name )

        return config

    @staticmethod
    def get_job_config(conf):
        """ Extract handler names from job_conf.xml
        """
        rval = []
        root = elementtree.parse(conf).getroot()
        for handler in root.find('handlers'):
            rval.append({'service_name' : handler.attrib['id']})
        return rval

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
    private_options = ()

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
