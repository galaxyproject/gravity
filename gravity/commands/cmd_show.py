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
            error_message = f"{config} is not a registered config file."
            exception(error_message)
        else:
            config_data.dump(sys.stdout)
