import os

import click

from gravity import options
from gravity import config_manager
from gravity.io import error


@click.command('create')
@options.instance_config_arg('ic')
@options.config_arg(exists=True, required=False)
@click.pass_context
def cli(ctx, ic, config):
    """ Create an instance/config.

    The "config" argument is required if creating a config.
    """
    if '/' in ic and not config:
        click.echo(ctx.get_usage() + '\n', err=True)
        click.echo('Error: Missing argument "config".', err=True)
        ctx.exit(2)
    with config_manager.config_manager() as cm:
        try:
            cm.create(ic, config)
        except Exception as exc:
            error('Caught exception: %s', exc)
            ctx.exit(1)
