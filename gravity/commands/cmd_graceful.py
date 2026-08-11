import click

from gravity import options
from gravity import process_manager


@click.command("graceful")
@options.instances_services_arg()
@click.option(
    "--start-if-stopped",
    is_flag=True,
    default=False,
    help="If a service is not currently running, start it instead of refusing to perform a graceful restart.",
)
@click.pass_context
def cli(ctx, instances_services, start_if_stopped):
    """Gracefully reload configured services.

    If no INSTANCES or SERVICES are provided, all configured services of all configured instances are gracefully
    reloaded.

    Specifying INSTANCES and SERVICES limits the operation to only the provided instance name(s) and/or service(s).

    By default, a rolling restart refuses to proceed if a service instance's pre-restart health check fails, since
    there's nothing to roll from. With --start-if-stopped, a health check failure is only treated as "not running"
    (and started instead of causing the command to fail) once confirmed against the process manager itself
    (e.g. systemd unit state, supervisor program state). A running-but-unhealthy instance still causes the command
    to fail, as does an instance that is restarted but never becomes ready.
    """
    with process_manager.process_manager(**ctx.parent.cm_kwargs) as pm:
        pm.graceful(instance_names=instances_services, start_if_stopped=start_if_stopped)
