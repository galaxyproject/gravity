=========
 History
=========

0.9
===

- Converted CLI from `argparse`_ to `click`_.
- Stole ideas and code from `planemo`_ in general.
- Improve the AttributeDict so that it can have "hidden" items (anything that
  starts with a ``_``) that won't be serialized. Also, it serializes itself and
  can be created via deserialization from a classmethod. This simplifies using
  it to persist state data in the new GravityState subclass.

.. _argparse: https://docs.python.org/3/library/argparse.html
.. _click: http://click.pocoo.org/
.. _planemo: https://github.com/galaxyproject/planemo

0.8.3
=====

- Merge ``galaxycfg`` and ``galaxyadm`` commands to ``galaxy``.

0.8.2
=====

- Allow for passing names of individual services directly to ``supervisorctl``
  via the ``start``, ``stop``, and ``restart`` methods.
- Fix a bug where uWSGI would not start when using the automatic virtualenv
  install method.

0.8.1
=====

- Version bump because I deleted the 0.8 files from PyPI, and despite the fact
  that it lets you delete them, it doesn't let you upload once they have been
  uploaded once...

0.8
===

- Add auto-register to ``galaxy start`` if it's called from the root (or
  subdirectory) of a Galaxy root directory.
- Make ``galaxycfg remove`` accept instance names as params in addition to
  config file paths.
- Use the same hash generated for an instance name as the hash for a generated
  virtualenv name, so virtualenvs are more easily identified as belonging to a
  config.
- Renamed from ``galaxyadmin`` to ``gravity`` (thanks John Chilton).

0.7
===

- Added the ``galaxyadm`` subcommand ``graceful`` on a suggestion from Nicola
  Soranzo.
- Install uWSGI into the config's virtualenv if requested.
- Removed any dependence on Galaxy and eggs.
- Moved project to its own repository from the Galaxy clone I'd been working
  from.

Older
=====

- Works in progress as part of the Galaxy code.
