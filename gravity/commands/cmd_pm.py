import click

from gravity import process_manager


NO_START_COMMANDS = (
    "shutdown",
    "status",
)


@click.command("pm")
@click.argument("pm_arg", nargs=-1)
@click.pass_context
def cli(ctx, pm_arg):
    """Invoke process manager (supervisorctl, systemctl) directly."""
    start_daemon = bool(pm_arg and pm_arg[0] not in NO_START_COMMANDS)
    with process_manager.process_manager(state_dir=ctx.parent.state_dir, start_daemon=start_daemon) as pm:
        pm.pm(*pm_arg)
