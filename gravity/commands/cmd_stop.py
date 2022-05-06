import click

from gravity import options
from gravity import process_manager


@click.command("stop")
@options.required_instance_arg()
@click.pass_context
def cli(ctx, instance):
    """Stop configured services.

    If INSTANCE matches an instance name, all services configured for the instance are stopped.

    If INSTANCE does not match an instance name, it is assumed to be a service and only the listed service(s) are
    stopped."""
    with process_manager.process_manager(state_dir=ctx.parent.state_dir, start_daemon=False) as pm:
        pm.stop(instance)
