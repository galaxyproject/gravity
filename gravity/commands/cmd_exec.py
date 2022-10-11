import click

from gravity import options
from gravity import process_manager
from gravity.io import exception


@click.command("exec")
@options.instances_services_arg()
@click.pass_context
def cli(ctx, instances_services):
    """Run a single Galaxy service, with logging output to stdout/stderr.

    Zero or one instance names can be provided in INSTANCES, it is required if more than one Galaxy instance is
    configured in Gravity.

    Exactly one service name is required in SERVICES.
    """
    with process_manager.process_manager(state_dir=ctx.parent.state_dir) as pm:
        """
        instance_names, service_names = pm._instance_service_names(instances_services)
        if len(instance_names) == 0 and pm.config_manager.single_instance:
            instance_name = None
        elif len(instance_names) != 1:
            exception("Only zero or one instance name can be provided")
        else:
            instance_name = instance_names[0]
        if len(service_names) != 1:
            exception("Exactly one service_name must be provided")
        """
        pm.exec(instance_names=instances_services)
