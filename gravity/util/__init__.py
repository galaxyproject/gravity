"""
"""
import collections.abc
import copy
import os
import sys
from urllib.parse import quote

import requests
import requests_unixsocket

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


def is_root():
    """Check if the current process is running as root.

    Returns ``False`` if the ``GRAVITY_IGNORE_ROOT`` environment variable is
    set to a truthy value (``1``, ``true``, ``yes``), allowing Gravity to
    behave as a non-root user even when euid is 0.  This is useful when
    running inside containers or via Planemo where the process is root but
    systemd is unavailable.
    """
    if os.environ.get("GRAVITY_IGNORE_ROOT", "0").lower() in ("1", "true", "yes"):
        return False
    return os.geteuid() == 0


def recursive_update(to_update, update_from):
    """
    Update values in `to_update` with values in `update_from`.

    Does not mutate values in to_update, but returns a new dictionary.
    """
    d = copy.deepcopy(to_update)
    for k, v in update_from.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = recursive_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


def which(file):
    # http://stackoverflow.com/questions/5226958/which-equivalent-function-in-python
    if os.path.exists(os.path.dirname(sys.executable) + "/" + file):
        return os.path.dirname(sys.executable) + "/" + file
    for path in os.environ["PATH"].split(":"):
        if os.path.exists(path + "/" + file):
            return path + "/" + file
    return None


def http_check(bind, path):
    if bind.startswith("unix:"):
        socket = quote(bind.split(":", 1)[1], safe="")
        session = requests_unixsocket.Session()
        response = session.get(f"http+unix://{socket}{path}")
    else:
        response = requests.get(f"http://{bind}{path}", timeout=30)
    response.raise_for_status()
    return response
