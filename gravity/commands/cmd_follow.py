import click

from gravity import options
from gravity import process_manager


@click.command("follow")
@options.required_instance_arg()
@click.pass_context
def cli(ctx, instance):
    """Follow log files of configured instances."""
    with process_manager.process_manager(state_dir=ctx.parent.state_dir, start_daemon=False) as pm:
        pm.follow(instance)
