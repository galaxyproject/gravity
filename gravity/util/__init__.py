"""
"""
import collections.abc
import copy
import os
import sys

import jsonref
import ruamel.yaml
import yaml
from gravity.settings import Settings


class AttributeDict(dict):
    yaml_tag = "tag:yaml.org,2002:map"

    @classmethod
    def loads(cls, s, *args, **kwargs):
        return cls(yaml.safe_load(s, *args, **kwargs))

    @classmethod
    def to_yaml(cls, representer, node):
        d = {}
        for k in node.keys():
            if not k.startswith("_"):
                d[k] = node[k]
        return representer.represent_mapping(cls.yaml_tag, d)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._yaml = ruamel.yaml.YAML()
        self._yaml.register_class(self.__class__)

    def __eq__(self, other):
        return all([other[k] == v for k, v in self.items() if not k.startswith("_")])

    def __setattr__(self, name, value):
        self[name] = value

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def dump(self, fp, *args, **kwargs):
        self._yaml.dump(self, fp)


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
    description = "\n".join(f"{extra_white_space}# {desc}" for desc in value["description"].strip().split("\n"))
    allOff = value.get("allOf", [])
    if allOff and allOff[0].get("properties"):
        # we've got a nested map, add key once
        description = f"{description}\n{extra_white_space}{key}:\n"
    for item in allOff:
        if "enum" in item:
            description = f'{description}\n{extra_white_space}# Valid options are: {", ".join(item["enum"])}'
        if "properties" in item:
            for _key, _value in item["properties"].items():
                description = f"{description}\n{process_property(_key, _value, depth=depth+1)}"
    if not default == "{}" or key == "handlers":
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
