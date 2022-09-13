import sys

import click

from gravity import config_manager
from gravity import options
from gravity.io import exception


@click.command("show")
@options.required_config_arg(exists=True)
@click.pass_context
def cli(ctx, config):
    """Show details of registered config.

    aliases: get
    """
    with config_manager.config_manager(state_dir=ctx.parent.state_dir) as cm:
        config_data = cm.get_registered_config(config)
        if config_data is None:
            newline = "\n"
            error_message = f"{config} is not a registered config file.{newline}"
            registered_configs = cm.get_registered_configs()
            if registered_configs:
                registered_configs_str = "\n".join([c.__file__ for c in registered_configs])
                error_message = f'{error_message}Registered config files are:{newline}{registered_configs_str}{newline}{newline}'
            else:
                error_message = f'{error_message}No config files have been registered.{newline}{newline}'
            error_message = f'{error_message}To register this config file run "galaxyctl register {config}".'
            exception(error_message)
        else:
            config_data.dump(sys.stdout)
