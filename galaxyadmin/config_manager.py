""" Galaxy Process Management superclass and utilities
"""
from __future__ import print_function

import os
import sys
import json
import errno
import logging
import hashlib
import subprocess
import setproctitle
import xml.etree.ElementTree as elementtree

from os import pardir
from os.path import join, abspath, exists, expanduser, dirname, isabs

try:
    import ConfigParser as configparser
except:
    import configparser

log = logging.getLogger(__name__)


class AttributeDict(dict):
    def __setattr__(self, name, value):
        self[name] = value

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError("'%s' object has no attribute '%s'" % (self.__class__.__name__, name))


class Service(AttributeDict):
    def __cmp__(self, other):
        return self['config_type'] == other['config_type'] \
                and self['service_type'] == other['service_type'] \
                and self['service_name'] == other['service_name']


class ConfigFile(AttributeDict):
    def __init__(self, *args, **kwargs):
        super(ConfigFile, self).__init__(*args, **kwargs)
        if args and 'services' in args[0]:
            self['services'] = []
            for service in args[0]['services']:
                self['services'].append(Service(service))

    @property
    def defaults(self):
        return { 'instance_name' : self['instance_name'],
                 'galaxy_root' : self['attribs']['galaxy_root'],
                 'log_dir' : self['attribs']['log_dir'],
                 'virtualenv' : self['attribs']['virtualenv'] }

class ConfigState(AttributeDict):
    def __init__(self, *args, **kwargs):
        super(ConfigState, self).__init__(*args, **kwargs)
        for key in ('config_files', 'remove_configs'):
            if args and key in args[0]:
                for config_file, config_dict in args[0].get(key).items():
                    self[key][config_file] = ConfigFile(config_dict)


