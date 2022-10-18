import click

from gravity import config_manager
from gravity import options
from gravity.io import warn


@click.command("register")
@options.required_config_arg(exists=True, nargs=-1)
@click.pass_context
def cli(ctx, config):
    """Register config file(s).

    aliases: add
    """
    if ctx.parent.cm_kwargs["config_file"]:
        warn("The 'register' subcommand is meaningless when --config-file is set")
        return
    with config_manager.config_manager(**ctx.parent.cm_kwargs) as cm:
        cm.add(config)
