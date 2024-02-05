#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
InfiniteDefaultRevisionDict sort items in the order of latest updates and allows arbitrary chaining of keys.

For example,

>>> d=InfiniteDefaultRevisionDict()
>>> dct[person_name][gender] = 'M'
>>> dct[company_name][employees] = [...]
"""

import bisect, json
from collections import namedtuple
from collections.abc import MutableMapping


from collections import OrderedDict, defaultdict

class Dict(OrderedDict):
	def __init__(self, default=None, init_dct={}):
		self._default = default
		self.update(init_dct)

	def __setitem__(self, key, value):
		super().__setitem__(key, value)
		self.move_to_end(key)

	def __missing__(self, key):
		self[key] = self._default() if callable(self._default) else self._default
		return self[key]

	def to_json(self, fp=None, **kwargs):
		return json.dumps(self, default=lambda t: dict(t), **kwargs) if fp==None else json.dump(self, fp, default=lambda t: dict(t), **kwargs)

	def from_json(self, fp=None, data=''):
		self.update(json.loads(data, object_hook=lambda t: (Dict(self._default, t) if type(t)==dict else t)) if fp==None \
			else json.load(fp, object_hook=lambda t: (Dict(self._default, t) if type(t)==dict else t)))
		return self


InfiniteDefaultRevisionDict = lambda: Dict(InfiniteDefaultRevisionDict)

# dd=SDict()
# dd['a']['b'][2] = [1,'2',3.5]

# d=LastUpdatedOrderedDict({'a':1, 'b':2})
