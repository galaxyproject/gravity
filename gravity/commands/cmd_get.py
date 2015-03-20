import os

import click

from gravity import options
from gravity import config_manager
from gravity.io import error
from gravity.state import Instance, ConfigFile, Service


@click.command('get')
@options.instance_config_service_arg('on', required=False)
@click.argument('option', required=False)
@click.pass_context
def cli(ctx, on, option):
    """ Get config options.
    """
    with config_manager.config_manager() as cm:
        if option is None and on is not None:
            try:
                cm.get_ics_object(on)
            except KeyError:
                option = on
                on = None
        try:
            obj = cm.get(on)
        except Exception as exc:
            error('Caught exception: %s', exc)
            ctx.exit(1)
        if obj:
            opts = None
            if option is not None:
                opts = [option]
            icsw, optw, valw, srcw, props = walk(obj, len('NAME'),
                                                 len('OPTION'), len('VALUE'),
                                                 len('SOURCE'), opts)
            line = '%-{icsw}s  %-{optw}s  %-{valw}s  %{srcw}s'
            click.echo(line.format(icsw=icsw, optw=optw, valw=valw, srcw=srcw)
                       % ('NAME', 'OPTION', 'VALUE', 'SOURCE'))
            for prop in props:
                click.echo(line.format(icsw=icsw, optw=optw,
                           valw=valw, srcw=srcw) % prop)
        else:
            click.echo('No instances configured')


def walk(obj, icsw, optw, valw, srcw, opts, path=None):
    rval = []
    if opts is None:
        opts = config_manager.ConfigManager.config_attributes
    for name, data in obj.items():
        if path is None:
            ics = name
        else:
            ics = path + '/' + name
        icsw = max(len(ics), icsw)
        for optg, get in (
                (opts, data.config.get_source),
                (data.private_options, lambda o, d: (data.get(o, d),
                    'private'))):
            for opt in optg:
                if opt not in config_manager.ConfigManager.config_attributes \
                        + data.private_options:
                    continue
                val, src = get(opt, None)
                if opt in data.private_options and src != 'private':
                    continue
                optw = max(len(opt), optw)
                valw = max(len(str(val)), valw)
                srcw = max(len(src), srcw)
                rval.append((ics, opt, val, src))
        if isinstance(data, Instance):
            icsw, optw, valw, srcw, props = walk(data.config_files, icsw, optw,
                                                 valw, srcw, opts, ics)
            rval.extend(props)
        elif isinstance(data, ConfigFile):
            icsw, optw, valw, srcw, props = walk(data.services, icsw, optw,
                                                 valw, srcw, opts, ics)
            rval.extend(props)
    return icsw, optw, valw, srcw, rval
