import click

from gravity import process_manager


@click.command("pm")
@click.argument("pm_args", nargs=-1)
@click.pass_context
def cli(ctx, pm_args):
    """Invoke process manager (supervisorctl, systemctl) directly.

    Any args in PM_ARGS are passed to the process manager command.
    """
    with process_manager.process_manager(**ctx.parent.cm_kwargs) as pm:
        pm.pm(*pm_args)
