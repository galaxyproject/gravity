import os

import click

from gravity import options
from gravity import config_manager
from gravity.io import error


@click.command('get')
@options.instance_config_service_arg('on', required=False)
@click.argument('option', required=False)
@click.pass_context
def cli(ctx, on, option):
    """ Get config options.
    """
    with config_manager.config_manager() as cm:
        try:
            instance, config, service = options.instance_config_service_arg_parse(ctx, on, required=False)
            instances = cm.get(instance, config, service, option)
        except Exception as exc:
            error('Caught exception: %s', exc)
            ctx.exit(1)
        if instances:
            i, c, s, o, v, sr, props = walk_instances(instances)
            #click.echo('%-32s  %-24s  
            line = '%-{i}s  %-{c}s  %-{s}s  %-{o}s  %-{v}s  %{sr}s'
            click.echo(line.format(i=i, c=c, s=s, o=o, v=v, sr=sr) % ('INSTANCE', 'CONFIG FILE', 'SERVICE', 'OPTION', 'VALUE', 'SOURCE'))
            for prop in props:
                click.echo(line.format(i=i, c=c, s=s, o=o, v=v, sr=sr) % prop)
            #click.echo('%-12s  %-24s  %s' % ('TYPE', 'INSTANCE NAME', 'CONFIG PATH'))
            #click.echo(opts)
        else:
            click.echo('No instances configured')

def walk_instances(instances):
    i, c, s, o, v, sr = len('INSTANCE'), len('CONFIG FILE'), len('SERVICE'), len('OPTION'), len('VALUE'), len('SOURCE')
    rval = []
    # FIXME: recurse
    for instance_name in sorted(instances.keys()):
        i = max(len(instance_name), i)
        instance_data = instances[instance_name]
        for opt in config_manager.ConfigManager.config_attributes:
            val, source = instance_data.config.get_source(opt, None)
            v = max(len(str(val)), v)
            o = max(len(opt), o)
            sr = max(len(source), sr)
            rval.append((instance_name, '', '', opt, val, source))
        config_files = instances[instance_name].config_files
        for config_name in sorted(config_files.keys()):
            c = max(len(config_name), i)
            config_data = config_files[config_name]
            for opt in config_manager.ConfigManager.config_attributes:
                val, source = config_data.config.get_source(opt, None)
                v = max(len(str(val)), v)
                sr = max(len(source), sr)
                rval.append((instance_name, config_name, '', opt, val, source))
            services = config_files[config_name].services
            for service_name in sorted(config_data.services.keys()):
                s = max(len(service_name), i)
                service_data = services[service_name]
                for opt in config_manager.ConfigManager.config_attributes:
                    val, source = service_data.config.get_source(opt, None)
                    v = max(len(str(val)), v)
                    sr = max(len(source), sr)
                    rval.append((instance_name, config_name, service_name, opt, val, source))
    return i, c, s, o, v, sr, rval
