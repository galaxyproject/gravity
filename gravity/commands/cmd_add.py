import os

import click

from gravity import options
from gravity import config_manager
from gravity.io import error


@click.command('add')
@options.required_instance_arg()
@options.required_config_arg(exists=True, nargs=-1)
@click.pass_context
def cli(ctx, instance, config):
    """ Register config file(s).

    aliases: add
    """
    with config_manager.config_manager() as cm:
        try:
            cm.add(instance, config)
        except Exception as exc:
            error('Caught exception: %s', exc)
            ctx.exit(1)
