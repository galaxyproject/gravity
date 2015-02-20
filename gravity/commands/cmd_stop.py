import os

import click

from gravity import options
from gravity import process_manager

@click.command('stop')
@options.required_instance_arg()
@click.pass_context
def cli(ctx, instance):
    """ Stop configured services.
    """
    with process_manager.process_manager() as pm:
        pm.stop(instance)
