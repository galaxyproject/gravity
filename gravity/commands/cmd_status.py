import click

from gravity import process_manager


@click.command("status")
@click.pass_context
def cli(ctx):
    """Display server status."""
    with process_manager.process_manager(**ctx.parent.cm_kwargs) as pm:
        pm.status()
