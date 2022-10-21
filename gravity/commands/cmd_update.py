import click

from gravity import process_manager


@click.command("update")
@click.option("--force", is_flag=True, help="Force rewriting of process config files")
@click.option("--clean", is_flag=True, help="Remove process config files if they exist")
@click.pass_context
def cli(ctx, force, clean):
    """Update process manager from config changes."""
    with process_manager.process_manager(**ctx.parent.cm_kwargs) as pm:
        pm.update(force=force, clean=clean)
