import os

import click

from gravity import options
from gravity import config_manager
from gravity.io import error


@click.command('set')
@options.instance_config_service_arg('on')
@click.argument('option')
@click.argument('value')
@click.pass_context
def cli(ctx, on, option, value):
    """ Set config options.
    """
    with config_manager.config_manager() as cm:
        try:
            cm.set(on, option, value)
        except Exception as exc:
            error('Caught exception: %s', exc)
            ctx.exit(1)
