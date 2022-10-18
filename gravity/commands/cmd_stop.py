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
    cm_args = {"state_dir": ctx.parent.state_dir, "galaxy_config": ctx.parent.galaxy_config}
    with process_manager.process_manager(start_daemon=False, **cm_args) as pm:
        pm.stop(instance_names=instance)
