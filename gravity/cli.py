""" Command line utilities for managing Galaxy servers
"""

import os

import click

from gravity import io
from gravity import options
from gravity.settings import ProcessManager


CONTEXT_SETTINGS = {
    "auto_envvar_prefix": "GRAVITY",
    "help_option_names": ["-h", "--help"]
}

COMMAND_ALIASES = {
    "configs": "list",
    "get": "show",
    "reload": "graceful",
    "supervisorctl": "pm",
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
        mod_name = "gravity.commands.cmd_" + name
        mod = __import__(mod_name, None, None, ["cli"])
    except ImportError as e:
        io.error(f"Problem loading command {name}, exception {e}")
        return
    return mod.cli


class GravityCLI(click.Group):
    def list_commands(self, ctx):
        return list_cmds()

    def get_command(self, ctx, name):
        if name in COMMAND_ALIASES:
            name = COMMAND_ALIASES[name]
        return name_to_command(name)


# Shortcut for running Galaxy in the foreground
@click.command(context_settings=CONTEXT_SETTINGS)
@click.version_option()
@options.debug_option()
@options.config_file_option()
@options.state_dir_option()
@options.no_log_option()
@options.single_user_option()
@click.pass_context
def galaxy(ctx, debug, config_file, state_dir, quiet, single_user):
    """Run Galaxy server in the foreground"""
    set_debug(debug)
    ctx.cm_kwargs = {
        "config_file": config_file,
        "state_dir": state_dir,
        "process_manager": ProcessManager.multiprocessing.value,
    }
    if single_user:
        os.environ["GALAXY_CONFIG_SINGLE_USER"] = single_user
        os.environ["GALAXY_CONFIG_ADMIN_USERS"] = single_user
    mod = __import__("gravity.commands.cmd_start", None, None, ["cli"])
    return ctx.invoke(mod.cli, foreground=True, quiet=quiet)


@click.command(cls=GravityCLI, context_settings=CONTEXT_SETTINGS)
@click.version_option()
@options.debug_option()
@options.config_file_option()
@options.state_dir_option()
@options.user_mode_option()
@click.pass_context
def galaxyctl(ctx, debug, config_file, state_dir, user):
    """Manage Galaxy server configurations and processes."""
    set_debug(debug)
    ctx.cm_kwargs = {
        "config_file": config_file,
        "state_dir": state_dir,
        "user_mode": user,
    }
