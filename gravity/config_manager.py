""" Galaxy Process Management superclass and utilities
"""
import os
import sys
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


from gravity.io import info, warn, error
from gravity.state import GravityState, ConfigFile, Service


# FIXME
import contextlib
@contextlib.contextmanager
def config_manager(state_dir=None, python_exe=None):
    yield ConfigManager(state_dir=state_dir, python_exe=python_exe)

class ConfigManager(object):
    state_dir = '~/.galaxy'
    config_attributes = (
        'virtualenv',
        'galaxy_root',
        'uwsgi',
    )

    @staticmethod
    def get_ini_config(conf, defaults=None):
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

        config = ConfigFile()
        config.services = {}
        config.config_type = factory_to_type[app_factory]

        # shortcut for galaxy configs in the standard locations
        '''
        if config.attribs['galaxy_root'] is None:
            if exists(join(dirname(conf), pardir, 'lib', 'galaxy')):
                config.attribs['galaxy_root'] = abspath(join(dirname(conf), pardir))
            elif exists(join(dirname(conf), 'lib', 'galaxy')):
                config.attribs['galaxy_root'] = abspath(join(dirname(conf)))
            else:
                raise Exception("Cannot locate Galaxy root directory: set `galaxy_root' in the [%s] section of %s" % (section_name, conf))
        '''

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
            for service_name in [ x['service_name'] for x in ConfigManager.get_job_config(job_conf_xml) if x['service_name'] not in paste_service_names ]:
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

    def __init__(self, state_dir=None, python_exe=None):
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

    def _register_config_file(self, key, val):
        """ Persist a newly added config file, or update (overwrite) the value
        of a previously persisted config.
        """
        with self.state as state:
            state.config_files[key] = val

    def _deregister_config_file(self, key):
        """ Deregister a previously registered config file.  The caller should
        ensure that it was previously registered.
        """
        with self.state as state:
            state.remove_configs[key] = state.config_files.pop(key)

    def _purge_config_file(self, key):
        """ Forget a previously deregister config file.  The caller should
        ensure that it was previously deregistered.
        """
        with self.state as state:
            del state['remove_configs'][key]

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
                warn('Unable to read %s (hint: use `rename` or `remove` to fix): %s', config_file, exc)
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
        return GravityState.open(self.config_state_path)

    def get_instances(self):
        return self.state.instances

    def get_instance(self, name):
        return self.state.instances[name]

    def get_registered_configs(self, instances=None):
        """ Return the persisted values of all config files registered with the config manager.
        """
        configs = self.state.config_files
        if instances is not None:
            for config_file, config in configs.items():
                if config['instance_name'] not in instances:
                    configs.pop(config_file)
        return configs

    def get_remove_configs(self):
        """ Return the persisted values of all config files pending removal by the process manager.
        """
        return self.state.remove_configs

    def get_registered_config(self, config_file):
        """ Return the persisted value of the named config file.
        """
        return self.state.config_files.get(config_file, None)

    def get_registered_instances(self, include_removed=False):
        """ Return the persisted names of all instances across all registered configs.
        """
        rval = []
        configs = self.state.config_files.values()
        if include_removed:
            configs.extend(self.state.remove_configs.values())
        for config in configs:
            if config['instance_name'] not in rval:
                rval.append(config['instance_name'])
        return rval

    def get_instance_services(self, instance_name):
        rval = []
        for config_file, config in self.state.config_files.items():
            if config['instance_name'] == instance_name:
                rval.extend(config['services'])
        return rval

    def get_registered_services(self):
        rval = []
        for config_file, config in self.state.items():
            for service in config['services']:
                service['config_file'] = config_file
                service['instance_name'] = config['instance_name']
                rval.append(service)
        return rval

    def is_registered(self, config_file):
        return config_file in self.get_registered_configs()

    # cli subcommands
    def create(self, name):
        with self.state as state:
            if name not in state.instances:
                state.instances[name] = {}
                info('Created instance: %s', name)
            else:
                warn('%s already exists', name)

    def add(self, instance, config_files):
        if instance not in self.state.instances:
            self.create(instance)
        with self.state as state:
            for config_file in config_files:
                if config_file in state.instances[instance].config_files:
                    warn('%s is already registered', config_file)
                    continue
                #defaults = None
                #if galaxy_root is not None:
                #    defaults={ 'galaxy_root' : galaxy_root }
                conf = ConfigManager.get_ini_config(config_file)
                if conf is None:
                    raise Exception('Cannot add %s: File is unknown type' % config_file)
                #if conf['instance_name'] is None:
                #    conf['instance_name'] = conf['config_type'] + '-' + hashlib.md5(os.urandom(32)).hexdigest()[:12]
                #if conf['attribs']['virtualenv'] is None:
                #    conf['attribs']['virtualenv'] = abspath(join(expanduser(self.state_dir), 'virtualenv-' + conf['instance_name']))
                ## create the virtualenv if necessary
                ## FIXME: delay this so that venv name can be set with `galaxycfg set`?
                #self.create_virtualenv(conf['attribs']['virtualenv'])
                #conf_data = { 'config_type' : conf['config_type'],
                #              'instance_name' : conf['instance_name'],
                #              'attribs' : conf['attribs'],
                #              'services' : [] } # services will be populated by the update method
                #self._register_config_file(config_file, conf_data)
                info('Registered %s config: %s', conf.config_type, config_file)
                state.instances[instance].config_files[config_file] = conf

    def set(self, instance, config, service, option, value):
        with self.state as state:
            if config is None and service is None:
                # setting an instance option
                state.instances[instance].config[option] = value
            elif service is None:
                # setting a config option
                state.instances[instance][config].config[option] = value
            else:
                # setting a service option
                for cfservice in state.instances[instance][config].services:
                    if cfservice.service_name == service:
                        cfservice.config[option] = value

    def unset(self, instance, config, service, option):
        instance, config, service = (list(on) + [None, None])[:3]
        with self.state as state:
            if config is None and service is None:
                # unsetting an instance option
                if option in state.instances[instance].config:
                    state.instances[instance].config.pop(option)
            elif service is None:
                # unsetting a config option
                if option in state.instances[instance][config].config:
                    state.instances[instance][config].config.pop(option)
            else:
                # unsetting a service option
                for cfservice in state.instances[instance][config].services:
                    if cfservice.service_name == service \
                       and option in state.instances[instance][config][service].config:
                        cfservice.config.pop(option)

    def get(self, instance, config, service, option):
        if not instance:
            return self.get_instances()
        instance_data = self.get_instance(instance)
        if config:
            instance_data.config_files = instance_data.config_files[config]
        if service:
            instance_data.config_files[config].services = instance_data.config_files[config].services[service]
        return {instance : instance_data}

    def rename(self, old, new):
        if not self.is_registered(old):
            error('%s is not registered', old)
            return
        conf = ConfigManager.get_ini_config(new)
        if conf is None:
            raise Exception('Cannot add %s: File is unknown type' % new)
        with self.state as state:
            state.config_files[new] = state.config_files.pop(old)
        info('Reregistered config %s as %s', old, new)

    def remove(self, instance, config_files):
        if instance not in self.state.instances:
            warn('Instance %s does not exist' % instance)
        with self.state as state:
            for config_file in config_files:
                if config_file not in state.instances[instance]:
                    warn('%s is not registered', config_file)
                    continue
                # FIXME: this isn't going to work for supervisor of course
                state.instances[instance].pop(config_file)
                info('Deregistered config: %s', config_file)

    def create_virtualenv(self, venv_path):
        if not exists(venv_path):
            info("Creating virtualenv in: %s", venv_path)
            args = ['virtualenv']
            if self.python_exe is not None:
                args.extend(['-p', self.python_exe])
            args.append(venv_path)
            subprocess.check_call(args)

    def install_uwsgi(self, venv_path):
        if not exists(join(venv_path, 'bin', 'uwsgi')):
            info("Installing uWSGI in: %s", venv_path)
            pip = join(venv_path, 'bin', 'pip')
            args = [pip, 'install', 'PasteDeploy', 'uwsgi']
            subprocess.check_call(args)
