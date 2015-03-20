"""
"""
from UserDict import DictMixin


class ContextDict(object, DictMixin):

    def __init__(self, dict, parent=None):
        """
        Create a new expression context that looks for values in the
        container object 'dict', and falls back to 'parent'
        """
        self.dict = dict
        self.parent = parent

    def __getitem__(self, key):
        if key in self.dict:
            return self.dict[key]
        if self.parent is not None and key in self.parent:
            return self.parent[key]
        raise KeyError(key)

    def __setitem__(self, key, value):
        self.dict[key] = value

    def __delitem__(self, key):
        del self.dict[key]

    def __contains__(self, key):
        if key in self.dict:
            return True
        if self.parent is not None and key in self.parent:
            return True
        return False

    def __str__(self):
        return str(self.dict)

    def __nonzero__(self):
        if not self.dict and not self.parent:
            return False
        return True

    def get_source(self, key, *args):
        if key in self.dict:
            return self.dict[key], 'local'
        if self.parent is not None and key in self.parent:
            return self.parent[key], 'inherited'
        if len(args):
            return args[0], 'default'
        raise KeyError(key)
