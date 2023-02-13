Basic Usage
===========

A basic example of starting and running a simple Galaxy server from a source clone in the foreground is provided in the
ref:`Quick Start` guide. This section covers more typical usage for production Galaxy servers.

Managing a Single Galaxy
------------------------

If you have not installed Gravity separate from the Galaxy virtualenv, simply activate Galaxy's virtualenv, which will
put Gravity's ``galaxyctl`` and ``galaxy`` commands on your ``$PATH``:

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

Gravity can either run Galaxy via the `supervisor`_ process manager (the default) or `systemd`_. For production servers,
**it is recommended that you run Gravity as root in systemd mode**. See the :ref:`Managing a Production Galaxy` section
for details.

As shown in the Quick Start, the ``galaxy`` command will run a Galaxy server in the foreground. The ``galaxy`` command
is actually a shortcut for two separate steps: 1. read the provided ``galaxy.yml`` and write out the corresponding
process manager configurations, and 2. start and run Galaxy in the foreground using the process manager (`supervisor`_).
You can perform these steps separately (and in this example, start Galaxy as a backgrounded daemon instead of in the
foreground):

.. code:: console

    $ galaxyctl update
    Adding service gunicorn
    Adding service celery
    Adding service celery-beat
    $ galaxyctl start
    celery                           STARTING
    celery-beat                      STARTING
    gunicorn                         STARTING
    Log files are in /srv/galaxy/var/gravity/log

When running as a daemon, the ``stop`` subcommand stops your Galaxy server:

.. code:: console

    $ galaxyctl stop
    celery-beat: stopped
    gunicorn: stopped
    celery: stopped
    All processes stopped, supervisord will exit
    Shut down

Most Gravity subcommands (such as ``stop``, ``start``, ``restart``, ...) are straightforward, but a few subcommands are
worth pointing out: :ref:`update`, :ref:`graceful`, and :ref:`exec`. All subcommands are documented in the
:ref:`Subcommands` section and their respective ``--help`` output.

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

.. _supervisor: http://supervisord.org/
.. _systemd: https://www.freedesktop.org/wiki/Software/systemd/
.. _systemd service unit files: https://www.freedesktop.org/software/systemd/man/systemd.unit.html
.. _systemd user mode: https://www.freedesktop.org/software/systemd/man/user@.service.html
