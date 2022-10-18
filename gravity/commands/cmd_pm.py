import click

from gravity import process_manager


@click.command("pm")
@click.argument("pm_arg", nargs=-1)
@click.pass_context
def cli(ctx, pm_arg):
    """Invoke process manager (supervisorctl, systemctl) directly."""
    with process_manager.process_manager(**ctx.parent.cm_kwargs) as pm:
        pm.pm(*pm_arg)
