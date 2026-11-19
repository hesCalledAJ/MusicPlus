from .compat import dynamic_proxy, jarray, jclass, jint
from .helpers import _argb
from .safe import tolerated


_PROXIES = None
_HOLD_MS = 600


def _proxies():
    global _PROXIES
    if _PROXIES is not None:
        return _PROXIES
    OnTouch = jclass("android.view.View$OnTouchListener")
    OnClick = jclass("android.view.View$OnClickListener")
    Runnable = jclass("java.lang.Runnable")
    class Touch(dynamic_proxy(OnTouch)):
        def __init__(self, fn):
            super().__init__()
            self.fn = fn
        def onTouch(self, v, event):
            try:
                return bool(self.fn(v, event))
            except Exception:
                return False
    class Click(dynamic_proxy(OnClick)):
        def __init__(self, fn):
            super().__init__()
            self.fn = fn
        def onClick(self, v):
            with tolerated():
                self.fn(v)
    class Run(dynamic_proxy(Runnable)):
        def __init__(self, fn):
            super().__init__()
            self.fn = fn
        def run(self):
            with tolerated():
                self.fn()
    _PROXIES = (Touch, Click, Run)
    return _PROXIES


def _cv_put_int(values, key, n):
    with tolerated():
        values.put(key, jint(n))
        return
    values.put(key, str(int(n)))


def _mediastore_save(ctx, kind, display, mime, write_fn, folder="Music +", extra=None):
    api = int(jclass("android.os.Build$VERSION").SDK_INT)
    if api < 29:
        raise RuntimeError("needs Android 10+")
    values = jclass("android.content.ContentValues")()
    if kind == "audio":
        coll, base = jclass("android.provider.MediaStore$Audio$Media"), "Music"
    else:
        coll, base = jclass("android.provider.MediaStore$Images$Media"), "Pictures"
    values.put("_display_name", str(display))
    values.put("mime_type", str(mime))
    values.put("relative_path", f"{base}/{folder}")
    for k, v in (extra or {}).items():
        if v:
            values.put(str(k), str(v))
    _cv_put_int(values, "is_pending", 1)
    resolver = ctx.getContentResolver()
    uri = resolver.insert(coll.EXTERNAL_CONTENT_URI, values)
    if uri is None:
        raise RuntimeError("MediaStore refused the file")
    try:
        stream = resolver.openOutputStream(uri, "w")
        if stream is None:
            raise RuntimeError("couldn't open output")
        try:
            write_fn(stream)
            stream.flush()
        finally:
            stream.close()
        done = jclass("android.content.ContentValues")()
        _cv_put_int(done, "is_pending", 0)
        resolver.update(uri, done, None, None)
    except Exception:
        with tolerated():
            resolver.delete(uri, None, None)
        raise
    return uri


def _legacy_public_save(ctx, base, display, write_fn, folder="Music +"):
    Env = jclass("android.os.Environment")
    d = jclass("java.io.File")(Env.getExternalStoragePublicDirectory(base), folder)
    d.mkdirs()
    dest = jclass("java.io.File")(d, str(display))
    out = jclass("java.io.FileOutputStream")(dest)
    try:
        write_fn(out)
        out.flush()
    finally:
        out.close()
    with tolerated():
        _cls("android.media.MediaScannerConnection").scanFile(
       ctx, jarray(jclass("java.lang.String"))([str(dest.getAbsolutePath())]), None, None)
    return dest


_CLS = {}


def _cls(name):
    c = _CLS.get(name)
    if c is None:
        c = _CLS[name] = jclass(name)
    return c


def _wide_px(act, cap_dp):
    dm = act.getResources().getDisplayMetrics()
    w = int(dm.widthPixels)
    return min(w, int(cap_dp * dm.density)) if w > 560 * dm.density else 0


def _mix(c1, c2, t):
    def ch(c, sh):
        return (int(c) >> sh) & 255
    return _argb(255, *[int(ch(c1, sh) * (1 - t) + ch(c2, sh) * t) for sh in (16, 8, 0)])


_PIN_ICONS = ("msg_pin", "msg_pin_filled", "menu_pin", "input_pin")
_UNPIN_ICONS = ("msg_unpin", "msg_pin", "menu_unpin")
_LISTENERS = {}


def _proxy(iface, method, adapt=lambda *a: a, ret=False):
    c = _LISTENERS.get((iface, method))
    if c is None:
        def handler(self, *a):
            try:
                r = self.fn(*adapt(*a))
                return bool(r) if ret else None
            except Exception:
                return False if ret else None

        handler.__name__ = method

        class L(dynamic_proxy(jclass(iface))):
            def __init__(self, fn):
                super().__init__()
                self.fn = fn

            locals()[method] = handler

        c = _LISTENERS[(iface, method)] = L
    return c


def _viewlong_proxy():
    return _proxy("android.view.View$OnLongClickListener", "onLongClick", ret=True)


def _scrollchg_proxy():
    return _proxy("android.view.View$OnScrollChangeListener", "onScrollChange", lambda *a: ())


def _layoutchg_proxy():
    return _proxy("android.view.View$OnLayoutChangeListener", "onLayoutChange", lambda *a: ())


def _key_proxy():
    return _proxy("android.content.DialogInterface$OnKeyListener", "onKey",
    lambda d, code, ev: (int(code), ev), ret=True)


def _backcb_proxy():
    return _proxy("android.window.OnBackInvokedCallback", "onBackInvoked")


def _dismiss_proxy():
    return _proxy("android.content.DialogInterface$OnDismissListener", "onDismiss")


def _anim_proxy():
    return _proxy("android.animation.ValueAnimator$AnimatorUpdateListener", "onAnimationUpdate",
    lambda a: (float(a.getAnimatedFraction()),))


_SEEK = None


def _seek_proxy():
    global _SEEK
    if _SEEK is None:
        Listener = jclass("android.widget.SeekBar$OnSeekBarChangeListener")
        class Seek(dynamic_proxy(Listener)):
            def __init__(self, fn):
                super().__init__()
                self.fn = fn
            def onProgressChanged(self, sb, progress, from_user):
                if from_user:
                    self._call("change", int(progress))
            def onStartTrackingTouch(self, sb):
                self._call("start", None)
            def onStopTrackingTouch(self, sb):
                self._call("stop", None)
            def _call(self, kind, val):
                with tolerated():
                    self.fn(kind, val)
        _SEEK = Seek
    return _SEEK
