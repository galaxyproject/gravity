Subcommands
===========

Use ``galaxyctl --help`` for help. Subcommands also support ``--help``, e.g. ``galaxy register --help``

start
-----

Start and run Galaxy and associated processes in daemonized (background) mode, or ``-f`` to run in the foreground and
follow log files. The ``galaxy`` command is a shortcut for ``galaxyctl start -f``.

stop
----

Stop daemonized Galaxy server processes. If using supervisor mode and no processes remain running after this step (which
should be the case when working with a single Galaxy instance), ``supervisord`` will terminate.

restart
-------

Restart Galaxy server processes. This is done in a relatively "brutal" fashion: processes are signaled (by the process
manager) to exit, and then are restarted. See the ``graceful`` subcommand to restart gracefully.

graceful
--------

Restart Galaxy with minimal interruption.

If running with a single `gunicorn`_ without ``preload``, this means holding the web socket open while restarting
(connections to Galaxy will block). With ``preload``, gunicorn is restarted and some clients may experience connection
failures.

If running with multiple gunicorns, a rolling restart is performed, where Gravity restarts each gunicorn, waits for it
to respond to requests after restarting, and then moves to the next one. This process should be transparent to clients.
See :ref:`Zero-Downtime Restarts` for configuration details.

update
------

Figure out what has changed in the Galaxy/Gravity config(s), which could be:

-  changes to the Gravity configuration options in ``galaxy.yml``
-  adding or removing handlers in ``job_conf.yml`` or ``job_conf.xml``

This may cause service restarts if there are any changes.

Any needed changes to supervisor or systemd configs will be performed and then ``supervisorctl update`` or ``systemctl
daemon-reload`` will be called.

If you wish to *remove* any existing process manager configurations for Galaxy servers managed by Gravity, the
``--clean`` flag to ``update`` can be used for this purpose.

shutdown
--------

Stop all processes and cause ``supervisord`` to terminate. Similar to ``stop`` but there is no ambiguity as to whether
``supervisord`` remains running. The equivalent of ``stop`` when using systemd.

follow
------

Follow (e.g. using ``tail -f`` (supervisor) or ``journalctl -f`` (systemd)) log files of all Galaxy services, or a
subset (if named as arguments).

list
----

List config files known to Gravity.

show
----

Show Gravity configuration details for a Galaxy instance.

pm
--

Pass through directly to the process manager (e.g. supervisor). Run ``galaxyctl pm`` to invoke the supervisorctl shell,
or ``galaxyctl pm [command]`` to call a supervisorctl or systemctl command directly. See the `supervisor`_ documentation
or ``galaxyctl pm help`` for help.

exec
----

Directly execute a single Galaxy service in the foreground, e.g. ``galaxyctl exec gunicorn``, ``galaxyctl exec tusd``,
etc.

When Gravity writes out configs for the underlying process manager, it must provide a *command* (program and arguments)
to execute and some number of *environment variables* that must be set for each individual Galaxy service (gunicorn,
celery, etc.) to execute. By default, rather than write this information directly to the process manager configuration,
Gravity sets the command to ``galaxyctl exec --config-file=<gravity-config-path> <service-name>``. The ``exec``
subcommand instructs Gravity to use the `exec(3)`_ system call to execute the actual service command with its proper
arguments and environment.

This is done so that it is is not necesary to rewrite the process manager configs and update the process manager every
time a parameter is changed, only when services are added or removed entirely. Gravity can instead be instructed to
write the actual service command and environment variables directly to the process manager configurations by setting
``service_command_style`` to ``direct``.

Thus, although ``exec`` is mostly an internal subcommand, developers and admins may find it useful when debugging in
order to quickly and easily start just a single service and view only that service's logs in the foreground.

.. _gunicorn: https://gunicorn.org/
.. _supervisor: http://supervisord.org/
.. _exec(3): https://pubs.opengroup.org/onlinepubs/9699919799/functions/exec.html
