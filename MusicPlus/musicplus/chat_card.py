import time

from .compat import MethodHook, find_class, jclass, jfloat, jint
from . import reflect
from .android import _mix
from .helpers import _argb
from .safe import tolerated

_AUDIO = "org.telegram.ui.Cells.ChatMessageAudio"
_CELL = "org.telegram.ui.Cells.ChatMessageCell"
_BTN = 28
_GAP = 6
_NEED_EXTRA = 173
_MIN_W = 220

_F = {}


def _field(obj, name):
    k = (int(obj.getClass().hashCode()), name)
    f = _F.get(k)
    if f is None:
        cls = obj.getClass()
        while cls is not None and f is None:
            with tolerated():
                f = cls.getDeclaredField(name)
                f.setAccessible(True)
            if f is None:
                cls = cls.getSuperclass()
        _F[k] = f if f is not None else False
    return f or None


def _fld(obj, name):
    f = _field(obj, name)
    return None if f is None else f.get(obj)


def reflect_field(obj, name):
    return _field(obj, name)


_AU = []


class _Paints:
    def __init__(self, ctx):
        self.d = float(ctx.getResources().getDisplayMetrics().density)
        P = jclass("android.graphics.Paint")
        self.Style = jclass("android.graphics.Paint$Style")
        self.fill = P(1)
        self.line = P(1)
        self.line.setStrokeCap(jclass("android.graphics.Paint$Cap").ROUND)
        self.line.setStrokeJoin(jclass("android.graphics.Paint$Join").ROUND)
        self.rect = jclass("android.graphics.RectF")()
        self.path = jclass("android.graphics.Path")()
        self.Picture = jclass("android.graphics.Picture")

    def dp(self, v):
        return self.d * v

    def solid(self, c):
        self.fill.setStyle(self.Style.FILL)
        self.fill.setColor(jint(int(c)))

    def stroke(self, w, c):
        self.line.setStyle(self.Style.STROKE)
        self.line.setStrokeWidth(self.dp(w))
        self.line.setColor(jint(int(c)))


