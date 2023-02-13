.. figure:: https://raw.githubusercontent.com/galaxyproject/gravity/main/docs/gravity-logo.png
   :alt: Gravity Logo
   :align: center
   :figwidth: 100%
   :target: https://github.com/galaxyproject/gravity

Process management for `Galaxy`_ servers.

.. image:: https://readthedocs.org/projects/gravity/badge/?version=latest
   :target: http://gravity.readthedocs.io/en/latest/
   :alt: Documentation Status

.. image:: https://badge.fury.io/py/gravity.svg
   :target: https://pypi.python.org/pypi/gravity/
   :alt: Gravity on the Python Package Index (PyPI)

.. image:: https://github.com/galaxyproject/gravity/actions/workflows/test.yaml/badge.svg
   :target: https://github.com/galaxyproject/gravity/actions/workflows/test.yaml

* License: MIT
* Documentation: https://gravity.readthedocs.io
* Code: https://github.com/galaxyproject/gravity

Overview
========

Modern Galaxy servers run multiple disparate processes: `gunicorn`_ for serving the web application, `celery`_ for
asynchronous tasks, `tusd`_ for fault-tolerant uploads, standalone Galaxy processes for job handling, and more. Gravity
is Galaxy's process manager, to make configuring and running these services simple.

Installing Gravity will give you two executables, ``galaxyctl`` which is used to manage the starting, stopping, and
logging of Galaxy's various processes, and ``galaxy``, which can be used to run a Galaxy server in the foreground.

Quick Start
===========

Installation
------------

Python 3.7 or later is required. Gravity can be installed independently of Galaxy, but it is also a dependency of
Galaxy since Galaxy 22.01. If you've installed Galaxy, then Gravity is already installed in Galaxy's virtualenv.

To install independently:

.. code:: console

    $ pip install gravity

Usage
-----

From the root directory of a source checkout of Galaxy, after first run (or running Galaxy's
``./scripts/common_startup.sh``), activate Galaxy's virtualenv, which will put Gravity's ``galaxyctl`` and ``galaxy``
commands on your ``$PATH``:

.. code:: console

    $ . ./.venv/bin/activate
    $ galaxyctl --help
    Usage: galaxyctl [OPTIONS] COMMAND [ARGS]...

      Manage Galaxy server configurations and processes.

    ... additional help output

You can start and run Galaxy in the foreground using the ``galaxy`` command:

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

More detailed configuration and usage examples, especially those concerning production Galaxy servers, can be found in
`the full documentation`_.

.. _Galaxy: http://galaxyproject.org/
.. _gunicorn: https://gunicorn.org/
.. _celery: https://docs.celeryq.dev/
.. _tusd: https://tus.io/
.. _the full documentation: https://gravity.readthedocs.io
