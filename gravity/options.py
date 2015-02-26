""" Click definitions for various shared options and arguments.
"""
import click


def debug_option():
    return click.option(
        '-d', '--debug',
        is_flag=True,
        help='Enables debug mode.'
    )


def state_dir_option():
    return click.option(
        '--state-dir',
        type=click.Path(file_okay=False, writable=True, resolve_path=True),
        help='Where process management configs and state will be stored.'
    )


def required_config_arg(name='config', exists=False, nargs=None):
    arg_type = click.Path(
        exists = exists,
        file_okay = True,
        dir_okay = False,
        readable = True,
        resolve_path = True,
    )
    if nargs is None:
        return click.argument(name, type=arg_type)
    else:
        return click.argument(name, nargs=nargs, type=arg_type)


def required_instance_arg(nargs=None):
    if nargs is None:
        return click.argument('instance')
    else:
        return click.argument('instance', nargs=-1)

def instance_config_service_arg(name='on', required=True):
    metavar = 'INSTANCE [CONFIG [SERVICE]]'
    if not required:
        metavar = '[INSTANCE [CONFIG [SERVICE]]]'
    return click.argument(
        name,
        metavar=metavar,
        nargs=-1
    )

def instance_config_service_arg_parse(ctx, on, required=True):
    """ Click can't really handle this type of arg, but we'll pretend that it can.
    """
    if (len(on) < 1 and required) or len(on) > 3:
        click.echo(ctx.get_usage() + '\n', err=True)
        if len(on) < 1:
            click.echo('Error: Missing argument "instance".', err=True)
        else:
            click.echo('Error: Got unexpected extra arguments (%s)' % ' '.join(on[3:]), err=True)
        ctx.exit(2)
    return (list(on) + [None, None, None])[:3]
