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
from gravity.state import GravityState, Instance, ConfigFile, Service


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
    def validate(option, value):
        def _path():
            v = abspath(expanduser(value))
            assert exists(v), '%s: does not exist' % v
            return v

        if option == 'uwsgi':
            if value == 'install':
                return value
            return _path()
        elif option in ('galaxy_root', 'virtualenv'):
            return _path()

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

    def __parse_ics(self, ics):
        try:
            return (ics.split('/') + [None, None, None])[:3]
        except AttributeError:
            return None, None, None

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

    def get_config_files(self, instance):
        return [ config.config_file for config in self.state.instances[instance].config_files.values() ]

    def get_ics_object(self, ics, state=None):
        instance, config, service = self.__parse_ics(ics)
        if state is None:
            state = self.state
        if config is None and service is None:
            # setting an instance option
            return state.instances[instance]
        elif service is None:
            # setting a config option
            return state.instances[instance].config_files[config]
        else:
            # setting a service option
            return state.instances[instance].config_files[config] \
                   .services[service]

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
    def create(self, ic, config_file):
        instance, config, service = self.__parse_ics(ic)
        created_instance = False
        with self.state as state:
            if service:
                warn('%s: gravity does not create services, add them to config'
                        ' files and run `gravity update`', ic)
            elif instance not in state.instances:
                state.instances[instance] = Instance()
                info('Created instance: %s', instance)
                created_instance = True
            elif not config:
                warn('%s: already exists', instance)

            if config and not created_instance:
                if config_file in self.get_config_files(instance):
                    raise Exception('%s: file already registered' %
                        config_file)
                elif config in state.instances[instance].config_files:
                    raise Exception('%s: already exists' % ic)

            if config:
                conf = ConfigFile.load(config_file)
                info('Registered %s config: %s as %s', conf.config_type,
                    config_file, config)
                state.instances[instance].config_files[config] = conf

    def set(self, ics, option, value):
        with self.state as state:
            try:
                obj = self.get_ics_object(ics, state)
                if option not in ConfigManager.config_attributes \
                        + obj.private_options:
                    error('%s: invalid option', option)
                    return
                elif option in obj.private_options:
                    obj[option] = obj.validate(option, value)
                else:
                    obj.config[option] = ConfigManager.validate(option, value)
            except KeyError:
                error('%s: invalid path', ics)

    def unset(self, ics, option):
        with self.state as state:
            try:
                obj = self.get_ics_object(ics, state)
            except KeyError:
                error('%s: invalid path', ics)
                return
            try:
                obj.config.pop(option)
            except KeyError:
                # unsetting a valid option that is already unset is a
                # noop
                if option not in ConfigManager.config_attributes:
                    error('%s: invalid option', option)
                return

    def get(self, ics):
        #instance, config, service = self.__parse_ics(ics)
        if not ics:
            return self.get_instances()
        else:
            try:
                return {ics: self.get_ics_object(ics)}
            except KeyError:
                error('%s: invalid path', ics)
                return
        #instance_data = self.get_instance(instance)
        #if config:
        #    instance_data.config_files = instance_data.config_files[config]
        #if service:
        #    instance_data.config_files[config].services = instance_data.config_files[config].services[service]
        #return {instance : instance_data}

    def destroy(self, ic):
        instance, config, service = self.__parse_ics(ic)
        with self.state as state:
            if service:
                warn('%s: gravity does not destroy services, remove them from'
                    ' config files and run `gravity update`', ic)
            elif instance not in state.instances:
                raise Exception('%s: does not exist' % ic)
            elif config and config not in state.instances[instance].config_files:
                raise Exception('%s: does not exist' % config)
            elif config:
                state.instances[instance].config_files.pop(config)
                info('Destroyed %s', config)
            elif instance:
                state.instances.pop(instance)
                info('Destroyed %s', instance)

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
