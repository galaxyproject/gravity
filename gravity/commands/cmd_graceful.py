import click

from gravity import options
from gravity import process_manager


@click.command("graceful")
@options.required_instance_arg()
@click.pass_context
def cli(ctx, instance):
    """Gracefully reload configured services."""
    with process_manager.process_manager(state_dir=ctx.parent.state_dir) as pm:
        pm.graceful(instance)
