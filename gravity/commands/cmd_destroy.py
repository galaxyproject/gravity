import os

import click

from gravity import options
from gravity import config_manager
from gravity.io import error


@click.command('destroy')
@options.instance_config_arg('ic')
@click.pass_context
def cli(ctx, ic):
    """ Destroy an instance/config.
    """
    with config_manager.config_manager() as cm:
        try:
            cm.destroy(ic)
        except Exception as exc:
            error('Caught exception: %s', exc)
            ctx.exit(1)
