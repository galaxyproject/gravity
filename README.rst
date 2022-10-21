============================================
 gravity - Galaxy Server Process Management
============================================

Process management for `Galaxy`_ servers.

Modern Galaxy servers run multiple disparate processes: `gunicorn`_ for serving the web application, `celery`_ for
asynchronous tasks, `tusd`_ for fault-tolerant uploads, standalone Galaxy processes for job handling, and more. Gravity
is Galaxy's process manager, to make configuring and running these services simple.

Installing Gravity will give you two executables, ``galaxyctl`` which is used to manage the starting, stopping, and
logging of Galaxy's various processes, and ``galaxy``, which can be used to run a Galaxy server in the foreground.

Installation
============

Python 3.7 or later is required. Gravity can be installed independently of Galaxy, but it is also a dependency of
Galaxy since Galaxy 22.01. If you've installed Galaxy, then Gravity is already installed in Galaxy's virtualenv.

To install independently:

.. code:: console

    $ pip install gravity

To make your life easier, you are encourged to install into a `virtualenv`_. The easiest way to do this is with Python's
built-in `venv`_ module:

.. code:: console

    $ python3 -m venv ~/gravity
    $ . ~/gravity/bin/activate

Usage
=====

Gravity needs to know where your Galaxy configuration file is, and depending on your Galaxy layout, some additional
details like the paths to its virtualenv and root directory. Gravity's configuration is defined in Galaxy's
configuration file (``galaxy.yml``) to be easy and familiar for Galaxy administrators.

Examples in this documentation assume a Galaxy layout like the one used in the `Galaxy Installation with Ansible`_
tutorial::

    /srv/galaxy/server  # Galaxy code
    /srv/galaxy/config  # config files
    /srv/galaxy/venv    # virtualenv

Gravity can either run Galaxy via the `supervisor`_ process manager (the default) or `systemd`_.

Managing a Single Galaxy
------------------------

The simplest way to use Gravity is to activate Galaxy's virtualenv, which will put Gravity's ``galaxyctl`` and
``galaxy`` commands on your ``$PATH``:

.. code:: console

    $ . /srv/galaxy/venv/bin/activate
    $ galaxyctl --help
    Usage: galaxyctl [OPTIONS] COMMAND [ARGS]...

      Manage Galaxy server configurations and processes.

    Options:
      -d, --debug             Enables debug mode.
      -c, --config-file FILE  Gravity (or Galaxy) config file to operate on. Can
                              also be set with $GRAVITY_CONFIG_FILE or
                              $GALAXY_CONFIG_FILE
      --state-dir DIRECTORY   Where process management configs and state will be
                              stored.
      -h, --help              Show this message and exit.

    Commands:
      configs     List registered config files.
      deregister  Deregister config file(s).
      exec        Run a single Galaxy service in the foreground, with logging...
      follow      Follow log files of configured instances.
      graceful    Gracefully reload configured services.
      instances   List all known instances.
      pm          Invoke process manager (supervisorctl, systemctl) directly.
      register    Register config file(s).
      rename      Update path of registered config file.
      restart     Restart configured services.
      show        Show details of registered config.
      shutdown    Shut down process manager.
      start       Start configured services.
      status      Display server status.
      stop        Stop configured services.
      update      Update process manager from config changes.

If you run ``galaxy`` or ``galaxyctl`` from the root of a Galaxy source checkout and do not specify the config file
option, ``config/galaxy.yml`` or ``config/galaxy.yml.sample`` will be automatically used. This is handy for working with
local clones of Galaxy for testing or development. You can skip Galaxy's lengthy and repetitive ``run.sh`` configuration
steps when starting and stopping Galaxy in between code updates (you should still run ``run.sh`` after performing a
``git pull`` to make sure your dependencies are up to date).

For production servers, **it is recommended that you run Gravity as root in systemd mode**. See the :ref:`Managing a
Production Galaxy` section below for details.

