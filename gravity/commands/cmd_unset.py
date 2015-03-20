import os

import click

from gravity import options
from gravity import config_manager
from gravity.io import error


@click.command('set')
@options.instance_config_service_arg('on')
@click.argument('option')
@click.pass_context
def cli(ctx, on, option):
    """ Unset config options.
    """
    with config_manager.config_manager() as cm:
        try:
            cm.unset(on, option)
        except Exception as exc:
            error('Caught exception: %s', exc)
            ctx.exit(1)
