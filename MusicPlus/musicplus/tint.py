import colorsys
import queue
import threading
import time

_state = {"c": None}

DUR_MS = 650
_TARGET_CONTRAST = 4.3
_LUM_MIN, _LUM_MAX = 0.14, 0.26
_SAT_MIN, _SAT_MAX = 0.38, 0.85
_NEUTRAL_SAT = 0.12
_ease = [None]
_dur = [None]
_FRAME_MIN, _FRAME_MAX = 0.008, 0.1
_JANK_GAP = 0.034

_GAP_BY_LVL = (0.008, 0.033, 0.05, 0.008)
_q = [0]
_q_floor = [0]
_streak = [0, 0]
_q_init = [False]


def _device_floor():
    try:
        from .compat import jclass
        sdk = int(jclass("android.os.Build$VERSION").SDK_INT)
        mem = int(jclass("java.lang.Runtime").getRuntime().maxMemory()) // (1024 * 1024)
        return 1 if (sdk <= 26 or mem <= 192) else 0
    except Exception:
        return 0


def quality():
    if not _q_init[0]:
        _q_init[0] = True
        _q_floor[0] = _q[0] = _device_floor()
    return _q[0]


_sys = [0.0, 0]


def _system_level():
    now = time.monotonic()
    if now - _sys[0] < 5.0:
        return _sys[1]
    _sys[0] = now
    lvl = 0
    try:
        from .compat import jclass
        try:
            lm = jclass("org.telegram.messenger.LiteMode")
            try:
                flag = int(lm.FLAG_ANIMATIONS)
                if not bool(lm.isEnabled(flag)):
                    lvl = 2
            except Exception:
                pass
            try:
                if lvl < 2 and bool(lm.isPowerSaverApplied()):
                    lvl = 2
            except Exception:
                pass
        except Exception:
            pass
        if lvl < 2:
            try:
                sc = jclass("org.telegram.messenger.SharedConfig")
                if int(sc.getDevicePerformanceClass()) == 0:
                    lvl = max(lvl, 1)
            except Exception:
                pass
            try:
                ctx = jclass("org.telegram.messenger.ApplicationLoader").applicationContext
                if bool(ctx.getSystemService("power").isPowerSaveMode()):
                    lvl = max(lvl, 1)
            except Exception:
                pass
    except Exception:
        pass
    _sys[1] = lvl
    return lvl


def queue_level(mode):
    if mode == 1:
        return 0
    if mode == 2:
        return 3
    return max(_system_level(), quality())


def report_run(n, drops, cost_s, calls):
    quality()
    if n < 6 or calls <= 0:
        return
    bad = drops / float(n) > 0.2 or cost_s / calls * 1000.0 > 12.0
    note_pressure(bad)


def note_pressure(bad):
    quality()
    if bad:
        _streak[0] += 1
        _streak[1] = 0
        if _streak[0] >= 2 and _q[0] < 2:
            _q[0] += 1
            _streak[0] = 0
    else:
        _streak[1] += 1
        _streak[0] = 0
        if _streak[1] >= 8 and _q[0] > _q_floor[0]:
            _q[0] -= 1
            _streak[1] = 0


def current():
    return _state["c"]


def set_dur(ms):
    _dur[0] = ms


def set_current(c):
    _state["c"] = c


def _lin(v):
    v = v / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def lum(c):
    c = int(c)
    return 0.2126 * _lin((c >> 16) & 255) + 0.7152 * _lin((c >> 8) & 255) + 0.0722 * _lin(c & 255)




def _pack(r, g, b):
    return (255 << 24 | (int(round(r * 255)) & 255) << 16 | (int(round(g * 255)) & 255) << 8
            | (int(round(b * 255)) & 255))


def _signed(argb):
    argb &= 0xFFFFFFFF
    return argb - (1 << 32) if argb & 0x80000000 else argb


def target_lum(bg):
    lb = lum(bg)
    want = (lb + 0.05) * _TARGET_CONTRAST - 0.05 if lb < 0.18 else (lb + 0.05) / _TARGET_CONTRAST - 0.05
    return max(_LUM_MIN, min(_LUM_MAX, want))


