from typing import Any, Optional

from .compat import find_class, jclass
from .safe import tolerated

_MISSING = object()


def jcls(name: str) -> Optional[Any]:
    cls = find_class(name)
    if cls is None:
        return None
    if hasattr(cls, "getDeclaredMethod"):
        return cls
    for attr in ("class_", "__javaclass__"):
        with tolerated():
            value = getattr(cls, attr)
            if hasattr(value, "getDeclaredMethod"):
                return value
    with tolerated():
        loader = jclass("org.telegram.messenger.ApplicationLoader").applicationContext.getClassLoader()
        return jclass("java.lang.Class").forName(name, True, loader)
    return None


def _read_declared(cls: Any, name: str, obj: Any) -> Any:
    with tolerated():
        handle = cls.getDeclaredField(name)
        handle.setAccessible(True)
        return handle.get(obj)
    return _MISSING


def field(obj: Any, name: str) -> Any:
    cls = obj.getClass()
    while cls is not None:
        value = _read_declared(cls, name, obj)
        if value is not _MISSING:
            return value
        cls = cls.getSuperclass()
    return None


def _find_method(obj: Any, name: str, argc: int) -> Optional[Any]:
    cls = obj.getClass()
    while cls is not None:
        for method in cls.getDeclaredMethods():
            if method.getName() == name and method.getParameterCount() == argc:
                return method
        cls = cls.getSuperclass()
    return None


def invoke(obj: Any, name: str, *args: Any) -> Any:
    try:
        return getattr(obj, name)(*args)
    except Exception as first:
        method = _find_method(obj, name, len(args))
        if method is None:
            raise first
        method.setAccessible(True)
        return method.invoke(obj, *args)


_SYS = []


def identity_hash(obj: Any) -> int:
    if not _SYS:
        _SYS.append(jclass("java.lang.System"))
    return int(_SYS[0].identityHashCode(obj))
