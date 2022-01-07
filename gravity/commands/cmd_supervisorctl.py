import click

from gravity import process_manager


@click.command("supervisorctl")
@click.argument("supervisorctl_arg", nargs=-1)
@click.pass_context
def cli(ctx, supervisorctl_arg):
    """Invoke supervisorctl directly."""
    with process_manager.process_manager() as pm:
        pm.supervisorctl(*supervisorctl_arg)