def fit(c, bg):
    c = int(c)
    h, l, s = colorsys.rgb_to_hls(((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0)
    if s >= _NEUTRAL_SAT:
        s = max(_SAT_MIN, min(_SAT_MAX, s))
    want = target_lum(bg)
    lo, hi = 0.0, 1.0
    for _ in range(14):
        mid = (lo + hi) / 2.0
        if lum(_pack(*colorsys.hls_to_rgb(h, mid, s))) < want:
            lo = mid
        else:
            hi = mid
    return _signed(_pack(*colorsys.hls_to_rgb(h, (lo + hi) / 2.0, s)))


_BINS = 24


def dominant(pixels):
    import colorsys
    px_list = []
    mass = [0.0] * _BINS
    for px in pixels:
        px = int(px) & 0xFFFFFFFF
        if ((px >> 24) & 255) < 200:
            continue
        r, g, b = (px >> 16) & 255, (px >> 8) & 255, px & 255
        mx, mn = max(r, g, b), min(r, g, b)
        sat = (mx - mn) / 255.0
        light = (mx + mn) / 510.0
        w = 0.02 + sat * sat * (1.0 - abs(2.0 * light - 1.0))
        h = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)[0]
        k = int(h * _BINS) % _BINS
        px_list.append((r, g, b, w, k))
        mass[k] += w
    if not px_list:
        return None
    score = [mass[k] + 0.5 * (mass[(k - 1) % _BINS] + mass[(k + 1) % _BINS]) for k in range(_BINS)]
    best = max(range(_BINS), key=score.__getitem__)
    sw = sr = sg = sb = 0.0
    for r, g, b, w, k in px_list:
        d = min((k - best) % _BINS, (best - k) % _BINS)
        if d <= 1:
            sw += w
            sr += r * w
            sg += g * w
            sb += b * w
    if sw <= 0:
        return None
    return _signed(_pack(sr / sw / 255.0, sg / sw / 255.0, sb / sw / 255.0))


_MISS = object()
_CACHE_MAX = 4
_lock = threading.Lock()
_cache = []
_jobs = {}
_work = queue.Queue()
_worker = [None]


def _compute(bmp, bg):
    try:
        from .compat import jarray, jclass, jint
        B = jclass("android.graphics.Bitmap")
        cfg = bmp.getConfig()
        src = bmp
        if cfg is None or str(cfg.name()) == "HARDWARE":
            src = bmp.copy(jclass("android.graphics.Bitmap$Config").ARGB_8888, False)
            if src is None:
                return None
        if int(src.getWidth()) > 64:
            src = B.createScaledBitmap(src, 64, 64, True)
        small = B.createScaledBitmap(src, 16, 16, True)
        arr = jarray(jint)(256)
        small.getPixels(arr, 0, 16, 0, 0, 16, 16)
        c = dominant(list(arr))
        return fit(c, bg) if c is not None else None
    except Exception:
        return None


def get(bmp, bg):
    with _lock:
        for b, g, res in reversed(_cache):
            if b is bmp and g == bg:
                return True, res
    return False, None


def pending(bmp, bg):
    with _lock:
        return (id(bmp), bg) in _jobs


def request(bmp, bg):
    key = (id(bmp), bg)
    with _lock:
        if key in _jobs or any(b is bmp and g == bg for b, g, _r in _cache):
            return
        _jobs[key] = (bmp, bg)
        if _worker[0] is None or not _worker[0].is_alive():
            _worker[0] = threading.Thread(target=_loop, daemon=True, name="smq-tint")
            _worker[0].start()
        _work.put(key)


def _loop():
    while True:
        try:
            key = _work.get(timeout=30)
        except queue.Empty:
            with _lock:
                if _work.empty():
                    _worker[0] = None
                    return
            continue
        with _lock:
            job = _jobs.get(key)
        if job is None:
            continue
        bmp, bg = job
        res = _compute(bmp, bg)
        with _lock:
            _cache.append((bmp, bg, res))
            del _cache[:-_CACHE_MAX]
            _jobs.pop(key, None)




def ease(va):
    try:
        if _ease[0] is None:
            from .android import _cls
            _ease[0] = _cls("android.view.animation.AccelerateDecelerateInterpolator")()
        va.setInterpolator(_ease[0])
    except Exception:
        pass
    va.setDuration(int(_dur[0] or DUR_MS))
    return va


def throttled(fn, floor=_FRAME_MIN):
    st = [0.0, floor]
    r = [None, 0, 0, 0.0, 0]

    def run(f):
        now = time.monotonic()
        if r[0] is not None:
            r[1] += 1
            if now - r[0] > _JANK_GAP:
                r[2] += 1
        r[0] = now
        if f < 0.999 and now - st[0] < st[1]:
            return
        fn(f)
        end = time.monotonic()
        st[0] = end
        st[1] = max(floor, min(_FRAME_MAX, (end - now) * 2.0))
        r[3] += end - now
        r[4] += 1
        if f >= 0.999:
            report_run(r[1], r[2], r[3], r[4])
            r[0], r[1], r[2], r[3], r[4] = None, 0, 0, 0.0, 0
    return run
