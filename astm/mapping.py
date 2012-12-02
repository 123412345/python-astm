# -*- coding: utf-8 -*-
#
# Copyright (C) 2012 Alexander Shorin
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#

import datetime
import decimal
from operator import itemgetter
from itertools import islice
try:
    from itertools import izip, izip_longest
    from .compat import bytes
except ImportError: # Python 3
    from itertools import zip_longest as izip_longest
    izip = zip
    from .compat import basestring, unicode, bytes, long


def make_string(value):
    if isinstance(value, unicode):
        return value
    elif isinstance(value, bytes):
        return unicode(value, 'utf-8')
    else:
        return unicode(value)


class Field(object):
    """Base mapping field class."""
    def __init__(self, name=None, default=None):
        self.name = name
        self.default = default

    def __get__(self, instance, owner):
        if instance is None:
            return self
        value = instance._data.get(self.name)
        if value is not None:
            value = self._get_value(value)
        elif self.default is not None:
            default = self.default
            if hasattr(default, '__call__'):
                default = default()
            value = default
        return value

    def __set__(self, instance, value):
        if value is not None:
            value = self._set_value(value)
        instance._data[self.name] = value

    def _get_value(self, value):
        return value

    def _set_value(self, value):
        return make_string(value)


class MetaMapping(type):

    def __new__(mcs, name, bases, d):
        fields = []
        for base in bases:
            if hasattr(base, '_fields'):
                fields.extend(base._fields)
        seen = set([])
        for attrname, attrval in d.items():
            if isinstance(attrval, Field):
                if not attrval.name:
                    attrval.name = attrname
                if attrname in seen:
                    raise ValueError('duplicate field name: %r' % attrname)
                seen.add(attrname)
                fields.append((attrname, attrval))
        if '_fields' not in d:
            d['_fields'] = fields
        else:
            d['_fields'].extend(fields)
        return super(MetaMapping, mcs).__new__(mcs, name, bases, d)


_MappingProxy = MetaMapping('_MappingProxy', (object,), {}) # Python 3 workaround

class Mapping(_MappingProxy):

    def __init__(self, *args, **kwargs):
        fieldnames = map(itemgetter(0), self._fields)
        values = dict(izip_longest(fieldnames, args))
        values.update(kwargs)
        self._data = {}
        for attrname, field in self._fields:
            attrval = values.pop(attrname, None)
            if attrval is None:
                setattr(self, attrname, getattr(self, attrname))
            else:
                setattr(self, attrname, attrval)
        if values:
            raise ValueError('Unexpected kwargs found: %r' % values)

    @classmethod
    def build(cls, *a):
        d = {}
        fields = []
        for field in a:
            if field.name is None:
                raise ValueError('Name is required for ordered fields.')
            setattr(cls, field.name, field)
            fields.append((field.name, field))
        d['_fields'] = fields
        return type('Generic' + cls.__name__, (cls,), d)

    def __getitem__(self, key):
        return self.values()[key]

    def __setitem__(self, key, value):
        setattr(self, self._fields[key][0], value)

    def __delitem__(self, key):
        self._data[self._fields[key][0]] = None

    def __iter__(self):
        return iter(self.values())

    def __contains__(self, item):
        return item in self.values()

    def __len__(self):
        return len(self._data)

    def __eq__(self, other):
        if len(self) != len(other):
            return False
        for key, value in zip(self.keys(), other):
            if getattr(self, key) != value:
                return False
        return True

    def __ne__(self, other):
        return not (self == other)

    def __repr__(self):
        return '%s(%s)' % (self.__class__.__name__,
                           ', '.join('%s=%r' % (key, value)
                                     for key, value in self.items()))

    def keys(self):
        return [key for key, field in self._fields]

    def values(self):
        return [getattr(self, key) for key in self.keys()]

    def items(self):
        return zip(self.keys(), self.values())

    def to_astm_record(self):
        def values(obj):
            for key in obj.keys():
                value = obj._data[key]
                if isinstance(value, Mapping):
                    yield list(values(value))
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, Mapping):
                            yield list(values(item))
                        else:
                            yield item
                else:
                    yield value
        return list(values(self))


class Record(Mapping):
    """ASTM record mapping class."""


class Component(Mapping):
    """ASTM component mapping class."""


class TextField(Field):
    """Mapping field for string values."""
    def _set_value(self, value):
        if not isinstance(value, basestring):
            raise TypeError('String value expected, got %r' % value)
        return super(TextField, self)._set_value(value)


class ConstantField(Field):
    """Mapping field for constant values.

    >>> class Record(Mapping):
    ...     type = ConstantField(default='S')
    >>> rec = Record()
    >>> rec.type
    'S'
    >>> rec.type = 'W'
    Traceback (most recent call last):
        ...
    ValueError: Field changing not allowed
    """
    def __init__(self, name=None, default=None):
        if default is not None:
            assert isinstance(default, basestring)
        super(ConstantField, self).__init__(name, default)
        self.value = default

    def _get_value(self, value):
        return self.value

    def _set_value(self, value):
        if self.value is not None and self.value != value:
            raise ValueError('Field changing not allowed')
        elif self.value is None:
            self.value = value
        return super(ConstantField, self)._set_value(value)


class IntegerField(Field):
    """Mapping field for integer values."""
    def _get_value(self, value):
        return int(value)

    def _set_value(self, value):
        if not isinstance(value, (int, long)):
            raise TypeError('Integer value expected, got %r' % value)
        return super(IntegerField, self)._set_value(value)


