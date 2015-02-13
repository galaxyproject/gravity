""" Galaxy Process Management superclass and utilities
"""

import os
import errno
import logging

from ..config_manager import ConfigManager

log = logging.getLogger(__name__)


class BaseProcessManager(object):
    state_dir = '~/.galaxy'

    def __init__(self, state_dir=None, galaxy_root=None):
        if state_dir is None:
            state_dir = BaseProcessManager.state_dir
        self.state_dir = os.path.abspath(os.path.expanduser(state_dir))
        try:
            os.makedirs(self.state_dir)
        except (IOError, OSError) as exc:
            if exc.errno != errno.EEXIST:
                raise
        self.config_manager = ConfigManager(state_dir=state_dir, galaxy_root=galaxy_root)

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

    # FIXME: define some base class methods here
