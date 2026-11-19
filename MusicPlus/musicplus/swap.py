from .android import _cls
from .compat import jarray, jint
from .safe import tolerated

OUT_MS = 100
IN_MS = 200
POP_MS = 260
_gen = {}
_base = {}
_color_anim = {}
_decel = [None]


def _interp():
    if _decel[0] is None:
        _decel[0] = _cls("android.view.animation.DecelerateInterpolator")(1.6)
    return _decel[0]


def _rest_color(tv, key):
    cur = int(tv.getCurrentTextColor()) & 0xFFFFFFFF
    base = _base.get(key)
    if base is None or (cur & 0xFFFFFF) != (base & 0xFFFFFF):
        base = cur | 0xFF000000 if (cur >> 24) == 0 else cur
        _base[key] = base
    return base


def _signed(c):
    c &= 0xFFFFFFFF
    return c - (1 << 32) if c & 0x80000000 else c


def _fade(tv, key, to_c, ms, interp=None):
    old = _color_anim.pop(key, None)
    if old is not None:
        with tolerated():
            old.cancel()
    cur = int(tv.getCurrentTextColor())
    an = _cls("android.animation.ObjectAnimator").ofArgb(
        tv, "textColor", jarray(jint)([jint(cur), jint(_signed(to_c))]))
    an.setDuration(int(ms))
    if interp is not None:
        an.setInterpolator(interp)
    _color_anim[key] = an
    an.start()


def _settle(tv, key, base):
    old = _color_anim.pop(key, None)
    if old is not None:
        with tolerated():
            old.cancel()
    with tolerated():
        tv.setTextColor(_signed(base))
        tv.setAlpha(1.0)
        tv.setTranslationX(0.0)


def swap_text(tv, apply, shift_px, direction, run, animate=True):
    key = id(tv)
    g = _gen[key] = _gen.get(key, 0) + 1
    with tolerated():
        tv.animate().cancel()
    base = None
    with tolerated():
        base = _rest_color(tv, key)
    ok = False
    if animate and base is not None:
        with tolerated():
            ok = int(tv.getVisibility()) == 0 and int(tv.getWidth()) > 0
    if not ok:
        apply()
        if base is not None:
            _settle(tv, key, base)
        else:
            with tolerated():
                tv.setAlpha(1.0)
                tv.setTranslationX(0.0)
        return
    d = 1.0 if direction >= 0 else -1.0
    shift_px = int(round(shift_px))

    def back():
        if _gen.get(key) != g:
            return
        apply()
        with tolerated():
            tv.setTextColor(_signed(base & 0x00FFFFFF))
            tv.setTranslationX(float(d * shift_px))
            tv.animate().translationX(0.0).setDuration(IN_MS).setInterpolator(_interp()).start()
            _fade(tv, key, base, IN_MS, _interp())

    try:
        tv.animate().translationX(float(-d * shift_px)).setDuration(OUT_MS).withEndAction(run(back)).start()
        _fade(tv, key, base & 0x00FFFFFF, OUT_MS)
    except Exception:
        apply()
        _settle(tv, key, base)


def pop_in(v):
    with tolerated():
        v.animate().cancel()
        v.setAlpha(0.0)
        v.setScaleX(0.86)
        v.setScaleY(0.86)
        v.animate().alpha(1.0).scaleX(1.0).scaleY(1.0).setDuration(POP_MS).setInterpolator(_interp()).start()
