import click

from gravity import options
from gravity import process_manager


@click.command("follow")
@options.required_instance_arg()
@click.pass_context
def cli(ctx, instance):
    """Follow log files of configured instances.

    If INSTANCE matches an instance name, logs of all services configured for the instance are followed.

    If INSTANCE does not match an instance name, it is assumed to be a service and only logs of the listed service(s)
    are followed."""
    with process_manager.process_manager(state_dir=ctx.parent.state_dir, start_daemon=False) as pm:
        pm.follow(instance_names=instance)
