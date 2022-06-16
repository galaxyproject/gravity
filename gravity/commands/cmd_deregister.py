import click

from gravity import config_manager
from gravity import options


@click.command("deregister")
@options.required_config_arg(nargs=-1)
@click.pass_context
def cli(ctx, config):
    """Deregister config file(s).

    aliases: remove, forget
    """
    with config_manager.config_manager(state_dir=ctx.parent.state_dir) as cm:
        cm.remove(config)