class ConfigManager(object):
    state_dir = '~/.galaxy'
    galaxy_server_config_section = 'galaxy:server'

    @staticmethod
    def get_ini_config(conf, defaults=None):
        server_section = ConfigManager.galaxy_server_config_section
        factory_to_type = { 'galaxy.web.buildapp:app_factory' : 'galaxy',
                            'galaxy.webapps.reports.buildapp:app_factory' : 'reports',
                            'galaxy.webapps.tool_shed.buildapp:app_factory' : 'tool_shed' }

        defs = { 'galaxy_root' : None,
                 'log_dir' : join(expanduser(ConfigManager.state_dir), 'log'),
                 'instance_name' : None,
                 'job_config_file' : 'config/job_conf.xml',
                 'virtualenv' : None,
                 'uwsgi_path' : None }
        if defaults is not None:
            defs.update(defaults)
        parser = configparser.ConfigParser(defs)

        # will raise IOError if the path is wrong
        parser.readfp(open(conf))

        try:
            app_factory = parser.get('app:main', 'paste.app_factory')
            assert app_factory in factory_to_type
        except Exception as exc:
            log.error("Config file does not contain 'paste.app_factory' option in '[app:main]' section. Is this a Galaxy config?: %s", exc)
            return None

        if server_section not in parser.sections():
            parser.add_section(server_section)

        config = ConfigFile()
        config.attribs = {}
        config.services = []
        config.instance_name = parser.get(server_section, 'instance_name') or None
        config.config_type = factory_to_type[app_factory]

        # shortcut for galaxy configs in the standard locations
        config.attribs['galaxy_root'] =  parser.get(server_section, 'galaxy_root')
        if config.attribs['galaxy_root'] is None:
            if exists(join(dirname(conf), pardir, 'lib', 'galaxy')):
                config.attribs['galaxy_root'] = abspath(join(dirname(conf), pardir))
            elif exists(join(dirname(conf), 'lib', 'galaxy')):
                config.attribs['galaxy_root'] = abspath(join(dirname(conf)))
            else:
                raise Exception("Cannot locate Galaxy root directory: set `galaxy_root' in the [%s] section of %s" % (section_name, conf))

        config.attribs['uwsgi_path'] = parser.get(server_section, 'uwsgi_path')

        # path attributes used for service definitions or other things that should cause updating
        for name in ('virtualenv', 'log_dir'):
            val = parser.get(server_section, name)
            if val is not None:
                val = abspath(expanduser(val))
            config.attribs[name] = val

        # Paste servers and uWSGI
        paste_service_names = []
        for section in parser.sections():
            if section.startswith('server:'):
                service_name = section.split(':', 1)[1]
                try:
                    port = int(parser.get(section, 'port'))
                except configparser.Error:
                    port = 8080
                config.services.append(Service( config_type=config.config_type, service_type='paste', service_name=service_name, paste_port=port ))
                paste_service_names.append(service_name)
            elif section == 'uwsgi':
                # this makes it impossible to have >1 uwsgi of the config_type per instance. which is probably fine for now.
                config.services.append(Service( config_type=config.config_type, service_type='uwsgi', service_name='uwsgi' ))

        # If this is a Galaxy config, parse job_conf.xml for any standalone handlers
        job_conf_xml = parser.get('app:main', 'job_config_file')
        if not isabs(job_conf_xml):
            job_conf_xml = abspath(join(config.attribs['galaxy_root'], job_conf_xml))
        if config.config_type == 'galaxy' and exists(job_conf_xml):
            for service_name in [ x['service_name'] for x in ConfigManager.get_job_config(job_conf_xml) if x['service_name'] not in paste_service_names ]:
                config.services.append(Service( config_type=config.config_type, service_type='standalone', service_name=service_name ))

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

    def __init__(self, state_dir=None, galaxy_root=None, python_exe=None):
        if state_dir is None:
            state_dir = ConfigManager.state_dir
        self.state_dir = abspath(expanduser(state_dir))
        self.config_state_path = join(self.state_dir, 'configstate.json')
        self.python_exe = python_exe
        try:
            os.makedirs(self.state_dir)
        except (IOError, OSError) as exc:
            if exc.errno != errno.EEXIST:
                raise

    def __load_state(self):
        """ Read persisted state from the JSON statefile
        """
        try:
            return ConfigState(json.load(open(self.config_state_path)))
        except (OSError, IOError) as exc:
            if exc.errno == errno.ENOENT:
                self.__dump_state({})
                return json.load(open(self.config_state_path))
            raise

    def __dump_state(self, newstate):
        """ Save state to the JSON statefile
        """
        json.dump(newstate, open(self.config_state_path, 'w'))

    def _register_config_file(self, key, val):
        """ Persist a newly added config file, or update (overwrite) the value
        of a previously persisted config.
        """
        state = self.__load_state()
        if 'config_files' not in state:
            state['config_files'] = {}
        state['config_files'][key] = val
        self.__dump_state(state)

    def _deregister_config_file(self, key):
        """ Deregister a previously registered config file.  The caller should
        ensure that it was previously registered.
        """
        state = self.__load_state()
        if 'remove_configs' not in state:
            state['remove_configs'] = {}
        state['remove_configs'][key] = (state['config_files'].pop(key))
        self.__dump_state(state)

    def _purge_config_file(self, key):
        """ Forget a previously deregister config file.  The caller should
        ensure that it was previously deregistered.
        """
        state = self.__load_state()
        del state['remove_configs'][key]
        self.__dump_state(state)

    def determine_config_changes(self):
        """ The magic: Determine what has changed since the last time.

        Caller should pass the returned config to register_config_changes to persist.
        """
        # 'update' here is synonymous with 'add or update'
        instances = set()
        new_configs = {}
        meta_changes = { 'changed_instances' : set(),
                         'remove_instances' : [],
                         'remove_configs' : self.get_remove_configs() }
        for config_file, stored_config in self.get_registered_configs().items():
            new_config = stored_config
            try:
                ini_config = ConfigManager.get_ini_config(config_file, defaults=stored_config.defaults)
            except (OSError, IOError) as exc:
                log.warning('Unable to read %s (hint: use `rename` or `remove` to fix): %s', config_file, exc)
                new_configs[config_file] = stored_config
                instances.add(stored_config['instance_name'])
                continue
            if ini_config['instance_name'] is not None:
                # instance name is explicitly set in the config
                instance_name = ini_config['instance_name']
                if ini_config['instance_name'] != stored_config['instance_name']:
                    # instance name has changed
                    # (removal of old instance will happen later if no other config references it)
                    new_config['update_instance_name'] = instance_name
                meta_changes['changed_instances'].add(instance_name)
            else:
                # instance name is dynamically generated
                instance_name = stored_config['instance_name']
            if ini_config['attribs'] != stored_config['attribs']:
                # Ensure that dynamically generated virtualenv is not lost
                if ini_config['attribs']['virtualenv'] is None:
                    ini_config['attribs']['virtualenv'] = stored_config['attribs']['virtualenv']
                # Recheck to see if dynamic virtualenv was the only change.
                if ini_config['attribs'] != stored_config['attribs']:
                    self.create_virtualenv(ini_config['attribs']['virtualenv'])
                    new_config['update_attribs'] = ini_config['attribs']
                    meta_changes['changed_instances'].add(instance_name)
            # make sure this instance isn't removed
            instances.add(instance_name)
            services = []
            for service in ini_config['services']:
                if service not in stored_config['services']:
                    # instance has a new service
                    if 'update_services' not in new_config:
                        new_config['update_services'] = []
                    new_config['update_services'].append(service)
                    meta_changes['changed_instances'].add(instance_name)
                # make sure this service isn't removed
                services.append(service)
            for service in stored_config['services']:
                if service not in services:
                    if 'remove_services' not in new_config:
                        new_config['remove_services'] = []
                    new_config['remove_services'].append(service)
                    meta_changes['changed_instances'].add(instance_name)
            new_configs[config_file] = new_config
        # once finished processing all configs, find any instances which have been deleted
        for instance_name in self.get_registered_instances(include_removed=True):
            if instance_name not in instances:
                meta_changes['remove_instances'].append(instance_name)
        return new_configs, meta_changes

    def register_config_changes(self, configs, meta_changes):
        """ Persist config changes to the JSON state file. When a config
        changes, a process manager may perform certain actions based on these
        changes. This method can be called once the actions are complete.
        """
        for config_file in meta_changes['remove_configs'].keys():
            self._purge_config_file(config_file)
        for config_file, config in configs.items():
            if 'update_attribs' in config:
                config['attribs'] = config.pop('update_attribs')
            if 'update_instance_name' in config:
                config['instance_name'] = config.pop('update_instance_name')
            if 'update_services' in config or 'remove_services' in config:
                remove = config.pop('remove_services', [])
                services = config.pop('update_services', [])
                # need to prevent old service defs from overwriting new ones
                for service in config['services']:
                    if service not in remove and service not in services:
                        services.append(service)
                config['services'] = services
            self._register_config_file(config_file, config)

    @property
    def state(self):
        """ Public property to access persisted config state
        """
        return self.__load_state()

    def get_registered_configs(self, instances=None):
        """ Return the persisted values of all config files registered with the config manager.
        """
        configs = self.state.get('config_files', {})
        if instances is not None:
            for config_file, config in configs.items():
                if config['instance_name'] not in instances:
                    configs.pop(config_file)
        return configs

    def get_remove_configs(self):
        """ Return the persisted values of all config files pending removal by the process manager.
        """
        return self.state.get('remove_configs', {})

    def get_registered_config(self, config_file):
        """ Return the persisted value of the named config file.
        """
        return self.state.get('config_files', {}).get(config_file, None)

    def get_registered_instances(self, include_removed=False):
        """ Return the persisted names of all instances across all registered configs.
        """
        rval = []
        configs = self.state.get('config_files', {}).values()
        if include_removed:
            configs.extend(self.state.get('remove_configs', {}).values())
        for config in configs:
            if config['instance_name'] not in rval:
                rval.append(config['instance_name'])
        return rval

    def get_instance_services(self, instance_name):
        rval = []
        for config_file, config in self.state.get('config_files', {}).items():
            if config['instance_name'] == instance_name:
                rval.extend(config['services'])
        return rval

    def get_registered_services(self):
        rval = []
        for config_file, config in self.state.get('config_files', {}).items():
            for service in config['services']:
                service['config_file'] = config_file
                service['instance_name'] = config['instance_name']
                rval.append(service)
        return rval

    def is_registered(self, config_file):
        return config_file in self.get_registered_configs()

    def add(self, config_files, galaxy_root=None):
        """ Public method to add (register) config file(s).
        """
        for config_file in config_files:
            config_file = abspath(expanduser(config_file))
            if self.is_registered(config_file):
                log.warning('%s is already registered', config_file)
                continue
            defaults = None
            if galaxy_root is not None:
                defaults={ 'galaxy_root' : galaxy_root }
            conf = ConfigManager.get_ini_config(config_file, defaults=defaults)
            if conf is None:
                raise Exception('Cannot add %s: File is unknown type' % config_file)
            if conf['instance_name'] is None:
                conf['instance_name'] = conf['config_type'] + '-' + hashlib.md5(os.urandom(32)).hexdigest()[:12]
            if conf['attribs']['virtualenv'] is None:
                conf['attribs']['virtualenv'] = abspath(join(expanduser(self.state_dir), 'virtualenv-' + conf['instance_name']))
            # create the virtualenv if necessary
            self.create_virtualenv(conf['attribs']['virtualenv'])
            conf_data = { 'config_type' : conf['config_type'],
                          'instance_name' : conf['instance_name'],
                          'attribs' : conf['attribs'],
                          'services' : [] } # services will be populated by the update method
            self._register_config_file(config_file, conf_data)
            log.info('Added %s config: %s', conf['config_type'], config_file)

    def rename(self, old, new):
        old = abspath(old)
        new = abspath(new)
        if not self.is_registered(old):
            log.error('%s is not registered', old)
            return
        conf = ConfigManager.get_ini_config(new)
        if conf is None:
            raise Exception('Cannot add %s: File is unknown type' % new)
        newstate = self.state
        state['config_files'][new] = state['config_files'].pop(old)
        self.__dump_state(newstate)
        log.info('Renamed config %s as %s', old, new)

    def remove(self, config_files):
        # allow the arg to be instance names
        configs_by_instance = self.get_registered_configs(instances=config_files)
        if configs_by_instance:
            supplied_config_files = []
            config_files = configs_by_instance.keys()
        else:
            supplied_config_files = [ abspath(cf) for cf in config_files ]
            config_files = []
        for config_file in supplied_config_files:
            if not self.is_registered(config_file):
                log.warning('%s is not registered', config_file)
            else:
                config_files.append(config_file)
        for config_file in config_files:
            self._deregister_config_file(config_file)
            log.info('Removed config: %s', config_file)

    def create_virtualenv(self, venv_path):
        if not exists(venv_path):
            log.info("Creating virtualenv in: %s", venv_path)
            args = ['virtualenv']
            if self.python_exe is not None:
                args.extend(['-p', self.python_exe])
            args.append(venv_path)
            subprocess.check_call(args)

    def install_uwsgi(self, venv_path):
        if not exists(join(venv_path, 'bin', 'uwsgi')):
            log.info("Installing uWSGI in: %s", venv_path)
            pip = join(venv_path, 'bin', 'pip')
            args = [pip, 'install', 'PasteDeploy', 'uwsgi']
            subprocess.check_call(args)