To avoid having to run from the galaxy root directory, you can explicitly point Gravity at your Galaxy configuration
file with the ``--config-file`` option or ``$GRAVITY_CONFIG_FILE`` (or ``$GALAXY_CONFIG_FILE``, as set by Galaxy's
``run.sh`` script) environment variable. Then it's possible to run the ``galaxyctl`` command from anywhere.

.. code:: console

    $ galaxyctl --config-file /srv/galaxy/config/galaxy.yml SUBCOMMAND [OPTIONS]

Often times it's more convenient to put the environment variable in the Galaxy user's shell environment file, e.g.:

.. code:: console

    $ echo "export GRAVITY_CONFIG_FILE='/srv/galaxy/config/galaxy.yml'" >> ~/.bash_profile

Once you have configured the path to your config file, you can start and run Galaxy in the foreground using the
``galaxy`` command:

.. code:: console

    $ galaxy
    Registered galaxy config: /srv/galaxy/config/galaxy.yml
    Creating or updating service gunicorn
    Creating or updating service celery
    Creating or updating service celery-beat
    celery: added process group
    2022-01-20 14:44:24,619 INFO spawned: 'celery' with pid 291651
    celery-beat: added process group
    2022-01-20 14:44:24,620 INFO spawned: 'celery-beat' with pid 291652
    gunicorn: added process group
    2022-01-20 14:44:24,622 INFO spawned: 'gunicorn' with pid 291653
    celery                           STARTING
    celery-beat                      STARTING
    gunicorn                         STARTING
    ==> /srv/galaxy/var/gravity/log/gunicorn.log <==
    ...log output follows...

Galaxy will continue to run and output logs to stdout until terminated with ``CTRL+C``.

The ``galaxy`` command is actually a shortcut for two separate steps: 1. read the provided ``galaxy.yml`` and write out
the corresponding process manager configurations, and 2. start and run Galaxy in the foreground using the process
manager (`supervisor`_). You can perform these steps separately (and in this example, start Galaxy as a backgrounded
daemon instead of in the foreground):

.. code:: console

    $ galaxyctl update
    Registered galaxy config: /home/nate/work/galaxy/config/galaxy.yml
    Creating or updating service gunicorn
    Creating or updating service celery
    Creating or updating service celery-beat
    $ galaxyctl start
    celery                           STARTING
    celery-beat                      STARTING
    gunicorn                         STARTING
    Log files are in /home/nate/work/galaxy/database/gravity/log

When running as a daemon, the ``stop`` subcommand stops your Galaxy server:

.. code:: console

    $ galaxyctl stop
    celery-beat: stopped
    gunicorn: stopped
    celery: stopped
    All processes stopped, supervisord will exit
    Shut down

Managing a Production Galaxy
----------------------------

By default, Gravity runs Galaxy processes under `supervisor`_, but setting the ``process_manager`` option to ``systemd``
in Gravity's configuration will cause it to run under `systemd`_ instead. systemd is the default init system under most
modern Linux distributions, and using systemd is strongly encouraged for production Galaxy deployments.

Gravity manages `systemd service unit files`_ corresponding to all of the Galaxy services that it is aware of, much like
how it manages supervisor program config files in supervisor mode. If you run ``galaxyctl update`` as a non-root user,
the unit files will be installed in ``~/.config/systemd/user`` and run via `systemd user mode`_. This can be useful for
testing and development, but in production it is recommended to run Gravity as root, so that it installs the service
units in ``/etc/systemd/system`` and are managed by the privileged systemd instance. Even when Gravity is run as root,
Galaxy itself still runs as a non-root user, specified by the ``galaxy_user`` option in the Gravity configuration.

It is also recommended, when running as root, that you install Gravity independent of Galaxy, rather than use the copy
installed in Galaxy's virtualenv:

.. code:: console

    # python3 -m venv /opt/gravity
    # /opt/gravity/bin/pip install gravity

