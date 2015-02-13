=========
 History
=========

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
