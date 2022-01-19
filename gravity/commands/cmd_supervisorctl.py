import click

from gravity import process_manager


NO_START_COMMANDS = (
    "shutdown",
    "status",
)


@click.command("supervisorctl")
@click.argument("supervisorctl_arg", nargs=-1)
@click.pass_context
def cli(ctx, supervisorctl_arg):
    """Invoke supervisorctl directly."""
    start_daemon = (supervisorctl_arg and supervisorctl_arg[0] not in NO_START_COMMANDS)
    with process_manager.process_manager(state_dir=ctx.parent.state_dir, start_daemon=start_daemon) as pm:
        pm.supervisorctl(*supervisorctl_arg)
