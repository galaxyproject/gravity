import json

import click

from gravity import config_manager


@click.command("show")
@click.argument("instance", required=False)
@click.pass_context
def cli(ctx, instance):
    """Show details of instance config.

    INSTANCE is optional unless there is more than one Galaxy instance configured.

    aliases: get
    """
    with config_manager.config_manager(**ctx.parent.cm_kwargs) as cm:
        config_data = cm.get_config(instance_name=instance)
        click.echo(json.dumps(config_data.dict(), indent=4))
