"""
"""
import ruamel.yaml
import yaml


class AttributeDict(dict):
    yaml_tag = u'tag:yaml.org,2002:map'

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
