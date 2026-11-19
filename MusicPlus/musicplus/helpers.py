from elyx import strings
from .compat import find_class, jclass
from .safe import tolerated

_PLUGIN_REF = {"plugin": None}


def mem_tight(limit=0.8):
    try:
        rt = jclass("java.lang.Runtime").getRuntime()
        used = float(rt.totalMemory()) - float(rt.freeMemory())
        return used > float(rt.maxMemory()) * limit
    except Exception:
        return False


def trim_caches(*dicts, keep=20):
    for d in dicts:
        with tolerated():
            while len(d) > keep:
                d.pop(next(iter(d)), None)
_SYS_PLAYLISTS = {"Liked Songs": "liked_songs", "Downloaded Songs": "downloaded_songs", "Profile Playlist": "profile_playlist"}


def _pln(name):
    name = str(name)
    return strings(_SYS_PLAYLISTS[name]) if name in _SYS_PLAYLISTS else name


def _deep_tuple(v):
    return tuple(_deep_tuple(x) for x in v) if isinstance(v, (list, tuple)) else v


def _fmt_time(sec) -> str:
    try:
        sec = max(0, int(sec))
    except Exception:
        sec = 0
    return f"{sec // 60}:{sec % 60:02d}"


def _signed(v: int) -> int:
    return v - (1 << 32) if v >= (1 << 31) else v


def _argb(a, r, g, b) -> int:
    return _signed((a << 24) | (r << 16) | (g << 8) | b)


_RD_IDX = None


def _rd_index():
    global _RD_IDX
    if _RD_IDX is None:
        _RD_IDX = {}
        with tolerated():
            RD = find_class("org.telegram.messenger.R$drawable")
            for f in RD.getFields():
                with tolerated():
                    _RD_IDX[str(f.getName())] = int(f.getInt(None))
    return _RD_IDX


_LIB_DYN = {"downloaded": ("msg_download", "menu_download_24"), "profile": ("filled_track_add", "msg_profile")}
_PROFILE_MUSIC_ICON = None
_PROFILE_MUSIC_GUESSES = (
 "msg_profile_music", "msg_music_profile", "profile_music", "msg_saved_music",
 "menu_profile_music", "msg_add_profile_music", "msg_savedmusic", "profile_saved_music",
 )


def _profile_music_icons():
    global _PROFILE_MUSIC_ICON
    if _PROFILE_MUSIC_ICON is not None:
        return _PROFILE_MUSIC_ICON
    found = []
    try:
        idx = _rd_index()
        found = [n for n in _PROFILE_MUSIC_GUESSES if n in idx]
        if not found:
            hits = [n for n in idx
          if "music" in n.lower() and ("profile" in n.lower() or "saved" in n.lower())]
            hits.sort(key=lambda n: (not n.startswith("msg"), len(n), n))
            found = hits[:4]
    except Exception:
        found = []
    _PROFILE_MUSIC_ICON = tuple(found) + ("msg_profile", "msg_music")
    return _PROFILE_MUSIC_ICON


def _tl_resolve(*names):
    for n in names:
        with tolerated():
            c = find_class("org.telegram.tgnet.TLRPC$" + n)
            if c is not None:
                return c
    with tolerated():
        from org.telegram.tgnet import TLRPC
        for attr in dir(TLRPC):
            low = attr.lower()
            for n in names:
                if n.lower() == low or (not n.startswith("TL_") and low.endswith(n.lower())
             and "byid" not in low and "notmodified" not in low):
                    c = getattr(TLRPC, attr, None)
                    if c is not None and callable(c):
                        return c
    with tolerated():
        from org.telegram.tgnet import tl as tg_tl
        for mod_name in dir(tg_tl):
            mod = getattr(tg_tl, mod_name, None)
            if mod is None:
                continue
            for n in names:
                c = getattr(mod, n, None)
                if c is not None:
                    return c
                short = n.split("_", 2)[-1]
                c = getattr(mod, short, None)
                if c is not None and callable(c):
                    return c
    return None


def _pm_list(obj):
    if obj is None:
        return []
    with tolerated():
        return list(obj)
    try:
        return [obj.get(i) for i in range(int(obj.size()))]
    except Exception:
        return []


def _http_stream(url):
    conn = jclass("java.net.URL")(url).openConnection()
    conn.setConnectTimeout(8000)
    conn.setReadTimeout(8000)
    conn.setRequestProperty("User-Agent", "Mozilla/5.0")
    return conn.getInputStream()


def _http_text(url):
    stream = _http_stream(url)
    try:
        sc = jclass("java.util.Scanner")(stream, "UTF-8").useDelimiter("\\A")
        return str(sc.next()) if sc.hasNext() else ""
    finally:
        stream.close()
