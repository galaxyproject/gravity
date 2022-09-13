import click

from gravity import config_manager


@click.command("configs")
@click.pass_context
def cli(ctx):
    """List registered config files.

    aliases: list
    """
    with config_manager.config_manager(state_dir=ctx.parent.state_dir) as cm:
        registered = cm.get_registered_configs()
        if registered:
            click.echo("%-12s  %-24s  %s" % ("TYPE", "INSTANCE NAME", "CONFIG PATH"))
            for config in registered:
                click.echo("%-12s  %-24s  %s" % (config.get("config_type", "unknown"), config.get("instance_name", "unknown"), config.__file__))
        else:
            click.echo("No config files registered")
