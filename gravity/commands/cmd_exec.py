import click

from gravity import options
from gravity import process_manager


@click.command("exec")
@options.instances_services_arg()
@click.pass_context
def cli(ctx, instances_services):
    """Run a single Galaxy service in the foreground, with logging output to stdout/stderr.

    Zero or one instance names can be provided in INSTANCES, it is required if more than one Galaxy instance is
    configured in Gravity.

    Exactly one service name is required in SERVICES.
    """
    with process_manager.process_manager(state_dir=ctx.parent.state_dir, start_daemon=False) as pm:
        pm.exec(instance_names=instances_services)
