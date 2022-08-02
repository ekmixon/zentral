import base64
import itertools
import json
import logging
import os
import re
import time
from .buckets import get_bucket_client
from .params import get_param_client
from .secrets import get_secret_client


logger = logging.getLogger("zentral.conf.config")


class Proxy:
    pass


class EnvProxy(Proxy):
    def __init__(self, name):
        self._name = name

    def get(self):
        return os.environ[self._name]


class ResolverMethodProxy(Proxy):
    def __init__(self, resolver, proxy_type, key):
        if proxy_type == "file":
            self._method = resolver.get_file_content
        elif proxy_type == "param":
            self._method = resolver.get_parameter_value
        elif proxy_type == "secret":
            self._method = resolver.get_secret_value
        elif proxy_type == "bucket_file":
            self._method = resolver.get_bucket_file
        else:
            raise ValueError("Unknown proxy type %s", proxy_type)
        self._key = key

    def get(self):
        return self._method(self._key)


class JSONDecodeFilter(Proxy):
    def __init__(self, child_proxy):
        self._child_proxy = child_proxy

    def get(self):
        return json.loads(self._child_proxy.get())


class Base64DecodeFilter(Proxy):
    def __init__(self, child_proxy):
        self._child_proxy = child_proxy

    def get(self):
        return base64.b64decode(self._child_proxy.get())


class ElementFilter(Proxy):
    def __init__(self, key, child_proxy):
        try:
            self._key = int(key)
        except ValueError:
            self._key = key
        self._child_proxy = child_proxy

    def get(self):
        return self._child_proxy.get()[self._key]


class Resolver:
    def __init__(self):
        self._cache = {}
        self._bucket_client = None
        self._param_client = None
        self._secret_client = None

    def _get_or_create_cached_value(self, key, getter, ttl=None):
        # happy path
        try:
            expiry, value = self._cache[key]
        except KeyError:
            pass
        else:
            if expiry is None or time.time() < expiry:
                logger.debug("Key %s from cache", key)
                return value
            logger.debug("Cache for key %s has expired", key)

        # get value
        value = getter()
        expiry = time.time() + ttl if ttl else None
        self._cache[key] = (expiry, value)
        logger.debug("Set cache for key %s", key)

        return value

    def get_file_content(self, filepath):
        cache_key = ("FILE", filepath)

        def getter():
            with open(filepath, "r") as f:
                return f.read()

        return self._get_or_create_cached_value(cache_key, getter)

    def get_secret_value(self, name):
        cache_key = ("SECRET", name)
        if not self._secret_client:
            self._secret_client = get_secret_client()

        def getter():
            return self._secret_client.get(name)

        return self._get_or_create_cached_value(cache_key, getter, ttl=600)

    def get_bucket_file(self, key):
        cache_key = ("BUCKET_FILE", key)
        if not self._bucket_client:
            self._bucket_client = get_bucket_client()

        def getter():
            return self._bucket_client.download_to_tmpfile(key)

        return self._get_or_create_cached_value(cache_key, getter)

    def get_parameter_value(self, key):
        cache_key = ("PARAM", key)
        if not self._param_client:
            self._param_client = get_param_client()

        def getter():
            return self._param_client.get(key)

        return self._get_or_create_cached_value(cache_key, getter, ttl=600)


