import click

from gravity import options
from gravity import process_manager


@click.command("graceful")
@options.instances_services_arg()
@click.pass_context
def cli(ctx, instance_services):
    """Gracefully reload configured services.

    If no INSTANCES or SERVICES are provided, all configured services of all configured instances are gracefully
    reloaded.

    Specifying INSTANCES and SERVICES limits the operation to only the provided instance name(s) and/or service(s).
    """
    with process_manager.process_manager(**ctx.parent.cm_kwargs) as pm:
        pm.graceful(instance_names=instance_services)
