import click

from gravity import options
from gravity import process_manager


@click.command("start")
@options.required_instance_arg()
@click.option("-f", "--foreground", is_flag=True, default=False, help="Run in foreground")
@click.pass_context
def cli(ctx, foreground, instance):
    """Start configured services."""
    with process_manager.process_manager(state_dir=ctx.parent.state_dir) as pm:
        pm.start(instance)
        if foreground:
            pm.follow(instance)
