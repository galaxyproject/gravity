"""
"""
import json


class AttributeDictEncoder(json.JSONEncoder):

    def encode(self, o):
        if isinstance(o, AttributeDict):
            return o.serialize(self)
        return json.JSONEncoder.encode(self, o)


class AttributeDict(dict):

    @classmethod
    def loads(cls, s, *args, **kwargs):
        return cls(json.loads(s, *args, **kwargs))

    def __setattr__(self, name, value):
        self[name] = value

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError("'%s' object has no attribute '%s'" % (self.__class__.__name__, name))

    def serialize(self, encoder):
        d = {}
        for k in self.keys():
            if not k.startswith('_'):
                d[k] = self[k]
        return json.JSONEncoder.encode(encoder, d)

    def dumps(self, *args, **kwargs):
        kwargs['cls'] = AttributeDictEncoder
        return json.dumps(self, *args, **kwargs)

    def dump(self, fp, *args, **kwargs):
        raise Exception("This isn't using the Encoder, what gives?")
        kwargs['cls'] = AttributeDictEncoder
        return json.dump(self, fp, *args, **kwargs)
