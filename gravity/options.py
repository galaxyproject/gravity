""" Click definitions for various shared options and arguments.
"""
import click


def debug_option():
    return click.option("-d", "--debug", is_flag=True, help="Enables debug mode.")


def state_dir_option():
    return click.option(
        "--state-dir", type=click.Path(file_okay=False, writable=True, resolve_path=True), help="Where process management configs and state will be stored."
    )


def config_file_option():
    return click.option(
        "-c",
        "--config-file",
        type=click.Path(exists=True, dir_okay=False, resolve_path=True),
        multiple=True,
        help="Gravity (or Galaxy) config file to operate on. Can also be set with $GRAVITY_CONFIG_FILE or $GALAXY_CONFIG_FILE",
    )


def no_log_option():
    return click.option(
        '--quiet', is_flag=True, default=False, help="Only output supervisor logs, do not include process logs"
    )


def required_config_arg(name="config", exists=False, nargs=None):
    arg_type = click.Path(
        exists=exists,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
    )
    if nargs is None:
        return click.argument(name, type=arg_type)
    else:
        return click.argument(name, nargs=nargs, type=arg_type)


def instances_services_arg():
    return click.argument("instances_services", metavar="[INSTANCES] [SERVICES]", nargs=-1)
