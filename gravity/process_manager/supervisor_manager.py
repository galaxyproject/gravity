"""
"""
from __future__ import print_function

import os
import sys
import time
import errno
import shutil
import signal
import logging
import urllib2

from os.path import join, abspath, exists

from supervisor import supervisorctl, supervisord
from setproctitle import setproctitle

from . import BaseProcessManager
from ..config_manager import ConfigManager

log = logging.getLogger(__name__)


supervisord_conf_template = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[unix_http_server]
file = {supervisor_state_dir}/supervisor.sock

[supervisord]
logfile = {supervisor_state_dir}/supervisord.log
pidfile = {supervisor_state_dir}/supervisord.pid
loglevel = info
nodaemon = false

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl = unix://{supervisor_state_dir}/supervisor.sock

[include]
files = {supervisord_conf_dir}/*.d/*.conf {supervisord_conf_dir}/*.conf
"""

supervisord_galaxy_uwsgi_conf_template = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[program:{program_name}]
command         = {uwsgi_path} --ini-paste {galaxy_conf} --pidfile={supervisor_state_dir}/{program_name}.pid
directory       = {galaxy_root}
autostart       = false
autorestart     = true
startsecs       = 10
numprocs        = 1
stopsignal      = INT
stdout_logfile  = {log_dir}/{program_name}.log
redirect_stderr = true
environment     = PYTHON_EGG_CACHE="{virtualenv}/.python-eggs",PATH="{virtualenv}/bin:%(ENV_PATH)s"
"""

supervisord_galaxy_paste_conf_template = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[program:{program_name}]
command         = python ./scripts/paster.py serve {galaxy_conf} --server-name={server_name} --pid-file={supervisor_state_dir}/{program_name}.pid
process_name    = {config_type}_{server_name}
directory       = {galaxy_root}
autostart       = false
autorestart     = true
startsecs       = 20
numprocs        = 1
stdout_logfile  = {log_dir}/{program_name}.log
redirect_stderr = true
environment     = PYTHON_EGG_CACHE="{virtualenv}/.python-eggs",PATH="{virtualenv}/bin:%(ENV_PATH)s"
"""

supervisord_galaxy_standalone_conf_template = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[program:{program_name}]
command         = python ./lib/galaxy/main.py -c {galaxy_conf} --server-name={server_name} --pid-file={supervisor_state_dir}/{program_name}.pid
process_name    = {config_type}_{server_name}
directory       = {galaxy_root}
autostart       = false
autorestart     = true
startsecs       = 20
numprocs        = 1
stdout_logfile  = {log_dir}/{program_name}.log
redirect_stderr = true
environment     = PYTHON_EGG_CACHE="{virtualenv}/.python-eggs",PATH="{virtualenv}/bin:%(ENV_PATH)s"
"""

supervisord_galaxy_instance_group_conf_template = """;
; This file is maintained by Galaxy - CHANGES WILL BE OVERWRITTEN
;

[group:{instance_name}]
programs = {programs}
"""


class SupervisorProcessManager(BaseProcessManager):

    def __init__(self, state_dir=None, galaxy_root=None, start_supervisord=True, default_config_file=None):
        super(SupervisorProcessManager, self).__init__(state_dir=state_dir)
        self.default_config_file = default_config_file
        self.supervisor_state_dir = join(self.state_dir, 'supervisor')
        self.supervisord_conf_path = join(self.supervisor_state_dir, 'supervisord.conf')
        self.supervisord_conf_dir = join(self.supervisor_state_dir, 'supervisord.conf.d')

        if not exists(self.supervisord_conf_dir):
            os.makedirs(self.supervisord_conf_dir)

        if start_supervisord:
            self.__supervisord()

    def __supervisord(self):
        format_vars = { 'supervisor_state_dir' : self.supervisor_state_dir,
                        'supervisord_conf_dir' : self.supervisord_conf_dir }
        supervisord_pid_path = join(self.supervisor_state_dir, 'supervisord.pid')

        try:
            assert exists(supervisord_pid_path)
            os.kill(int(open(supervisord_pid_path).read()), 0)
        except:
            # any time that supervisord is not running, let's rewrite supervisord.conf
            open(self.supervisord_conf_path, 'w').write(supervisord_conf_template.format(**format_vars))
            # supervisord detaches, fork so we don't exit here
            pid = os.fork()
            if pid == 0:
                args = ['-c', self.supervisord_conf_path]
                # set sys.argv so if there's an error it doesn't output a
                # misleading message that appears to be coming from galaxyadm
                sys.argv = ['supervisord'] + args
                setproctitle('supervisord -c %s' % self.supervisord_conf_path)
                supervisord.main(args=args)
            else:
                pid, rc = os.waitpid(pid, 0)
                assert rc == 0, 'supervisord exited with code %d' % rc
                log.info('supervisord started as pid %d', pid)

    def _update_service(self, config_file, config, attribs, service, instance_conf_dir, instance_name):
        format_vars = {
            'log_dir' : attribs['log_dir'],
            'config_type' : service['config_type'],
            'server_name' : service['service_name'],
            'program_name' : '%s_%s_%s_%s' % (instance_name, service['config_type'], service['service_type'], service['service_name']),
            'virtualenv' : attribs['virtualenv'],
            'galaxy_conf' : config_file,
            'galaxy_root' : attribs['galaxy_root'],
            'supervisor_state_dir' : self.supervisor_state_dir,
        }
        conf = join(instance_conf_dir, '%s_%s_%s.conf' % (service['config_type'], service['service_type'], service['service_name']))

        if not exists(attribs['log_dir']):
            os.makedirs(attribs['log_dir'])

        if service['service_type'] == 'paste':
            template = supervisord_galaxy_paste_conf_template
        elif service['service_type'] == 'uwsgi':
            uwsgi_path = attribs['uwsgi_path']
            if uwsgi_path == 'install':
                self.config_manager.install_uwsgi(attribs['virtualenv'])
                uwsgi_path = 'uwsgi'
            elif uwsgi_path is None:
                uwsgi_path = 'uwsgi'
            format_vars['uwsgi_path'] = uwsgi_path
            # uwsgi does not live in the process group so that it is not fully restarted with the rest of the processes
            format_vars['program_name'] = '%s_%s_%s' % (instance_name, service['config_type'], service['service_name'])
            template = supervisord_galaxy_uwsgi_conf_template
        elif service['service_type'] == 'standalone':
            template = supervisord_galaxy_standalone_conf_template
        else:
            raise Exception('Unknown service type: %s' % service['service_type'])

        open(conf, 'w').write(template.format(**format_vars))

    def _process_config_changes(self, configs, meta_changes):
        # remove the services of any configs which have been removed
        for config_file, config in meta_changes['remove_configs'].items():
            instance_name = config.instance_name
            instance_conf_dir = join(self.supervisord_conf_dir, '%s.d' % instance_name)
            for service in config['services']:
                log.info('Removing service %s:%s_%s_%s', instance_name, service.config_type, service.service_type, service.service_name)
                conf = join(instance_conf_dir, '%s_%s_%s.conf' % (service.config_type, service.service_type, service.service_name))
                if exists(conf):
                    os.unlink(conf)

        # update things for existing or new configs
        for config_file, config in configs.items():
            instance_name = config['instance_name']
            attribs = config['attribs']
            update_all_configs = False

            # config attribs have changed (galaxy_root, virtualenv, etc.)
            if 'update_attribs' in config:
                log.info('Updating all dependent services of config %s due to changes' % config_file)
                attribs = config['update_attribs']
                update_all_configs = True

            # instance name has changed, so supervisor group config must change
            if 'update_instance_name' in config:
                instance_name = config['update_instance_name']
                log.info('Creating new instance for name change: %s -> %s', config['instance_name'], instance_name)
                update_all_configs = True

            # always attempt to make the config dir
            instance_conf_dir = join(self.supervisord_conf_dir, '%s.d' % instance_name)
            try:
                os.makedirs(instance_conf_dir)
            except (IOError, OSError) as exc:
                if exc.errno != errno.EEXIST:
                    raise

            if update_all_configs:
                for service in config['services']:
                    log.info('Updating service %s:%s_%s_%s', instance_name, service['config_type'], service['service_type'], service['service_name'])
                    self._update_service(config_file, config, attribs, service, instance_conf_dir, instance_name)

            # new services
            if 'update_services' in config:
                for service in config['update_services']:
                    log.info('Creating service %s:%s_%s_%s', instance_name, service['config_type'], service['service_type'], service['service_name'])
                    self._update_service(config_file, config, attribs, service, instance_conf_dir, instance_name)

            # deleted services
            if 'remove_services' in config:
                for service in config['remove_services']:
                    log.info('Removing service %s:%s_%s_%s', instance_name, service['config_type'], service['service_type'], service['service_name'])
                    conf = join(instance_conf_dir, '%s_%s_%s.conf' % (service['config_type'], service['service_type'], service['service_name']))
                    if exists(conf):
                        os.unlink(conf)

            # sanity check, make sure everything that should exist does exist
            for service in config['services']:
                conf = join(instance_conf_dir, '%s_%s_%s.conf' % (service['config_type'], service['service_type'], service['service_name']))
                if service not in config.get('remove_services', []) and not exists(conf):
                    self._update_service(config_file, config, attribs, service, instance_conf_dir, instance_name)
                    log.warning('Missing service config recreated: %s' % conf)

        # all configs referencing an instance name have been removed (or their
        # instance names have changed), nuke the group
        for instance_name in meta_changes['remove_instances']:
            log.info('Removing instance %s', instance_name)
            instance_conf_dir = join(self.supervisord_conf_dir, '%s.d' % instance_name)
            if exists(instance_conf_dir):
                shutil.rmtree(instance_conf_dir)
            conf = join(self.supervisord_conf_dir, 'group_%s.conf' % instance_name)
            if exists(conf):
                os.unlink(join(conf))

        # persist to the state file
        self.config_manager.register_config_changes(configs, meta_changes)

        # now we can create/update the instance group
        for instance_name in meta_changes['changed_instances']:
            programs = []
            for service in self.config_manager.get_registered_services():
                if service['instance_name'] == instance_name and service['service_type'] != 'uwsgi':
                    programs.append('%s_%s_%s_%s' % (instance_name, service['config_type'], service['service_type'], service['service_name']))
            conf = join(self.supervisord_conf_dir, 'group_%s.conf' % instance_name)
            if programs:
                format_vars = { 'instance_conf_dir' : instance_conf_dir,
                                'instance_name' : instance_name,
                                'programs' : ','.join(programs) }
                open(conf, 'w').write(supervisord_galaxy_instance_group_conf_template.format(**format_vars))
            else:
                # no programs for the group, so it should be removed
                if exists(conf):
                    os.unlink(conf)

    def get_instance_names(self, instance_names):
        registered_instance_names = self.config_manager.get_registered_instances()
        if instance_names:
            pass
        elif registered_instance_names:
            instance_names = registered_instance_names
        else:
            raise Exception('No instances registered (hint: `galaxycfg add /path/to/galaxy.ini`)')
        return instance_names

    def _start_stop(self, op, instance_names):
        self.update()
        for instance_name in self.get_instance_names(instance_names):
            self.supervisorctl(op, '%s:*' % instance_name)
            for service in self.config_manager.get_instance_services(instance_name):
                if service['service_type'] == 'uwsgi':
                    self.supervisorctl(op, '%s_%s_%s' % (instance_name, service['config_type'], service['service_name']))

    def start(self, instance_names):
        super(SupervisorProcessManager, self).start(instance_names)
        self._start_stop('start', instance_names)

    def stop(self, instance_names):
        self._start_stop('stop', instance_names)

    def restart(self, instance_names):
        self._start_stop('restart', instance_names)

    def _reload_graceful(self, op, instance_names):
        self.update()
        for instance_name in self.get_instance_names(instance_names):
            if op == 'restart':
                # restart everything but uwsgi
                self.supervisorctl('restart', '%s:*' % instance_name)
            for service in self.config_manager.get_instance_services(instance_name):
                service_name = '%s_%s_%s' % (instance_name, service.config_type, service.service_name)
                group_service_name = '%s:%s_%s' % (instance_name, service.config_type, service.service_name)
                procinfo = self.get_supervisor().getProcessInfo(group_service_name)
                if service['service_type'] == 'uwsgi':
                    # restart uwsgi
                    try:
                        os.kill(procinfo['pid'], signal.SIGHUP)
                        print('%s: sent HUP signal' % group_service_name)
                    except Exception as exc:
                        log.warning('Attempt to reload %s failed: %s', service_name, exc)
                # graceful restarts
                elif op == 'graceful' and service['service_type'] == 'standalone':
                    self.supervisorctl('restart', group_service_name)
                elif op == 'graceful' and service['service_type'] == 'paste':
                    self.supervisorctl('restart', group_service_name)
                    url = 'http://localhost:%d/' % service.paste_port
                    print('%s: waiting until %s is accepting requests' % (service_name, url), end='')
                    while True:
                        try:
                            r = urllib2.urlopen(url, None, 5)
                            assert r.getcode() == 200, '%s returned HTTP code: %s' % (url, r.getcode())
                            print(' OK')
                            break
                        except AssertionError as exc:
                            print()
                            log.error(exc)
                            return
                        except Exception as exc:
                            print('.', end='')
                            sys.stdout.flush()
                            time.sleep(1)

    def reload(self, instance_names):
        self._reload_graceful('reload', instance_names)

    def graceful(self, instance_names):
        self._reload_graceful('graceful', instance_names)

    def status(self):
        # TODO: create our own formatted output
        #supervisor = self.get_supervisor()
        #all_infos = supervisor.getAllProcessInfo()
        self.supervisorctl('status')

    def shutdown(self):
        self.supervisorctl('shutdown')

    def update(self):
        """ Add newly defined servers, remove any that are no longer present
        """
        configs, meta_changes = self.config_manager.determine_config_changes()
        self._process_config_changes(configs, meta_changes)
        self.supervisorctl('update')

    def get_supervisor(self):
        """ Return the supervisor proxy object

        Should probably use this more rather than supervisorctl directly
        """
        options = supervisorctl.ClientOptions()
        options.realize(args=['-c', self.supervisord_conf_path])
        return supervisorctl.Controller(options).get_supervisor()

    def supervisorctl(self, *args, **kwargs):
        supervisorctl.main(args=['-c', self.supervisord_conf_path] + list(args))
