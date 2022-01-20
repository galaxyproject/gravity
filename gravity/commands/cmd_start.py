import click

from gravity import options
from gravity import process_manager
from gravity.io import info


@click.command("start")
@options.required_instance_arg()
@click.option("-f", "--foreground", is_flag=True, default=False, help="Run in foreground")
@click.pass_context
def cli(ctx, foreground, instance):
    """Start configured services."""
    with process_manager.process_manager(state_dir=ctx.parent.state_dir, foreground=foreground) as pm:
        pm.start(instance)
        if foreground:
            pm.follow(instance)
        elif pm.config_manager.single_instance == 1:
            config = list(pm.config_manager.get_registered_configs().values())[0]
            info(f"Log files are in {config.attribs['log_dir']}")
        else:
            for config in pm.config_manager.get_registered_configs(instances=instance or None).values():
                info(f"Log files for {config.instance_name} are in {config.attribs['log_dir']}")
