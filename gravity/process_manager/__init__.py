""" Galaxy Process Management superclass and utilities
"""

import os
import errno
import importlib

from abc import ABCMeta, abstractmethod

from gravity.config_manager import ConfigManager


# If at some point we have additional process managers we can make a factory,
# but for the moment there's only supervisor.

import contextlib
@contextlib.contextmanager
def process_manager(state_dir=None, start_daemon=True):
    modlist = []
    # roulette!
    for filename in os.listdir(os.path.dirname(__file__)):
        if filename.endswith('.py') and \
           not filename.startswith('_'):
            mod = importlib.import_module('gravity.process_manager.' + filename[:-len(".py")])
            for name in dir(mod):
                obj = getattr(mod, name)
                if not name.startswith('_') and \
                   isinstance(obj, object) and \
                   issubclass(obj, BaseProcessManager) and \
                   obj != BaseProcessManager:
                    yield obj(state_dir=state_dir, start_daemon=start_daemon)
                    return


class BaseProcessManager(object, metaclass=ABCMeta):
    state_dir = '~/.galaxy'

    def __init__(self, state_dir=None, start_daemon=True):
        if state_dir is None:
            state_dir = BaseProcessManager.state_dir
        self.state_dir = os.path.abspath(os.path.expanduser(state_dir))
        try:
            os.makedirs(self.state_dir)
        except (IOError, OSError) as exc:
            if exc.errno != errno.EEXIST:
                raise
        self.config_manager = ConfigManager(state_dir=state_dir)

    @abstractmethod
    def start(self, instance_names):
        """ If start is called from the root of a Galaxy source directory with
        no args, automatically add this instance.
        """
        if not instance_names:
            configs = (os.path.join('config', 'galaxy.ini'),
                    os.path.join('config', 'galaxy.ini.sample'))
            for config in configs:
                if os.path.exists(config):
                    if not self.config_manager.is_registered(os.path.abspath(config)):
                        self.config_manager.add([config])
                    break

    @abstractmethod
    def _process_config_changes(self, configs, meta_changes):
        """
        """

    @abstractmethod
    def stop(self, instance_names):
        """
        """

    @abstractmethod
    def restart(self, instance_names):
        """
        """

    @abstractmethod
    def reload(self, instance_names):
        """
        """

    @abstractmethod
    def graceful(self, instance_names):
        """
        """

    @abstractmethod
    def update(self, instance_names):
        """
        """

    @abstractmethod
    def shutdown(self, instance_names):
        """
        """

    def get_instance_names(self, instance_names):
        registered_instance_names = self.config_manager.get_registered_instances()
        unknown_instance_names = []
        if instance_names:
            for i, n in enumerate(instance_names):
                if n not in registered_instance_names:
                    unknown_instance_names.append(instance_names.pop(i))
        elif registered_instance_names:
            instance_names = registered_instance_names
        else:
            raise Exception('No instances registered (hint: `galaxy add /path/to/galaxy.ini`)')
        return instance_names, unknown_instance_names
