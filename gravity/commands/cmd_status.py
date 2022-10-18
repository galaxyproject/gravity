import click

from gravity import process_manager


@click.command("status")
@click.pass_context
def cli(ctx):
    """Display server status."""
    cm_args = {"state_dir": ctx.parent.state_dir, "galaxy_config": ctx.parent.galaxy_config}
    with process_manager.process_manager(start_daemon=False, **cm_args) as pm:
        pm.status()
