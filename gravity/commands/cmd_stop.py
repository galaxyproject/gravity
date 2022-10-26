import click

from gravity import options
from gravity import process_manager


@click.command("stop")
@options.instances_services_arg()
@click.pass_context
def cli(ctx, instances_services):
    """Stop configured services.

    If no INSTANCES or SERVICES are provided, all configured services of all configured instances are stopped.

    Specifying INSTANCES and SERVICES limits the operation to only the provided instance name(s) and/or service(s).
    """
    with process_manager.process_manager(**ctx.parent.cm_kwargs) as pm:
        pm.stop(instance_names=instances_services)
