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

    # FIXME: define some base class methods here
