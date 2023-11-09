Installation and Configuration
==============================

Installation
------------

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

Configuration
-------------

Gravity needs to know where your Galaxy configuration file is, and depending on your Galaxy layout, some additional
details like the paths to its virtualenv and root directory. By default, Gravity's configuration is defined in Galaxy's
configuration file (``galaxy.yml``) to be easy and familiar for Galaxy administrators. Gravity's configuration is
defined underneath the ``gravity`` key, and Galaxy's configuration is defined underneath the ``galaxy`` key. For
example:

.. code:: yaml

    ---
    gravity:
      gunicorn:
        bind: localhost:8192
    galaxy:
      database_connection: postgresql:///galaxy

Configuration Search Paths
""""""""""""""""""""""""""

If you run ``galaxy`` or ``galaxyctl`` from the root of a Galaxy source checkout and do not specify the config file
option, ``config/galaxy.yml`` or ``config/galaxy.yml.sample`` will be automatically used. To avoid having to run from
the Galaxy root directory or to work with a config file in a different location, you can explicitly point Gravity at
your Galaxy configuration file with the ``--config-file`` (``-c``) option or the ``$GRAVITY_CONFIG_FILE`` (or
``$GALAXY_CONFIG_FILE``, as set by Galaxy's ``run.sh`` script) environment variable. Then it's possible to run the
``galaxyctl`` command from anywhere.

Often times it's convenient to put the environment variable in the Galaxy user's shell environment file, e.g.:

.. code:: console

    $ echo "export GRAVITY_CONFIG_FILE='/srv/galaxy/config/galaxy.yml'" >> ~/.bash_profile

When running Gravity as root, the following configuration files will automatically be searched for and read, unless
``--config-file`` is specified or ``$GRAVITY_CONFIG_FILE`` is set:

- ``/etc/galaxy/gravity.yml``
- ``/etc/galaxy/galaxy.yml``
- ``/etc/galaxy/gravity.d/*.y(a?)ml``

Splitting Gravity and Galaxy Configurations
"""""""""""""""""""""""""""""""""""""""""""

For more advanced deployments, it is *not* necessary to write your entire Galaxy configuration to the Gravity config
file. You can write only the Gravity configuration, and then point to your Galaxy config file with the
``galaxy_config_file`` option in the Gravity config. This can be useful for cases such as your Galaxy server being split
across multiple hosts.

For example, on a deployment where the web (gunicorn) and job handler processes run on different hosts, one might have:

In ``gravity.yml`` on the web host:

.. code:: yaml

    ---
    gravity:
      galaxy_config_file: galaxy.yml
      log_dir: /var/log/galaxy
      gunicorn:
        bind: localhost:8888
      celery:
        enable: false
        enable_beat: false

In ``gravity.yml`` on the job handler host:

.. code:: yaml

    ---
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

See the :ref:`Managing Multiple Galaxies` section for additional examples.

Configuration Options
---------------------

The following options in the ``gravity`` section of ``galaxy.yml`` can be used to configure Gravity:

.. code:: yaml

  # Configuration for Gravity process manager.
  # ``uwsgi:`` section will be ignored if Galaxy is started via Gravity commands (e.g ``./run.sh``, ``galaxy`` or ``galaxyctl``).
  gravity:

    # Process manager to use.
    # ``supervisor`` is the default process manager when Gravity is invoked as a non-root user.
    # ``systemd`` is the default when Gravity is invoked as root.
    # Valid options are: supervisor, systemd
    # process_manager:

    # What command to write to the process manager configs
    # `gravity` (`galaxyctl exec <service-name>`) is the default
    # `direct` (each service's actual command) is also supported.
    # Valid options are: gravity, direct
    # service_command_style: gravity

    # Use the process manager's *service instance* functionality for services that can run multiple instances.
    # Presently this includes services like gunicorn and Galaxy dynamic job handlers. Service instances are only supported if
    # ``service_command_style`` is ``gravity``, and so this option is automatically set to ``false`` if
    # ``service_command_style`` is set to ``direct``.
    # use_service_instances: true

    # umask under which services should be executed. Setting ``umask`` on an individual service overrides this value.
    # umask: '022'

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

    # Configuration for Gunicorn. Can be a list to run multiple gunicorns for rolling restarts.
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

      # umask under which service should be executed
      # umask:

      # Value of supervisor startsecs, systemd TimeoutStartSec
      # start_timeout: 15

      # Value of supervisor stopwaitsecs, systemd TimeoutStopSec
      # stop_timeout: 65

      # Amount of time to wait for a server to become alive when performing rolling restarts.
      # restart_timeout: 300

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

      # umask under which service should be executed
      # umask:

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

      # gx-it-proxy version
      # version: '>=0.0.6'

      # Public-facing IP of the proxy
      # ip: localhost

      # Public-facing port of the proxy
      # port: 4002

      # Routes file to monitor.
      # Should be set to the same path as ``interactivetools_map`` in the ``galaxy:`` section. This is ignored if
      # ``interactivetools_map is set``.
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

      # umask under which service should be executed
      # umask:

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

      # umask under which service should be executed
      # umask:

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

      # umask under which service should be executed
      # umask:

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

Galaxy Job Handlers
-------------------

Gravity has support for reading Galaxy's job configuration: it can read statically configured job handlers in the
``job_conf.yml`` or ``job_conf.xml`` files, or the job configuration inline from the ``job_config`` option in
``galaxy.yml``. However, unless you need to statically define handlers, it is simpler to configure Gravity to run
`dynamically defined handlers`_ as detailed in the Galaxy scaling documentation.

When using dynamically defined handlers, be sure to explicitly set the `job handler assignment method`_ to
``db-skip-locked`` or ``db-transaction-isolation`` to prevent the web process from also handling jobs.

Gravity State
-------------

Older versions of Gravity stored a considerable amount of *config state* in ``$GRAVITY_STATE_DIR/configstate.yaml``. As
of version 1.0.0, Gravity does not store state information, and this file can be removed if left over from an older
installation.

Although Gravity no longer uses the config state file, it does still use a state directory for storing supervisor
configs, the default log directory (if ``log_dir`` is unchanged), and the celery-beat database. This directory defaults
to ``<galaxy_root>/database/gravity/`` by way of the ``data_dir`` option in the ``galaxy`` section of ``galaxy.yml``
(which defaults to ``<galaxy_root>/database/``).

If running multiple Galaxy servers with the same Gravity configuration as described in :ref:`Managing Multiple Galaxies`
and if doing so using supervisor rather than systemd, the supervisor configurations will be stored in
``$XDG_CONFIG_HOME/galaxy-gravity`` (``$XDG_CONFIG_HOME`` defaults to ``~/.config/galaxy-gravity``)

In any case, you can override the path to the state directory using the ``--state-dir`` option, or the
``$GRAVITY_STATE_DIR`` environment variable.

.. note::

    Galaxy 22.01 and 22.05 automatically set ``$GRAVITY_STATE_DIR`` to ``<galaxy_root>/database/gravity`` in the
    virtualenv's activation script, ``activate``. This can be removed from the activate script when using Gravity 1.0.0
    or later.

.. _virtualenv: https://virtualenv.pypa.io/
.. _venv: https://docs.python.org/3/library/venv.html
.. _dynamically defined handlers: https://docs.galaxyproject.org/en/latest/admin/scaling.html#dynamically-defined-handlers
.. _job handler assignment method: https://docs.galaxyproject.org/en/master/admin/scaling.html#job-handler-assignment-methods