.. caution::

    Because systemd unit file names have semantic meaning (the filename is the service's name) and systemd does not have
    a facility for isolating unit files controlled by an application, Gravity considers all unit files in the unit dir
    (``/etc/systemd/system``) that are named like ``galaxy-*`` to be controlled by Gravity. **If you have existing unit
    files that are named as such, Gravity will overwrite or remove them.**

In systemd mode, and especially when run as root, some Gravity options are required:

.. code:: yaml

    gravity:
      process_manager: systemd

      # required if running as root
      galaxy_user: GALAXY-USERNAME
      # optional, defaults to primary group of the user set above
      galaxy_group: GALAXY-GROUPNAME

      # required
      virtualenv: /srv/galaxy/venv
      # probably necessary if your galaxy.yml is not in galaxy_root/config
      galaxy_root: /srv/galaxy/server

See the :ref:`Configuration` section for more details on these options and others.

When running Gravity as root, the following configuration files will automatically be searched for and read, unless
``--config-file`` is specified or ``$GRAVITY_CONFIG_FILE`` is set:

- ``/etc/galaxy/gravity.yml``
- ``/etc/galaxy/galaxy.yml``
- ``/etc/galaxy/gravity.d/*.y(a?)ml``

It is *not* necessary to write your entire Galaxy configuration to the Gravity config file. You can write only the
Gravity configuration, and then point to your Galaxy config file with the ``galaxy_config_file`` option in the Gravity
config. See the :ref:`Managing Multiple Galaxies` section for more details.

The ``log_dir`` option is ignored when using systemd. Logs are instead captured by systemd's logging facility,
``journald``.

You can use ``galaxyctl`` to manage Galaxy process starts/stops/restarts/etc. and follow the logs, just as you do under
supervisor, but you can also use ``systemctl`` and ``journalctl`` directly to manage process states and inspect logs
(respectively). Only ``galaxyctl update`` is necessary, in order to write and/or remove the appropriate systemd service
units based on your configuration. For example:

.. code:: console

   # export GRAVITY_CONFIG_FILE=/srv/galaxy/config/galaxy.yml
   # . /srv/galaxy/venv/bin/activate
   (venv) # galaxyctl update
   Adding service galaxy-gunicorn.service
   Adding service galaxy-celery.service
   Adding service galaxy-celery-beat.service

After this point, operations can be performed with either ``galaxyctl`` or ``systemctl``. Some examples of equivalent
commands:

=================================== ==================================================================
 Gravity                             systemd
=================================== ==================================================================
``galaxy``                          ``systemctl start galaxy.target && journalctl -f -u 'galaxy-*'``
``galaxyctl start``                 ``systemctl start galaxy.target``
``galaxyctl start SERVICE ...``     ``systemctl start galaxy-SERVICE.service galaxy-...``
``galaxyctl restart``               ``systemctl restart galaxy.target``
``galaxyctl restart SERVICE ...``   ``systemctl restart galaxy-SERVICE.service galaxy-...``
``galaxyctl graceful``              ``systemctl reload-or-restart galaxy.target``
``galaxyctl graceful SERVICE ...``  ``systemctl reload-or-restart galaxy-SERVICE.service galaxy-...``
``galaxyctl stop``                  ``systemctl start galaxy.target``
``galayxctl follow``                ``journalctl -f -u 'galaxy-*'``
=================================== ==================================================================

Managing Multiple Galaxies
--------------------------

Gravity can manage multiple instances of Galaxy simultaneously. This is useful especially in the case where you have
multiple production Galaxy instances on a single server and are managing them with Gravity installed outside of a Galaxy
virtualenv, as root. There are multiple ways to achieve this:

1. Pass multiple ``--config-file`` options to ``galaxyctl``, or set a list of colon-separated config paths in
   ``$GRAVITY_CONFIG_FILE``:

    .. code:: console

        $ galaxyctl --config-file /srv/galaxy/test/config/galaxy.yml \
                    --config-file /srv/galaxy/main/config/galaxy.yml list --version
        TYPE      INSTANCE NAME       VERSION       CONFIG PATH
        galaxy    test                22.05         /srv/galaxy/test/config/galaxy.yml
        galaxy    main                22.09.dev0    /srv/galaxy/main/config/galaxy.yml
        $ export GRAVITY_CONFIG_FILE='/srv/galaxy/test/config/galaxy.yml:/srv/galaxy/main/config/galaxy.yml'
        $ galaxyctl list --version
        TYPE      INSTANCE NAME       VERSION       CONFIG PATH
        galaxy    test                22.05         /srv/galaxy/test/config/galaxy.yml
        galaxy    main                22.09.dev0    /srv/galaxy/main/config/galaxy.yml

2. If running as root, any config files located in ``/etc/galaxy/gravity.d`` will automatically be loaded.

3. Specify multiple Gravity configurations in a single config file, as a list. In this case, the Galaxy and Gravity
   configurations must be in separate files as described in :ref:`Splitting Gravity and Galaxy Configurations`:

    .. code:: yaml

        gravity:
          - instance_name: test
            process_manager: systemd
            galaxy_config_file: /srv/galaxy/test/config/galaxy.yml
            galaxy_root: /srv/galaxy/test/server
            virtualenv: /srv/galaxy/test/venv
            galaxy_user: gxtest
            gunicorn:
              bind: unix:/srv/galaxy/test/var/gunicorn.sock
            handlers:
              handler:
                pools:
                  - job-handlers
                  - workflow-schedulers

          - instance_name: main
            process_manager: systemd
            galaxy_config_file: /srv/galaxy/main/config/galaxy.yml
            galaxy_root: /srv/galaxy/main/server
            virtualenv: /srv/galaxy/main/venv
            galaxy_user: gxmain
            gunicorn:
              bind: unix:/srv/galaxy/main/var/gunicorn.sock
              workers: 8
            handlers:
              handler:
                processes: 4
                pools:
                  - job-handlers
                  - workflow-schedulers

In all cases, when using multiple Gravity instances, each Galaxy instance managed by Gravity must have a unique
**instance name**. When working with a single instance, the default name ``_default_`` is used automatically and mostly
hidden from you. When working with multiple instances, set the ``instance_name`` option in each instance's Gravity
config to a unique name.

Although it is strongly encouraged to use systemd for running multiple instances, it is possible to use supervisor. If
using supervisor, the supervisor configurations will be stored in ``$XDG_CONFIG_HOME/galaxy-gravity``
(``$XDG_CONFIG_HOME`` defaults to ``~/.config/galaxy-gravity``), so you may want to set this to a different path using
the ``--state-dir`` option (or ``$GRAVITY_STATE_DIR``).

Note, Galaxy 22.01 and 22.05 automatically set ``$GRAVITY_STATE_DIR`` to ``<galaxy_root>/database/gravity`` in the
virtualenv's activation script.

Configuration
=============

The following options in the ``gravity`` section of ``galaxy.yml`` can be used to control Gravity:

.. code:: yaml

  # Configuration for Gravity process manager.
  # ``uwsgi:`` section will be ignored if Galaxy is started via Gravity commands (e.g ``./run.sh``, ``galaxy`` or ``galaxyctl``).
  gravity:

    # Process manager to use.
    # ``supervisor`` is the default process manager.
    # ``systemd`` is also supported.
    # Valid options are: supervisor, systemd
    # process_manager: supervisor

    # What command to write to the process manager configs
    # `gravity` (`galaxyctl exec <service-name>`) is the default
    # `direct` (each service's actual command) is also supported.
    # Valid options are: gravity, direct
    # service_command_style: gravity

    # Memory limit (in GB), processes exceeding the limit will be killed. Default is no limit. If set, this is default value
    # for all services. Setting ``memory_limit`` on an individual service overrides this value. Ignored if ``process_manager``
    # is ``supervisor``.
    # memory_limit:

    # Specify Galaxy config file (galaxy.yml), if the Gravity config is separate from the Galaxy config. Assumed to be the
    # same file as the Gravity config if a ``galaxy`` key exists at the root level, otherwise, this option is required.
    # galaxy_config_file:

    # Specify Galaxy's root directory.
    # Gravity will attempt to find the root directory, but you can set the directory explicitly with this option.
    # galaxy_root:

    # User to run Galaxy as, required when using the systemd process manager as root.
    # Ignored if ``process_manager`` is ``supervisor`` or user-mode (non-root) ``systemd``.
    # galaxy_user:

    # Group to run Galaxy as, optional when using the systemd process manager as root.
    # Ignored if ``process_manager`` is ``supervisor`` or user-mode (non-root) ``systemd``.
    # galaxy_group:

    # Set to a directory that should contain log files for the processes controlled by Gravity.
    # If not specified defaults to ``<galaxy_data_dir>/gravity/log``.
    # log_dir:

    # Set to Galaxy's virtualenv directory.
    # If not specified, Gravity assumes all processes are on PATH. This option is required in most circumstances when using
    # the ``systemd`` process manager.
    # virtualenv:

    # Select the application server.
    # ``gunicorn`` is the default application server.
    # ``unicornherder`` is a production-oriented manager for (G)unicorn servers that automates zero-downtime Galaxy server restarts,
    # similar to uWSGI Zerg Mode used in the past.
    # Valid options are: gunicorn, unicornherder
    # app_server: gunicorn

    # Override the default instance name.
    # this is hidden from you when running a single instance.
    # instance_name: _default_

    # Configuration for Gunicorn.
    gunicorn:

      # Enable Galaxy gunicorn server.
      # enable: true

      # The socket to bind. A string of the form: ``HOST``, ``HOST:PORT``, ``unix:PATH``, ``fd://FD``. An IP is a valid HOST.
      # bind: localhost:8080

      # Controls the number of Galaxy application processes Gunicorn will spawn.
      # Increased web performance can be attained by increasing this value.
      # If Gunicorn is the only application on the server, a good starting value is the number of CPUs * 2 + 1.
      # 4-12 workers should be able to handle hundreds if not thousands of requests per second.
      # workers: 1

      # Gunicorn workers silent for more than this many seconds are killed and restarted.
      # Value is a positive number or 0. Setting it to 0 has the effect of infinite timeouts by disabling timeouts for all workers entirely.
      # If you disable the ``preload`` option workers need to have finished booting within the timeout.
      # timeout: 300

      # Extra arguments to pass to Gunicorn command line.
      # extra_args:

      # Use Gunicorn's --preload option to fork workers after loading the Galaxy Application.
      # Consumes less memory when multiple processes are configured. Default is ``false`` if using unicornherder, else ``true``.
      # preload:

      # Value of supervisor startsecs, systemd TimeoutStartSec
      # start_timeout: 15

      # Value of supervisor stopwaitsecs, systemd TimeoutStopSec
      # stop_timeout: 65

      # Memory limit (in GB). If the service exceeds the limit, it will be killed. Default is no limit or the value of the
      # ``memory_limit`` setting at the top level of the Gravity configuration, if set. Ignored if ``process_manager`` is
      # ``supervisor``.
      # memory_limit:

      # Extra environment variables and their values to set when running the service. A dictionary where keys are the variable
      # names.
      # environment: {}

    # Configuration for Celery Processes.
    celery:

      # Enable Celery distributed task queue.
      # enable: true

      # Enable Celery Beat periodic task runner.
      # enable_beat: true

      # Number of Celery Workers to start.
      # concurrency: 2

      # Log Level to use for Celery Worker.
      # Valid options are: DEBUG, INFO, WARNING, ERROR
      # loglevel: DEBUG

      # Queues to join
      # queues: celery,galaxy.internal,galaxy.external

      # Pool implementation
      # Valid options are: prefork, eventlet, gevent, solo, processes, threads
      # pool: threads

      # Extra arguments to pass to Celery command line.
      # extra_args:

      # Value of supervisor startsecs, systemd TimeoutStartSec
      # start_timeout: 10

      # Value of supervisor stopwaitsecs, systemd TimeoutStopSec
      # stop_timeout: 10

      # Memory limit (in GB). If the service exceeds the limit, it will be killed. Default is no limit or the value of the
      # ``memory_limit`` setting at the top level of the Gravity configuration, if set. Ignored if ``process_manager`` is
      # ``supervisor``.
      # memory_limit:

      # Extra environment variables and their values to set when running the service. A dictionary where keys are the variable
      # names.
      # environment: {}

    # Configuration for gx-it-proxy.
    gx_it_proxy:

      # Set to true to start gx-it-proxy
      # enable: false

      # Public-facing IP of the proxy
      # ip: localhost

      # Public-facing port of the proxy
      # port: 4002

      # Routes file to monitor.
      # Should be set to the same path as ``interactivetools_map`` in the ``galaxy:`` section.
      # sessions: database/interactivetools_map.sqlite

      # Include verbose messages in gx-it-proxy
      # verbose: true

      # Forward all requests to IP.
      # This is an advanced option that is only needed when proxying to remote interactive tool container that cannot be reached through the local network.
      # forward_ip:

      # Forward all requests to port.
      # This is an advanced option that is only needed when proxying to remote interactive tool container that cannot be reached through the local network.
      # forward_port:

      # Rewrite location blocks with proxy port.
      # This is an advanced option that is only needed when proxying to remote interactive tool container that cannot be reached through the local network.
      # reverse_proxy: false

      # Value of supervisor startsecs, systemd TimeoutStartSec
      # start_timeout: 10

      # Value of supervisor stopwaitsecs, systemd TimeoutStopSec
      # stop_timeout: 10

      # Memory limit (in GB). If the service exceeds the limit, it will be killed. Default is no limit or the value of the
      # ``memory_limit`` setting at the top level of the Gravity configuration, if set. Ignored if ``process_manager`` is
      # ``supervisor``.
      # memory_limit:

      # Extra environment variables and their values to set when running the service. A dictionary where keys are the variable
      # names.
      # environment: {}

    # Configuration for tusd server (https://github.com/tus/tusd).
    # The ``tusd`` binary must be installed manually and made available on PATH (e.g in galaxy's .venv/bin directory).
    tusd:

      # Enable tusd server.
      # If enabled, you also need to set up your proxy as outlined in https://docs.galaxyproject.org/en/latest/admin/nginx.html#receiving-files-via-the-tus-protocol.
      # enable: false

      # Path to tusd binary
      # tusd_path: tusd

      # Host to bind the tusd server to
      # host: localhost

      # Port to bind the tusd server to
      # port: 1080

      # Directory to store uploads in.
      # Must match ``tus_upload_store`` setting in ``galaxy:`` section.
      # upload_dir:

      # Comma-separated string of enabled tusd hooks.
      #
      # Leave at the default value to require authorization at upload creation time.
      # This means Galaxy's web process does not need to be running after creating the initial
      # upload request.
      #
      # Set to empty string to disable all authorization. This means data can be uploaded (but not processed)
      # without the Galaxy web process being available.
      #
      # You can find a list of available hooks at https://github.com/tus/tusd/blob/master/docs/hooks.md#list-of-available-hooks.
      # hooks_enabled_events: pre-create

      # Extra arguments to pass to tusd command line.
      # extra_args:

      # Value of supervisor startsecs, systemd TimeoutStartSec
      # start_timeout: 10

      # Value of supervisor stopwaitsecs, systemd TimeoutStopSec
      # stop_timeout: 10

      # Memory limit (in GB). If the service exceeds the limit, it will be killed. Default is no limit or the value of the
      # ``memory_limit`` setting at the top level of the Gravity configuration, if set. Ignored if ``process_manager`` is
      # ``supervisor``.
      # memory_limit:

      # Extra environment variables and their values to set when running the service. A dictionary where keys are the variable
      # names.
      # environment: {}

    # Configuration for Galaxy Reports.
    reports:

      # Enable Galaxy Reports server.
      # enable: false

      # Path to reports.yml, relative to galaxy.yml if not absolute
      # config_file: reports.yml

      # The socket to bind. A string of the form: ``HOST``, ``HOST:PORT``, ``unix:PATH``, ``fd://FD``. An IP is a valid HOST.
      # bind: localhost:9001

      # Controls the number of Galaxy Reports application processes Gunicorn will spawn.
      # It is not generally necessary to increase this for the low-traffic Reports server.
      # workers: 1

      # Gunicorn workers silent for more than this many seconds are killed and restarted.
      # Value is a positive number or 0. Setting it to 0 has the effect of infinite timeouts by disabling timeouts for all workers entirely.
      # timeout: 300

      # URL prefix to serve from.
      # The corresponding nginx configuration is (replace <url_prefix> and <bind> with the values from these options):
      #
      # location /<url_prefix>/ {
      #     proxy_pass http://<bind>/;
      # }
      #
      # If <bind> is a unix socket, you will need a ``:`` after the socket path but before the trailing slash like so:
      #     proxy_pass http://unix:/run/reports.sock:/;
      # url_prefix:

      # Extra arguments to pass to Gunicorn command line.
      # extra_args:

      # Value of supervisor startsecs, systemd TimeoutStartSec
      # start_timeout: 10

      # Value of supervisor stopwaitsecs, systemd TimeoutStopSec
      # stop_timeout: 10

      # Memory limit (in GB). If the service exceeds the limit, it will be killed. Default is no limit or the value of the
      # ``memory_limit`` setting at the top level of the Gravity configuration, if set. Ignored if ``process_manager`` is
      # ``supervisor``.
      # memory_limit:

      # Extra environment variables and their values to set when running the service. A dictionary where keys are the variable
      # names.
      # environment: {}

    # Configure dynamic handlers in this section.
    # See https://docs.galaxyproject.org/en/latest/admin/scaling.html#dynamically-defined-handlers for details.
    # handlers: {}

Splitting Gravity and Galaxy Configurations
-------------------------------------------

As a convenience for cases where you may want to have different Gravity configurations but a single Galaxy
configuration (e.g. your Galaxy server is split across multiple hosts), the Gravity configuration can be stored in a
separate file. In this case, you must set the ``galaxy_config_file`` option in the Gravity config to specify the
location of the Galaxy config file.

For example, on a deployment where the web (gunicorn) and job handler processes run on different hosts, one might have:

In ``gravity.yml`` on the web host::

    gravity:
      galaxy_config_file: galaxy.yml
      log_dir: /var/log/galaxy
      gunicorn:
        bind: localhost:8888
      celery:
        enable: false
        enable_beat: false

In ``gravity.yml`` on the job handler host::

    gravity:
      galaxy_config_file: galaxy.yml
      log_dir: /var/log/galaxy
      gunicorn:
        enable: false
      celery:
        enable: true
        enable_beat: true
      handlers:
        handler:
          processes: 2

Galaxy Job Handlers
-------------------

Gravity has support for reading Galaxy's job configuration: it can read statically configured job handlers in the
``job_conf.yml`` or ``job_conf.yml`` files, or the job configuration inline from the ``job_config`` option in
``galaxy.yml``. However, unless you need to statically define handlers, it is simpler to configure Gravity to run
`dynamically defined handlers`_ as detailed in the Galaxy scaling documentation.

When using dynamically defined handlers, be sure to explicitly set the `job handler assignment method`_ to
``db-skip-locked`` or ``db-transaction-isolation`` to prevent the web process from also handling jobs.

Configuration and State
-----------------------

Older versions of Gravity stored a considerable amount of *config state* in ``$GRAVITY_STATE_DIR/configstate.yaml``. As
of version 1.0.0, Gravity does not store state information, and this file can be removed.

Although Gravity no longer uses the config state file, it does still use a state directory for storing supervisor
configs, the default log directory (if ``log_dir`` is unchanged), and the celery-beat database. This directory defaults
to ``<galaxy_root>/database/gravity/`` by way of the ``data_dir`` option in the ``galaxy`` section of ``galaxy.yml``
(which defaults to ``<galaxy_root>/database/``).

Subcommands
===========

Use ``galaxyctl --help`` for help. Subcommands also support ``--help``, e.g. ``galaxy register --help``

start
-----

Start and run Galaxy and associated processes in daemonized (background) mode, or ``-f`` to run in the foreground and
follow log files. The ``galaxy`` command is a shortcut for ``galaxyctl start -f``.

If no config files are registered and you run ``galaxyctl start`` from the root of a Galaxy source tree, it
automatically runs the equivalent of::

    $ galaxyctl register config/galaxy.yml  # or galaxy.yml.sample if galaxy.yml does not exist
    $ galaxyctl update
    $ galaxyctl start

stop
----

Stop daemonized Galaxy server processes. If no processes remain running after this step (which should be the case when
working with a single Galaxy instance), ``supervisord`` will terminate.

restart
-------

Restart Galaxy server processes. This is done in a relatively "brutal" fashion: processes are signaled (by supervisor)
to exit, and then are restarted. See the ``graceful`` subcommand to restart gracefully.

graceful
--------

Restart Galaxy with minimal interruption. If running with `gunicorn`_ this means holding the web socket open while
restarting (connections to Galaxy will block). If running with `unicornherder`_, a new Galaxy application will be
started and the old one shut down only once the new one is accepting connections. A graceful restart with unicornherder
should be transparent to clients.

update
------

Figure out what has changed in configs, which could be:

-  changes to the Gravity configuration options in ``galaxy.yml``
-  adding or removing handlers in ``job_conf.yml`` or ``job_conf.xml``

This may cause service restarts if there are any changes.

Any needed changes to supervisor or systemd configs will be performed and then ``supervisorctl update`` or ``systemctl
daemon-reload`` will be called.

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
etc. ``galaxyctl exec`` comands are written to the supervisor/systemd service files rather than the underlying command
so that it is not necesary to rewrite the process manager configs and update the process manager every time a parameter
is changed.

.. _Galaxy: http://galaxyproject.org/
.. _gunicorn: https://gunicorn.org/
.. _celery: https://docs.celeryq.dev/
.. _tusd: https://tus.io/
.. _supervisor: http://supervisord.org/
.. _systemd: https://www.freedesktop.org/wiki/Software/systemd/
.. _systemd service unit files: https://www.freedesktop.org/software/systemd/man/systemd.unit.html
.. _systemd user mode: https://www.freedesktop.org/software/systemd/man/user@.service.html
.. _virtualenv: https://virtualenv.pypa.io/
.. _venv: https://docs.python.org/3/library/venv.html
.. _Galaxy Installation with Ansible: https://training.galaxyproject.org/training-material/topics/admin/tutorials/ansible-galaxy/tutorial.html
.. _unicornherder: https://github.com/alphagov/unicornherder
.. _job handler assignment method: https://docs.galaxyproject.org/en/master/admin/scaling.html#job-handler-assignment-methods
.. _dynamically defined handlers: https://docs.galaxyproject.org/en/latest/admin/scaling.html#dynamically-defined-handlers
.. _Ansible: http://www.ansible.com/
.. _Issue #6: https://github.com/galaxyproject/gravity/issues/6
