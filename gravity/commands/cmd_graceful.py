import click

from gravity import options
from gravity import process_manager


@click.command("graceful")
@options.required_instance_arg()
@click.pass_context
def cli(ctx, instance):
    """Gracefully reload configured services.

    If INSTANCE matches an instance name, all services configured for the instance are restarted.

    If INSTANCE does not match an instance name, it is assumed to be a service and only the listed service(s) are
    restarted."""
    with process_manager.process_manager(**ctx.parent.cm_kwargs) as pm:
        pm.graceful(instance_names=instance)
