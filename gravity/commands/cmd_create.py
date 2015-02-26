import os

import click

from gravity import options
from gravity import config_manager
from gravity.io import error


@click.command('create')
@options.required_instance_arg()
@click.pass_context
def cli(ctx, instance):
    """ Create an instance.
    """
    with config_manager.config_manager() as cm:
        try:
            cm.create(instance)
        except Exception as exc:
            error('Caught exception: %s', exc)
            ctx.exit(1)
