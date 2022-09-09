import click

from gravity import process_manager


@click.command("update")
@click.option("--force", is_flag=True, help="Force rewriting of process config files")
@click.pass_context
def cli(ctx, force):
    """Update process manager from config changes."""
    with process_manager.process_manager(state_dir=ctx.parent.state_dir, start_daemon=False) as pm:
        pm.update(force=force)