class _Card:
    def __init__(self, plugin):
        self.p = plugin
        self.g = None
        self.theme = None
        self.colors = {}
        self.pics = {}
        self.hits = {}
        self.down = {}
        self.bounce = {}
        self.legacy = False
        self._cfg_c = None
        self._nt = {}


    def install(self):
        audio, cell = find_class(_AUDIO), find_class(_CELL)
        if cell is None:
            return False
        self.legacy = audio is None
        me = self

        class After(MethodHook):
            def after_hooked_method(self, param):
                try:
                    a = param.args
                    me.draw_buttons(param.thisObject, a[0], a[1] if len(a) > 2 else 0, a[2] if len(a) > 2 else 0)
                except Exception as e:
                    me.fail("draw_buttons", e)

        class Content(MethodHook):
            def after_hooked_method(self, param):
                try:
                    me.narrow_title(param.thisObject, param.args[0], None, True)
                except Exception as e:
                    me.fail("narrow_title", e)

        class Layouts(MethodHook):
            def after_hooked_method(self, param):
                try:
                    a = param.args
                    m = a[1] if len(a) > 1 else None
                    if m is None or int(a[0]) <= 0 or not bool(m.isMusic()):
                        return
                    cell = param.thisObject
                    owner = cell if me.legacy else _fld(cell, "audio")
                    if owner is not None:
                        me.narrow_title(owner, m, int(a[0]) if not me.legacy else None)
                except Exception as e:
                    me.fail("narrow_title", e)

        class Touch(MethodHook):
            def before_hooked_method(self, param):
                with tolerated():
                    if me.touch(param.thisObject, param.args[0]):
                        param.setResult(True)

        if self.legacy:
            plan = ((cell, "drawContent", After), (cell, "createDocumentLayout", Layouts),
                    (cell, "setMessageObject", Content), (cell, "onTouchEvent", Touch))
        else:
            plan = ((audio, "drawMusic", After), (cell, "createDocumentLayout", Layouts),
                    (audio, "setMusicContent", Content), (cell, "onTouchEvent", Touch))
        ok = False
        for cls, name, h in plan:
            with tolerated():
                u = self.p.hook_all_methods(cls, name, h())
                if u:
                    self.p._hooks.extend(u if isinstance(u, list) else [u])
                    ok = True
        return ok

    def _rec(self, key, w, h, paint):
        pic = self.pics.get(key)
        if pic is None:
            if len(self.pics) > 96:
                self.pics.clear()
            pic = self.g.Picture()
            c = pic.beginRecording(int(w), int(h))
            try:
                paint(c)
            finally:
                pic.endRecording()
            self.pics[key] = pic
        return pic

    def fail(self, where, e):
        if getattr(self, "_failed", False):
            return
        self._failed = True
        with tolerated():
            from . import crashlog
            crashlog.crumb(f"music card {where}: {type(e).__name__}: {str(e)[:80]}")

    def stop(self):
        self.hits.clear()
        self.down.clear()
        self.pics.clear()
        self.bounce.clear()
        self.colors.clear()


    def _cell(self, owner):
        if self.legacy:
            return owner if int(_fld(owner, "documentAttachType")) == 5 else None
        return _fld(owner, "cell")

    def _xy(self, owner, bx, by):
        if self.legacy:
            return float(_fld(owner, "buttonX")), float(_fld(owner, "buttonY"))
        return float(bx), float(by)

    def _cfg(self):
        now = time.monotonic()
        c = self._cfg_c
        if c is None or now - c[0] > 1.0:
            gs = self.p.get_setting
            c = self._cfg_c = (now, bool(gs("chat_music_card", True)), True)
        return c

    def _on(self):
        return self._cfg()[1]

    def _gfx(self, cell):
        if self.g is None:
            self.g = _Paints(cell.getContext())
            self.theme = find_class("org.telegram.ui.ActionBar.Theme")
        return self.g

    def _pal(self, cell, out):
        now = time.monotonic()
        c = self.colors.get(out)
        if c is not None and now - c[0] < 1.0:
            return c
        T = self.theme
        pre = "key_chat_out" if out else "key_chat_in"

        def col(name, fb):
            with tolerated():
                return int(cell.getThemedColor(int(getattr(T, name))))
            return fb

        bubble = col(pre + "Bubble", _argb(255, 255, 255, 255))
        acc = col(pre + "AudioProgress", _argb(255, 42, 139, 234))
        sub = col(pre + "AudioPerformerText", _mix(bubble, acc, 0.5))
        c = (now, bubble, acc, sub)
        self.colors[out] = c
        return c

    def _geo(self, cell, buttonX, buttonY, g):
        bl = int(cell.getBackgroundDrawableLeft())
        br = int(cell.getBackgroundDrawableRight())
        if br - bl < g.dp(_MIN_W):
            return None
        l = max(bl + g.dp(4), buttonX - g.dp(10))
        r = br - g.dp(5)
        t = buttonY - g.dp(13) + g.dp(5)
        return l, t, r, t + g.dp(66)


    def draw_buttons(self, audio, canvas, bx, by):
        if not self._on():
            return
        cell = self._cell(audio)
        if cell is None:
            return
        m = _fld(cell, "currentMessageObject")
        if m is None:
            return
        g = self._gfx(cell)
        bx, by = self._xy(audio, bx, by)
        geo = self._geo(cell, bx, by, g)
        key = reflect.identity_hash(cell)
        if geo is None:
            self.hits.pop(key, None)
            return
        l, t, r, b = geo
        out = bool(m.isOutOwner())
        mid, did = int(m.getId()), int(m.getDialogId())
        _, bubble, acc, sub = self._pal(cell, out)
        liked = (mid, did) in self.p._liked_keys()
        pressed = self.down.get(key)
        s, gap = g.dp(_BTN), g.dp(_GAP)
        px = r - g.dp(8) - s
        hx = px - gap - s
        y = t + g.dp(4)
        now = time.monotonic() * 1000.0
        if pressed is None and (key, "like") not in self.bounce and (key, "plus") not in self.bounce:
            hcol = acc if liked and not out else sub

            def paint(c):
                self._heart(c, g, s / 2.0, s / 2.0, hcol, liked)
                self._dots(c, g, s + gap + s / 2.0, s / 2.0, sub)
            pic = self._rec(("b", liked, hcol, sub, g.d), int(2 * s + gap) + 1, int(s) + 1, paint)
            canvas.save()
            canvas.translate(float(hx), float(y))
            canvas.drawPicture(pic)
            canvas.restore()
            self.hits[key] = {"like": (hx, y, hx + s, y + s), "plus": (px, y, px + s, y + s),
                              "id": (mid, did)}
            return
        busy = False
        for x, which in ((hx, "like"), (px, "plus")):
            cx, cy = x + s / 2.0, y + s / 2.0
            k = self._scale(key, which, now, pressed == which)
            busy = busy or (key, which) in self.bounce
            if pressed == which:
                g.solid(_argb(52, (acc >> 16) & 255, (acc >> 8) & 255, acc & 255))
                canvas.drawCircle(float(cx), float(cy), float(s / 2.0), g.fill)
            canvas.save()
            canvas.scale(float(k), float(k), float(cx), float(cy))
            if which == "like":
                self._heart(canvas, g, cx, cy, acc if liked and not out else sub, liked)
            else:
                self._dots(canvas, g, cx, cy, sub)
            canvas.restore()
        self.hits[key] = {"like": (hx, y, hx + s, y + s), "plus": (px, y, px + s, y + s),
                          "id": (mid, did)}
        if busy:
            with tolerated():
                cell.postInvalidateOnAnimation()


    def _kick(self, key, which, strong):
        now = time.monotonic() * 1000.0
        self.bounce[(key, which)] = (now, 0.55, 420.0, 4.0) if strong else (now, 0.78, 320.0, 3.0)

    def _scale(self, key, which, now, held):
        if held:
            return 0.86
        a = self.bounce.get((key, which))
        if a is None:
            return 1.0
        t0, frm, dur, ten = a
        e = (now - t0) / dur
        if e >= 1.0:
            self.bounce.pop((key, which), None)
            return 1.0
        e -= 1.0
        return frm + (1.0 - frm) * (e * e * ((ten + 1.0) * e + ten) + 1.0)


    @staticmethod
    def _heart(c, g, cx, cy, color, filled):
        k = 0.85 * g.d
        p = g.path
        p.reset()
        p.moveTo(0.0, 8.6 * k)
        p.cubicTo(-7.0 * k, 3.2 * k, -9.4 * k, -0.4 * k, -9.4 * k, -3.6 * k)
        p.cubicTo(-9.4 * k, -6.4 * k, -7.3 * k, -8.4 * k, -4.8 * k, -8.4 * k)
        p.cubicTo(-2.8 * k, -8.4 * k, -1.0 * k, -7.3 * k, 0.0, -5.4 * k)
        p.cubicTo(1.0 * k, -7.3 * k, 2.8 * k, -8.4 * k, 4.8 * k, -8.4 * k)
        p.cubicTo(7.3 * k, -8.4 * k, 9.4 * k, -6.4 * k, 9.4 * k, -3.6 * k)
        p.cubicTo(9.4 * k, -0.4 * k, 7.0 * k, 3.2 * k, 0.0, 8.6 * k)
        p.close()
        c.save()
        c.translate(float(cx), float(cy + g.dp(0.4)))
        if filled:
            g.solid(color)
            c.drawPath(p, g.fill)
        else:
            g.stroke(1.9, color)
            c.drawPath(p, g.line)
        c.restore()

    @staticmethod
    def _dots(c, g, cx, cy, color):
        g.solid(color)
        r, step = g.dp(2.0), g.dp(5.6)
        for i in (-1, 0, 1):
            c.drawCircle(float(cx), float(cy + i * step), float(r), g.fill)


    def _max_bubble(self, cell, g):
        side = 0
        with tolerated():
            if bool(cell.needDrawAvatar()):
                side = int(g.dp(52))
        pw = 0
        with tolerated():
            pw = int(cell.getParentWidth())
        if pw <= 0:
            pw = int(cell.getContext().getResources().getDisplayMetrics().widthPixels)
        cap = pw - int(g.dp(50)) - side
        with tolerated():
            if not _AU:
                au = find_class("org.telegram.messenger.AndroidUtilities")
                _AU.extend((au, bool(au.isTablet())))
            if _AU[1]:
                cap = min(cap, int(_AU[0].getMinTabletSide()) - int(g.dp(50)) - side)
        return cap

    @staticmethod
    def _layout(text, paint, width):
        SL = jclass("android.text.StaticLayout")
        with tolerated():
            bld = jclass("android.text.StaticLayout$Builder").obtain(text, 0, int(text.length()), paint, int(width))
            return bld.setAlignment(jclass("android.text.Layout$Alignment").ALIGN_NORMAL).setMaxLines(1).build()
        return SL(text, paint, int(width), jclass("android.text.Layout$Alignment").ALIGN_NORMAL,
                  jfloat(1.0), jfloat(0.0), False)

    def narrow_title(self, owner, m, cap=None, fallback=False):
        _, on, override = self._cfg()
        if not on or m is None:
            return
        if self.legacy:
            m = _fld(owner, "currentMessageObject") or m
        cell = self._cell(owner)
        if cell is None:
            return
        g = self._gfx(cell)
        lay = _fld(owner, "songLayout")
        bgw = int(_fld(cell, "backgroundWidth"))
        if lay is None or bgw < g.dp(_MIN_W):
            return
        nk, mh = reflect.identity_hash(owner), reflect.identity_hash(m)
        if fallback and self._nt.get(nk) == (mh, bgw):
            return
        paint = self.theme.chat_audioTitlePaint
        title = str(m.getMusicTitle()).replace("\n", " ")
        wt = int(jclass("java.lang.Math").ceil(float(paint.measureText(title))))
        extra = int(g.dp(_NEED_EXTRA))
        grow = 0
        if override and wt + extra > bgw:
            limit = int(cap) if cap else self._max_bubble(cell, g)
            grow = max(0, min(wt + extra - bgw, limit - bgw))
        if grow > 0:
            f = reflect_field(cell, "backgroundWidth")
            f.setInt(cell, bgw + grow)
            bgw += grow
            for name in ("availableTimeWidth", "widthBeforeNewTimeLine"):
                a = reflect_field(cell, name)
                if a is not None:
                    a.setInt(cell, int(a.getInt(cell)) + grow)
        avail = bgw - extra
        if len(self._nt) > 256:
            self._nt.clear()
        self._nt[nk] = (mh, bgw)
        if wt <= avail or avail < g.dp(60):
            return
        ell = jclass("android.text.TextUtils").ellipsize(
            title, paint, jfloat(avail), jclass("android.text.TextUtils$TruncateAt").END)
        new = self._layout(ell, paint, avail)
        reflect_field(owner, "songLayout").set(owner, new)
        if int(new.getLineCount()) > 0:
            fx = reflect_field(owner, "songX")
            if fx is not None:
                fx.setInt(owner, -int(jclass("java.lang.Math").ceil(float(new.getLineLeft(0)))))


    @staticmethod
    def _in(rc, x, y, slop):
        return rc[0] - slop <= x <= rc[2] + slop and rc[1] - slop <= y <= rc[3] + slop

    def touch(self, cell, ev):
        if not self._on() or self.g is None:
            return False
        key = reflect.identity_hash(cell)
        h = self.hits.get(key)
        if h is None:
            return False
        m = _fld(cell, "currentMessageObject")
        if m is None or (int(m.getId()), int(m.getDialogId())) != h["id"]:
            self.hits.pop(key, None)
            self.down.pop(key, None)
            return False
        act = int(ev.getActionMasked())
        x, y = float(ev.getX()), float(ev.getY())
        slop = self.g.dp(6)
        hit = "like" if self._in(h["like"], x, y, slop) else ("plus" if self._in(h["plus"], x, y, slop) else None)
        if act == 0:
            if hit is None:
                return False
            self.down[key] = hit
            cell.invalidate()
            return True
        pressed = self.down.get(key)
        if pressed is None:
            return False
        if act == 2:
            if hit != pressed:
                self.down.pop(key, None)
                cell.invalidate()
            return True
        self.down.pop(key, None)
        cell.invalidate()
        if act == 1 and hit == pressed:
            self._act(cell, pressed, m)
        return True

    def _act(self, cell, which, m):
        self._kick(reflect.identity_hash(cell), which, which == "like")
        if which == "like":
            self.p._toggle_track_liked(m)
            with tolerated():
                cell.performHapticFeedback(1)
            cell.invalidate()
        else:
            self.p._safe_message_actions({"message": m})
