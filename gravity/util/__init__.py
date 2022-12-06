"""
"""
import collections.abc
import copy
import os
import sys

import jsonref
import requests
import requests_unixsocket
import yaml

from gravity.settings import Settings


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


def settings_to_sample():
    schema = Settings.schema_json()
    # expand schema for easier processing
    data = jsonref.loads(schema)
    strings = [process_property("gravity", data)]
    for key, value in data["properties"].items():
        strings.append(process_property(key, value, 1))
    concat = "\n".join(strings)
    return concat


def process_property(key, value, depth=0):
    extra_white_space = "  " * depth
    default = value.get("default", "")
    if isinstance(default, dict):
        # Little hack that prevents listing the default value for tusd in the sample config
        default = {}
    if default != "":
        # make values more yaml-like.
        default = yaml.dump(default)
        if default.endswith("\n...\n"):
            default = default[: -(len("\n...\n"))]
        default = default.strip()
    description = "\n".join(f"{extra_white_space}# {desc}".rstrip() for desc in value["description"].strip().split("\n"))
    combined = value.get("allOf", [])
    if not combined and value.get("anyOf"):
        # we've got a union
        combined = [c for c in value["anyOf"] if c["type"] == "object"]
    if combined and combined[0].get("properties"):
        # we've got a nested map, add key once
        description = f"{description}\n{extra_white_space}{key}:\n"
    has_child = False
    for item in combined:
        if "enum" in item:
            enum_items = [i for i in item["enum"] if not i.startswith("_")]
            description = f'{description}\n{extra_white_space}# Valid options are: {", ".join(enum_items)}'
        if "properties" in item:
            has_child = True
            for _key, _value in item["properties"].items():
                description = f"{description}\n{process_property(_key, _value, depth=depth+1)}"
    if not has_child or key == "handlers":
        comment = "# "
        if key == "gravity":
            # gravity section should not be commented
            comment = ""
        if default == "":
            value_sep = ""
        else:
            value_sep = " "
        description = f"{description}\n{extra_white_space}{comment}{key}:{value_sep}{default}\n"
    return description


def http_check(bind, path):
    if bind.startswith("unix:"):
        socket = requests.utils.quote(bind.split(":", 1)[1], safe="")
        session = requests_unixsocket.Session()
        response = session.get(f"http+unix://{socket}{path}")
    else:
        response = requests.get(f"http://{bind}{path}", timeout=30)
    response.raise_for_status()
    return response
