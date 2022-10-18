import click

from gravity import config_manager
from gravity import options
from gravity.io import warn


@click.command("deregister")
@options.required_config_arg(nargs=-1)
@click.pass_context
def cli(ctx, config):
    """Deregister config file(s).

    aliases: remove, forget
    """
    if ctx.parent.cm_kwargs["config_file"]:
        warn("The 'deregister' subcommand is meaningless when --config-file is set")
        return
    with config_manager.config_manager(**ctx.parent.cm_kwargs) as cm:
        cm.remove(config)
