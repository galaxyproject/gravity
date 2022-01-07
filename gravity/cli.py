""" Command line utilities for managing Galaxy servers
"""

import os
import sys

import click

from gravity import io
from gravity import options


# FIXME: $GRAVITY_STATE_DIR unimplemented
# FIXME: -p/--python-exe unimplemented
# CONTEXT_SETTINGS = dict(auto_envvar_prefix='GRAVITY')
CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])
# FIXME: incomplete aliases
COMMAND_ALIASES = {
    "list": "configs",
    "add": "register",
    "remove": "deregister",
    "forget": "deregister",
}


cmd_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "commands"))


def set_debug(debug_opt):
    if debug_opt:
        io.DEBUG = True


def list_cmds():
    rv = []
    for filename in os.listdir(cmd_folder):
        if filename.endswith(".py") and filename.startswith("cmd_"):
            rv.append(filename[len("cmd_"): -len(".py")])
    rv.sort()
    return rv


def name_to_command(name):
    try:
        if sys.version_info[0] == 2:
            name = name.encode("ascii", "replace")
        mod_name = "gravity.commands.cmd_" + name
        mod = __import__(mod_name, None, None, ["cli"])
    except ImportError as e:
        io.error("Problem loading command %s, exception %s" % (name, e))
        return
    return mod.cli


class GravityCLI(click.MultiCommand):
    def list_commands(self, ctx):
        return list_cmds()

    def get_command(self, ctx, name):
        if name in COMMAND_ALIASES:
            name = COMMAND_ALIASES[name]
        return name_to_command(name)


@click.command(cls=GravityCLI, context_settings=CONTEXT_SETTINGS)
@options.debug_option()
@options.state_dir_option()
def galaxy(debug, state_dir):
    """Manage Galaxy server configurations and processes."""
    set_debug(debug)
