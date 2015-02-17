import os
import json

import click

from gravity import options
from gravity import config_manager

@click.command('show')
@options.required_config_arg()
@click.pass_context
def cli(ctx, config):
    """ Show details of registered config.

    aliases: get
    """
    with config_manager.config_manager() as cm:
        config_data = cm.get_registered_config(config)
        if config is None:
            click.echo('%s not found' % config)
        else:
            click.echo(json.dumps(config_data, sort_keys=True, indent=4, separators=(',', ': ')))
