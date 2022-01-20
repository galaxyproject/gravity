import click

from gravity import config_manager


@click.command("instances")
@click.pass_context
def cli(ctx):
    """List all known instances."""
    with config_manager.config_manager(state_dir=ctx.parent.state_dir) as cm:
        configs = cm.get_registered_configs()
        instances = cm.get_registered_instances()
        if instances:
            click.echo("%-24s  %-10s  %-10s  %s" % ("INSTANCE NAME", "TYPE", "SERVER", "NAME"))
            # not the most efficient...
            for instance in instances:
                instance_str = instance
                for config in configs.values():
                    if config["instance_name"] == instance:
                        for service in config["services"]:
                            click.echo("%-24s  %-10s  %-10s  %s" % (instance_str, service.config_type, service.service_type, service.service_name))
                            instance_str = ""
                if instance_str == instance:
                    click.echo("%-24s  no services configured" % instance)