class DecimalField(Field):
    """Mapping field for decimal values."""
    def _get_value(self, value):
        return decimal.Decimal(value)

    def _set_value(self, value):
        if not isinstance(value, (int, long, float, decimal.Decimal)):
            raise TypeError('Decimal value expected, got %r' % value)
        return super(DecimalField, self)._set_value(value)


class DateTimeField(Field):
    """Mapping field for storing date/time values."""
    def __init__(self, name=None, default=None, format='%Y%m%d%H%M%S'):
        self.format = format
        super(DateTimeField, self).__init__(name, default)

    def _get_value(self, value):
        return datetime.datetime.strptime(value, self.format)

    def _set_value(self, value):
        if not isinstance(value, (datetime.datetime, datetime.date)):
            raise TypeError('Datetime value expected, got %r' % value)
        return value.strftime(self.format)


class SetField(Field):
    """Mapping field for predefined set of values."""
    def __init__(self, name=None, default=None, values=None, field=Field()):
        super(SetField, self).__init__(name, default)
        self.field = field
        self.values = values and set(values) or set([])

    def _get_value(self, value):
        return self.field._get_value(value)

    def _set_value(self, value):
        if value not in self.values:
            raise ValueError('Unexpectable value %r' % value)
        return self.field._set_value(value)


class ComponentField(Field):
    """Mapping field for storing record component."""
    def __init__(self, mapping, name=None, default=None):
        self.mapping = mapping
        default = default or mapping()
        super(ComponentField, self).__init__(name, default)


    def _get_value(self, value):
        if isinstance(value, dict):
            return self.mapping(**value)
        elif isinstance(value, self.mapping):
            return value
        else:
            return self.mapping(*value)

    def _set_value(self, value):
        if isinstance(value, dict):
            return self.mapping(**value)
        elif isinstance(value, self.mapping):
            return value
        elif isinstance(value, basestring):
            raise TypeError('String values are not allowed to be components.')
        else:
            return self.mapping(*value)


class RepeatedComponentField(Field):
    """Mapping field for storing list of record components."""
    def __init__(self, field, name=None, default=None):
        if isinstance(field, ComponentField):
            self.field = field
        else:
            assert isinstance(field, type) and issubclass(field, Mapping)
            self.field = ComponentField(field)
        default = default or []
        super(RepeatedComponentField, self).__init__(name, default)

    class Proxy(list):
        def __init__(self, seq, field):
            list.__init__(self, seq)
            self.list = seq
            self.field = field

        def _to_list(self):
            return [list(self.field._get_value(item)) for item in self.list]

        def __add__(self, other):
            obj = type(self)(self.list, self.field)
            obj.extend(other)
            return obj

        def __iadd__(self, other):
            self.extend(other)
            return self

        def __mul__(self, other):
            return type(self)(self.list * other, self.field)

        def __imul__(self, other):
            self.list *= other
            return self

        def __lt__(self, other):
            return self._to_list() < other

        def __le__(self, other):
            return self._to_list() <= other

        def __eq__(self, other):
            return self._to_list() == other

        def __ne__(self, other):
            return self._to_list() != other

        def __ge__(self, other):
            return self._to_list() >= other

        def __gt__(self, other):
            return self._to_list() > other

        def __repr__(self):
            return '<ListProxy %s %r>' % (self.list, list(self))

        def __str__(self):
            return bytes(self.list)

        def __unicode__(self):
            return unicode(self.list)

        def __delitem__(self, index):
            del self.list[index]

        def __getitem__(self, index):
            return self.field._get_value(self.list[index])

        def __setitem__(self, index, value):
            self.list[index] = self.field._set_value(value)

        def __delslice__(self, i, j):
            del self.list[i:j]

        def __getslice__(self, i, j):
            return self.__class__(self.list[i:j], self.field)

        def __setslice__(self, i, j, seq):
            self.list[i:j] = [self.field._set_value(v) for v in seq]

        def __contains__(self, value):
            for item in self:
                if item == value:
                    return True
            return False

        def __iter__(self):
            for index in range(len(self)):
                yield self[index]

        def __len__(self):
            return len(self.list)

        def __nonzero__(self):
            return bool(self.list)

        def __reduce__(self):
            return self.list.__reduce__()

        def __reduce_ex__(self, *args, **kwargs):
            return self.list.__reduce_ex__(*args, **kwargs)

        def append(self, item):
            self.list.append(self.field._set_value(item))

        def count(self, value):
            return self._to_list().count(value)

        def extend(self, other):
            self.list.extend([self.field._set_value(i) for i in other])

        def index(self, value, start=None, stop=None):
            start = start or 0
            for idx, item in enumerate(islice(self, start, stop)):
                if item == value:
                    return idx + start
            else:
                raise ValueError('%r not in list' % value)

        def insert(self, index, object):
            self.list.insert(index, self.field._set_value(object))

        def remove(self, value):
            for item in self:
                if item == value:
                    return self.list.remove(value)
            raise ValueError('Value %r not in list' % value)

        def pop(self, index=-1):
            return self.field._get_value(self.list.pop(index))

        def sort(self, cmp=None, key=None, reverse=False):
            raise NotImplementedError('In place sorting not allowed.')

        # update docstrings from list
        for item in dir():
            if getattr(list, item, None) is None\
            or item in ['__module__', '__doc__']:
                continue
            func = eval(item)
            func.__doc__ = getattr(list, item).__doc__
        del func, item

    def _get_value(self, value):
        return self.Proxy(value, self.field)

    def _set_value(self, value):
        return [self.field._set_value(item) for item in value]
