import click

from gravity import config_manager


@click.command("list")
@click.option("--version", "-v", is_flag=True, default=False, help="Include Galaxy version in output")
@click.pass_context
def cli(ctx, version):
    """List configured instances.

    aliases: configs
    """
    cols = ["{:<18}", "{}"]
    head = ["INSTANCE NAME", "CONFIG PATH"]
    if version:
        cols.insert(1, "{:<12}")
        head.insert(1, "VERSION")
    cols_str = "  ".join(cols)
    with config_manager.config_manager(**ctx.parent.cm_kwargs) as cm:
        configs = cm.get_configs()
        if configs:
            click.echo(cols_str.format(*head))
            for config in configs:
                row = [
                    config.instance_name,
                    config.gravity_config_file,
                ]
                if version:
                    row.insert(1, config.galaxy_version)
                click.echo(cols_str.format(*row))
        else:
            click.echo("No configured instances")
