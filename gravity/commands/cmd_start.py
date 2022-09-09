import click

from gravity import config_manager, options
from gravity import process_manager
from gravity.io import info, exception


@click.command("start")
@options.required_instance_arg()
@click.option("-f", "--foreground", is_flag=True, default=False, help="Run in foreground")
@options.no_log_option()
@click.pass_context
def cli(ctx, foreground, instance, quiet=False):
    """Start configured services.

    If INSTANCE matches an instance name, all services configured for the instance are started.

    If INSTANCE does not match an instance name, it is assumed to be a service and only the listed service(s) are
    started."""
    if not instance:
        with config_manager.config_manager(state_dir=ctx.parent.state_dir) as cm:
            # If there are no configs registered, we will attempt to auto-register one
            cm.auto_register()
        if not cm.instance_count:
            exception(
                "Nothing to start: no Galaxy instances configured and no Galaxy configuration files found, "
                "see `galaxyctl register --help`")
    with process_manager.process_manager(state_dir=ctx.parent.state_dir, foreground=foreground) as pm:
        pm.start(instance_names=instance)
        if foreground:
            pm.follow(instance_names=instance, quiet=quiet)
        elif pm.config_manager.single_instance:
            config = list(pm.config_manager.get_registered_configs())[0]
            info(f"Log files are in {config.attribs['log_dir']}")
        else:
            for config in pm.config_manager.get_registered_configs(instances=instance or None):
                info(f"Log files for {config.instance_name} are in {config.attribs['log_dir']}")