class BaseConfig:
    PROXY_VAR_RE = re.compile(
        r"^\{\{\s*"
        r"(?P<type>bucket_file|env|file|param|secret)\:(?P<key>[^\}\|]+)"
        r"(?P<filters>(\s*\|\s*(jsondecode|base64decode|element:[a-zA-Z_\-/0-9]+))*)"
        r"\s*\}\}$"
    )
    custom_classes = {}

    def __init__(self, path=None, resolver=None):
        self._path = path or ()
        if not resolver:
            resolver = Resolver()
        self._resolver = resolver

    def _make_proxy(self, key, match):
        proxy_type = match.group("type")
        key = match.group("key").strip()
        if proxy_type == "env":
            proxy = EnvProxy(key)
        else:
            proxy = ResolverMethodProxy(self._resolver, proxy_type, key)
        filters = [f for f in [rf.strip() for rf in match.group("filters").split("|")] if f]
        for filter_name in filters:
            if filter_name == "jsondecode":
                proxy = JSONDecodeFilter(proxy)
            elif filter_name == "base64decode":
                proxy = Base64DecodeFilter(proxy)
            elif filter_name.startswith("element:"):
                key = filter_name.split(":", 1)[-1]
                proxy = ElementFilter(key, proxy)
            else:
                raise ValueError("Unknown filter %s", filter_name)
        return proxy

    def _from_python(self, key, value):
        new_path = self._path + (key,)
        if isinstance(value, dict):
            value = self.custom_classes.get(new_path, ConfigDict)(value, new_path)
        elif isinstance(value, list):
            value = self.custom_classes.get(new_path, ConfigList)(value, new_path)
        elif isinstance(value, str):
            if match := self.PROXY_VAR_RE.match(value):
                value = self._make_proxy(key, match)
        return value

    def _to_python(self, value):
        return value.get() if isinstance(value, Proxy) else value

    def __len__(self):
        return len(self._collection)

    def __delitem__(self, key):
        del self._collection[key]

    def __setitem__(self, key, value):
        self._collection[key] = self._from_python(key, value)

    def pop(self, key, default=None):
        value = self._collection.pop(key, default)
        if isinstance(value, Proxy):
            value = value.get()
        return value


class ConfigList(BaseConfig):
    def __init__(self, config_l, path=None, resolver=None):
        super().__init__(path=path, resolver=resolver)
        self._collection = [
            self._from_python(str(key), value)
            for key, value in enumerate(config_l)
        ]

    def __getitem__(self, key):
        value = self._collection[key]
        if isinstance(key, slice):
            slice_repr = ":".join(str("" if i is None else i) for i in (key.start, key.stop, key.step))
            logger.debug("Get /%s[%s] config key", "/".join(self._path), slice_repr)
            return [self._to_python(item) for item in value]
        else:
            logger.debug("Get /%s[%s] config key", "/".join(self._path), key)
            return self._to_python(value)

    def __iter__(self):
        for element in self._collection:
            yield self._to_python(element)

    def serialize(self):
        s = []
        for v in self:
            if isinstance(v, BaseConfig):
                v = v.serialize()
            s.append(v)
        return s


class ConfigDict(BaseConfig):
    def __init__(self, config_d, path=None, resolver=None):
        super().__init__(path=path, resolver=resolver)
        self._collection = {}
        for key, value in config_d.items():
            self._collection[key] = self._from_python(key, value)

    def __getitem__(self, key):
        logger.debug("Get /%s config key", "/".join(self._path + (key,)))
        value = self._collection[key]
        return self._to_python(value)

    def get(self, key, default=None):
        try:
            value = self[key]
        except KeyError:
            value = self._to_python(default)
        return value

    def __iter__(self):
        yield from self._collection

    def keys(self):
        return self._collection.keys()

    def values(self):
        for value in self._collection.values():
            yield self._to_python(value)

    def items(self):
        for key, value in self._collection.items():
            yield key, self._to_python(value)

    def clear(self):
        return self._collection.clear()

    def setdefault(self, key, default=None):
        return self._collection.setdefault(key, self._from_python(key, default))

    def pop(self, key, default=None):
        value = self._collection.pop(key, default)
        return self._to_python(value)

    def popitem(self):
        key, value = self._collection.popitem()
        return key, self._to_python(value)

    def copy(self):
        return ConfigDict(self._collection.copy(), path=self._path, resolver=self._resolver)

    def update(self, *args, **kwargs):
        chain = []
        for arg in args:
            iterator = arg.items() if isinstance(arg, dict) else arg
            chain = itertools.chain(chain, iterator)
        if kwargs:
            chain = itertools.chain(chain, kwargs.items())
        for key, value in iterator:
            self._collection[key] = self._from_python(key, value)

    def serialize(self):
        s = {}
        for k, v in self.items():
            if isinstance(v, BaseConfig):
                v = v.serialize()
            s[k] = v
        return s
