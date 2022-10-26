import click

from gravity import config_manager, options
from gravity import process_manager
from gravity.io import info, exception


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
    auto_update = False
    if not instances_services and not ctx.parent.cm_kwargs["config_file"]:
        # FIXME: this doesn't do anything anymore now that the cm goes out of scope. you just init the cm twice
        with config_manager.config_manager(**ctx.parent.cm_kwargs) as cm:
            # If there are no configs known, we will attempt to auto-load one
            cm.auto_load()
            auto_update = True
        if not cm.instance_count:
            exception(
                "Nothing to start: no Galaxy instances configured and no Galaxy configuration files found, "
                "see `galaxyctl --help`")
    with process_manager.process_manager(foreground=foreground, **ctx.parent.cm_kwargs) as pm:
        if auto_update:
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
