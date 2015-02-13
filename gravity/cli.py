""" Command line utilities for managing Galaxy servers
"""
from __future__ import print_function

import os
import sys
import json
import logging
import subprocess

from argparse import ArgumentParser
from abc import ABCMeta, abstractmethod

from .config_manager import ConfigManager
from .process_manager.supervisor_manager import SupervisorProcessManager

log = logging.getLogger(__name__)

DEFAULT_STATE_DIR = '~/.galaxy'


class BaseGalaxyCLI(object):
    """ Control Galaxy server(s)
    """
    __metaclass__ = ABCMeta

    def __init__(self):
        self.arg_parser = None
        self.args = None

    def _configure_logging(self):
        if self.args.debug:
            level = logging.DEBUG
        else:
            level = logging.INFO
            # Don't log full exceptions without -d
            log.exception = log.error
        logging.basicConfig(format='%(levelname)-8s: %(message)s', level=level)

    @property
    def state_dir(self):
        if self.args.state_dir is not None:
            state_dir = self.args.state_dir
        elif 'GALAXYADM_STATE_DIR' in os.environ:
            state_dir = os.environ['GALAXYADM_STATE_DIR']
        else:
            state_dir = DEFAULT_STATE_DIR
        return os.path.abspath(os.path.expanduser(state_dir))

    @abstractmethod
    def parse_arguments(self):
        self.arg_parser = ArgumentParser(description=self.description)
        self.arg_parser.add_argument("-d", "--debug", default=False, action='store_true', help="Show debugging messages")
        self.arg_parser.add_argument("--state-dir", default=None, help="Where process management configs and state will be stored (default: $GALAXYADM_STATE_DIR or ~/.galaxy)")

    @abstractmethod
    def main(self):
        self.parse_arguments()
        self._configure_logging()


class GalaxyConfig(BaseGalaxyCLI):
    """ Manage Galaxy server configurations
    """
    description = __doc__.strip()

    def __init__(self):
        super(GalaxyConfig, self).__init__()
        self.__config_manager = None

    def parse_arguments(self):
        super(GalaxyConfig, self).parse_arguments()
        python = subprocess.check_output(['python', '-c', 'import sys; print sys.executable'])
        self.arg_parser.add_argument("-p", "--python-exe", default=None, help="The Python interpreter to use to create the virtualenv (default: %s)" % python.strip())
        sub_arg_parsers = self.arg_parser.add_subparsers(dest='subcommand', help='SUBCOMMANDS')
        arg_parser_add = sub_arg_parsers.add_parser('add', help='Register config file(s)')
        arg_parser_add.add_argument("config", nargs='+', help='Config files to register')
        arg_parser_list = sub_arg_parsers.add_parser('list', help='List registered config files')
        arg_parser_get = sub_arg_parsers.add_parser('get', help='Get registered config file details')
        arg_parser_get.add_argument("config", help='Config file')
        arg_parser_instances = sub_arg_parsers.add_parser('instances', help='List known instances and services')
        arg_parser_rename = sub_arg_parsers.add_parser('rename', help='Rename config file')
        arg_parser_rename.add_argument("rename_config_old", help='Old config file path')
        arg_parser_rename.add_argument("rename_config_new", help='New config file path')
        arg_parser_remove = sub_arg_parsers.add_parser('remove', help='Deregister config file(s)')
        arg_parser_remove.add_argument("config", nargs='+', help='Config files or instance names to deregister')
        self.args = self.arg_parser.parse_args()

    @property
    def config_manager(self):
        if self.__config_manager is None:
            self.__config_manager = ConfigManager(self.state_dir, python_exe=self.args.python_exe)
        return self.__config_manager

    def main(self):
        super(GalaxyConfig, self).main()

        # Handle the specified operation
        if self.args.subcommand == 'add':
            try:
                self.config_manager.add(self.args.config)
            except Exception as exc:
                log.exception("Adding config failed: %s", exc)
                sys.exit(1)
        elif self.args.subcommand == 'list':
            registered = self.config_manager.get_registered_configs()
            if registered:
                print('%-12s  %-24s  %s' % ('TYPE', 'INSTANCE NAME', 'CONFIG PATH'))
                for config in sorted(registered.keys()):
                    print('%-12s  %-24s  %s' % (registered[config].get('config_type', 'unknown'), registered[config].get('instance_name', 'unknown'), config))
            else:
                print('No config files registered')
        elif self.args.subcommand == 'instances':
            configs = self.config_manager.get_registered_configs()
            instances = self.config_manager.get_registered_instances()
            if instances:
                print('%-24s  %-10s  %-10s  %s' % ('INSTANCE NAME', 'TYPE', 'SERVER', 'NAME'))
                # not the most efficient...
                for instance in instances:
                    instance_str = instance
                    for config in configs.values():
                        if config['instance_name'] == instance:
                            for service in config['services']:
                                print('%-24s  %-10s  %-10s  %s' % (instance_str, service.config_type, service.service_type, service.service_name))
                                instance_str = ''
                    if instance_str == instance:
                        print('%-24s  no services configured' % instance)
            else:
                print('No known instances')
        elif self.args.subcommand == 'get':
            config =  self.config_manager.get_registered_config(os.path.abspath(os.path.expanduser(self.args.config)))
            if config is None:
                print('%s not found' % self.args.config)
            else:
                print(json.dumps(config, sort_keys=True, indent=4, separators=(',', ': ')))
        elif self.args.subcommand == 'rename':
            try:
                self.config_manager.rename(self.args.rename_config_old, self.args.rename_config_new)
            except Exception as exc:
                log.exception("Renaming config failed: %s", exc)
                sys.exit(1)
        elif self.args.subcommand == 'remove':
            try:
                self.config_manager.remove(self.args.config)
            except Exception as exc:
                log.exception("Remove config failed: %s", exc)
                sys.exit(1)


