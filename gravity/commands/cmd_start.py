import click

from gravity import options
from gravity import process_manager
from gravity.io import info


@click.command("start")
@options.instances_services_arg()
@click.option("-f", "--foreground", is_flag=True, default=False, help="Run in foreground")
@options.no_log_option()
@click.pass_context
def cli(ctx, instances_services, foreground, quiet=False):
    """Start configured services.

    If no INSTANCES or SERVICES are provided, all configured services of all configured instances are started.

    Specifying INSTANCES and SERVICES limits the operation to only the provided instance name(s) and/or service(s).
    """
    with process_manager.process_manager(foreground=foreground, **ctx.parent.cm_kwargs) as pm:
        pm.update()
        pm.start(instance_names=instances_services)
        if foreground:
            pm.follow(instance_names=instances_services, quiet=quiet)
        elif pm.config_manager.single_instance:
            config = pm.config_manager.get_config()
            if config.process_manager != "systemd":
                info(f"Log files are in {config.log_dir}")
        else:
            for config in pm.config_manager.get_configs(instances=instances_services or None):
                if config.process_manager != "systemd":
                    info(f"Log files for {config.instance_name} are in {config.log_dir}")
