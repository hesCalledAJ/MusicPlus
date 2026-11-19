from .compat import find_class, jclass
from .safe import tolerated

removed = set()

_EMPTY_MEDIA = ("TL_messageMediaEmpty", "TL_messageMediaUnsupported")


def _name(o):
    try:
        return str(o.getClass().getSimpleName())
    except Exception:
        return ""


def key_of(m):
    try:
        return (int(m.getId()), int(m.getDialogId()))
    except Exception:
        return None


def restricted_reason(reasons):
    try:
        for r in list(reasons or ()):
            if str(r.platform) in ("all", "android") and str(r.reason) != "sensitive":
                return True
    except Exception:
        pass
    return False


def gone(m):
    if m is None:
        return False
    k = key_of(m)
    if k is not None and k in removed:
        return True
    with tolerated():
        if bool(getattr(m, "isRestrictedMessage", False)):
            return True
    with tolerated():
        if restricted_reason(getattr(m.messageOwner, "restriction_reason", None)):
            return True
    with tolerated():
        media = m.messageOwner.media
        if media is not None and _name(media) in _EMPTY_MEDIA:
            return True
    doc = None
    with tolerated():
        doc = m.getDocument()
    if doc is None:
        return True
    return _name(doc).lower().endswith("documentempty")


def has_local_copy(m):
    want = 0
    with tolerated():
        doc = m.getDocument()
        want = int(doc.size) if doc is not None else 0

    def complete(f):
        try:
            if f is None or not bool(f.exists()):
                return False
            n = int(f.length())
            return n > 0 and (want <= 0 or n >= want)
        except Exception:
            return False
    with tolerated():
        FL = find_class("org.telegram.messenger.FileLoader")
        if complete(FL.getInstance(int(m.currentAccount)).getPathToMessage(m.messageOwner)):
            return True
    with tolerated():
        path = m.messageOwner.attachPath
        if path and str(path).strip() and complete(jclass("java.io.File")(str(path))):
            return True
    return False


def unavailable(m):
    return m is not None and gone(m) and not has_local_copy(m)