class GalaxyAdmin(BaseGalaxyCLI):
    """ Manage Galaxy services
    """
    description = __doc__.strip()

    def __init__(self):
        super(GalaxyAdmin, self).__init__()
        self.__process_manager = None

    def parse_arguments(self):
        super(GalaxyAdmin, self).parse_arguments()

        # Add parsers for subcommands
        sub_arg_parsers = self.arg_parser.add_subparsers(dest='subcommand', help='SUBCOMMANDS')
        arg_parser_status = sub_arg_parsers.add_parser('status', help='Display server status')
        arg_parser_start = sub_arg_parsers.add_parser('start', help='Start configured services')
        arg_parser_start.add_argument("instance", nargs='*', help='Instance(s) to start')
        arg_parser_stop = sub_arg_parsers.add_parser('stop', help='Stop configured services')
        arg_parser_stop.add_argument("instance", nargs='*', help='Instance(s) to stop')
        arg_parser_restart = sub_arg_parsers.add_parser('restart', help='Restart configured services')
        arg_parser_restart.add_argument("instance", nargs='*', help='Instance(s) to restart')
        arg_parser_reload = sub_arg_parsers.add_parser('reload', help='Reload configured services')
        arg_parser_reload.add_argument("instance", nargs='*', help='Instance(s) to reload')
        arg_parser_graceful = sub_arg_parsers.add_parser('graceful', help='Gracefully reload configured services')
        arg_parser_graceful.add_argument("instance", nargs='*', help='Instance(s) to gracefully reload')
        arg_parser_shutdown = sub_arg_parsers.add_parser('shutdown', help='Stop all services and supervisord')
        arg_parser_update = sub_arg_parsers.add_parser('update', help='Update process manager from config changes')
        arg_parser_supervisorctl = sub_arg_parsers.add_parser('supervisorctl', help='Invoke supervisorctl directly')
        arg_parser_supervisorctl.add_argument("supervisorctl_args", nargs='*', help='supervisorctl subcommand (optional)')
        self.args = self.arg_parser.parse_args()

    @property
    def start_supervisord(self):
        return self.args.subcommand not in ('shutdown', 'status')

    @property
    def process_manager(self):
        if self.__process_manager is None:
            self.__process_manager = SupervisorProcessManager(start_supervisord=self.start_supervisord)
        return self.__process_manager

    def main(self):
        super(GalaxyAdmin, self).main()

        try:
            if self.args.subcommand == 'supervisorctl':
                self.process_manager.supervisorctl(*self.args.supervisorctl_args)
            elif self.args.subcommand == 'update':
                # TODO: update could a -f (force) option to wipe and rewrite all
                # supervisor configs. warn that this could affect other instances
                self.process_manager.update()
            elif self.args.subcommand in ('status', 'shutdown'):
                getattr(self.process_manager, self.args.subcommand)()
            elif self.args.subcommand in ('start', 'stop', 'restart', 'reload', 'graceful'):
                getattr(self.process_manager, self.args.subcommand)(self.args.instance)
        except Exception as exc:
            log.exception('%s failed: %s', self.args.subcommand, exc)


def galaxycfg():
    g = GalaxyConfig()
    g.main()

def galaxyadm():
    g = GalaxyAdmin()
    g.main()
