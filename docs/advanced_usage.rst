Advanced Usage
==============

Zero-Downtime Restarts
----------------------

Prior to Gravity 1.0, the preferred solution for performing zero-downtime restarts was `unicornherder`_. However, due to
limitations in the unicornherder software, it does not always successfully perform zero-downtime restarts. Because of
this, Gravity is now able to perform rolling restarts of gunicorn services if more than one gunicorn is configured.

To run multiple gunicorn processes, configure the ``gunicorn`` section of the Gravity configuration as a *list*. Each
item in the list is a gunicorn configuration, and can have all of the same parameters as a single gunicorn
configuration:

.. code:: yaml

    gravity:
      gunicorn:
        - bind: unix:/srv/galaxy/var/gunicorn0.sock
          workers: 4
        - bind: unix:/srv/galaxy/var/gunicorn1.sock
          workers: 4

.. caution::

   This will start multiple Galaxy servers with the same ``server_name``. If you have not configured separate Galaxy
   processes to act as job handlers, your gunicorn processes will handle them, resulting in job errors due to handling
   the same job multiple times. See the Gravity and Galaxy documentation on configuring handlers.

Your proxy server can balance load between the two gunicorns. For example, with nginx:

.. code:: nginx

    upstream galaxy {
        server unix:/srv/galaxy/var/gunicorn0.sock;
        server unix:/srv/galaxy/var/gunicorn1.sock;
    }

    http {
        location / {
            proxy_pass http://galaxy;
        }
    }

By default, Gravity will wait 300 seconds for the gunicorn server to respond to web requests after initiating the
restart. To change this timeout this, set the ``restart_timeout`` option on each configured ``gunicorn`` instance.

Service Instances
-----------------

In the case of multiple gunicorn instances as described in :ref:`Zero-Downtime Restarts` and multiple dynamic handlers
as described in :ref:`Galaxy Job Handlers`, Gravity will create multiple *service instances* of each service. This
allows multiple processes to be run from a single service definition.

In supervisor, this means that the service names as presented by supervisor are appended with ``:INSTANCE_NUMBER``,
e.g.:

.. code:: console

    $ galaxyctl status
    celery                           RUNNING   pid 121363, uptime 0:02:33
    celery-beat                      RUNNING   pid 121364, uptime 0:02:33
    gunicorn:0                       RUNNING   pid 121365, uptime 0:02:33
    gunicorn:1                       RUNNING   pid 121366, uptime 0:02:33

However, ``galaxyctl`` commands that take a service name still use the base service name, e.g.:

.. code:: console

    $ galaxyctl stop gunicorn
    gunicorn:0: stopped
    gunicorn:1: stopped
    Not all processes stopped, supervisord not shut down (hint: see `galaxyctl status`)

In systemd, the service names as presented by systemd are appended with ``@INSTANCE_NUMBER``,
e.g.:

.. code:: console

    $ galaxyctl status
      UNIT                       LOAD   ACTIVE SUB     DESCRIPTION
      galaxy-celery-beat.service loaded active running Galaxy celery-beat
      galaxy-celery.service      loaded active running Galaxy celery
      galaxy-gunicorn@0.service  loaded active running Galaxy gunicorn (process 0)
      galaxy-gunicorn@1.service  loaded active running Galaxy gunicorn (process 1)
      galaxy.target              loaded active active  Galaxy

As with supervisor, ``galaxyctl`` commands that take a service name still use the base service name.

If you prefer not to work with service instances and want Galaxy to write a service configuration file for each instance
of each service, you can do so by setting ``use_service_instances`` in the Gravity configuration to ``false``.

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

Although it is strongly encouraged to use systemd for running multiple instances, it is possible to use supervisor.
Please see the :ref:`Gravity State` section for important details on how and where Gravity stores the supervisor
configuration and log files.

.. _unicornherder: https://github.com/alphagov/unicornherder
