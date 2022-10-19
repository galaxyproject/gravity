import click

from gravity import config_manager


@click.command("configs")
@click.option("--version", "-v", is_flag=True, default=False, help="Include Galaxy version in output")
@click.pass_context
def cli(ctx, version):
    """List registered config files.

    aliases: list
    """
    cols = ["{:<8}", "{:<18}", "{}"]
    head = ["TYPE", "INSTANCE NAME", "CONFIG PATH"]
    if version:
        cols.insert(2, "{:<12}")
        head.insert(2, "VERSION")
    cols_str = "  ".join(cols)
    with config_manager.config_manager(**ctx.parent.cm_kwargs) as cm:
        registered = cm.get_registered_configs()
        if registered:
            click.echo(cols_str.format(*head))
            for config in registered:
                row = [
                    config.get("config_type", "unknown"),
                    config.get("instance_name", "unknown"),
                    config.__file__,
                ]
                if version:
                    row.insert(2, config.galaxy_version)
                click.echo(cols_str.format(*row))
        else:
            click.echo("No config files registered")
