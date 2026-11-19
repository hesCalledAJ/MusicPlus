from .compat import (
 Boolean,
 Selector,
 dynamic_proxy,
 find_class,
 jarray,
 jclass,
 jfloat,
 jint,
)
from .helpers import _PLUGIN_REF
from .helpers import _signed
from .android import _anim_proxy, _cls, _mix
from .safe import tolerated


_WCB = None


def _selector_sub(**kw):
    try:
        return Selector(**kw)
    except TypeError:
        kw.pop("subtext", None)
        return Selector(**kw)


def _hit(v, x, y):
    try:
        if not bool(v.isShown()):
            return False
        loc = jarray(jint)(2)
        v.getLocationOnScreen(loc)
        return int(loc[0]) <= x < int(loc[0]) + int(v.getWidth()) and int(loc[1]) <= y < int(loc[1]) + int(v.getHeight())
    except Exception:
        return False


def _window_hook(dialog, on_touch):
    global _WCB
    win = dialog.getWindow()
    orig = win.getCallback()
    if _WCB is None:
        IH = jclass("java.lang.reflect.InvocationHandler")
        class WinCb(dynamic_proxy(IH)):
            def __init__(self, target, fn):
                super().__init__()
                self.target = target
                self.fn = fn
            def invoke(self, proxy, method, args):
                name = str(method.getName())
                try:
                    if name == "dispatchTouchEvent":
                        try:
                            r = self.fn(self.target, args[0])
                        except Exception:
                            r = None
                        if r is None:
                            r = self.target.dispatchTouchEvent(args[0])
                        return Boolean.valueOf(bool(r))
                    if args is None:
                        return method.invoke(self.target)
                    return method.invoke(self.target, *args)
                except Exception:
                    with tolerated():
                        if str(method.getReturnType().getName()) == "boolean":
                            return Boolean.FALSE
                    return None
        _WCB = WinCb
    Cls = jclass("java.lang.Class")
    cb = Cls.forName("android.view.Window$Callback")
    proxy = jclass("java.lang.reflect.Proxy").newProxyInstance(
    dialog.getContext().getClassLoader(), jarray(Cls)([cb]), _WCB(orig, on_touch))
    win.setCallback(proxy)
    return proxy


class _PillRow:
    DUR = 0.30
    def __init__(self, ed, pill, cells, labels):
        self.ed, self.pill, self.cells, self.labels = ed, pill, cells, labels
        self.x = self.w = None
        self.run = None
    def geom(self, i):
        c = self.cells[i]
        return float(c.getLeft()), float(c.getWidth())
    def apply(self, x, w):
        ed, pill = self.ed, self.pill
        lp = pill.getLayoutParams()
        wi = int(round(w))
        if int(lp.width) != wi:
            lp.width = wi
            pill.setLayoutParams(lp)
        pill.setTranslationX(float(x))
        self.x, self.w = float(x), float(w)
        for c, tv in zip(self.cells, self.labels):
            cw = float(c.getWidth())
            if cw <= 0:
                continue
            cx = float(c.getLeft())
            ov = max(0.0, min(x + w, cx + cw) - max(x, cx)) / cw
            acc = getattr(ed, "_tab_accent", None)
            tv.setTextColor(_mix(ed.c_sub, ed.c_accent if acc is None else acc, max(0.0, min(1.0, ov))))
    def recolor(self):
        if self.x is not None:
            with tolerated():
                self.apply(self.x, self.w)
    def cancel(self):
        tok, self.run = self.run, None
        with tolerated():
            a = tok.get("anim") if isinstance(tok, dict) else None
            if a is not None:
                a.cancel()
    def set(self, i, attempt=0, prev=None, then=None):
        with tolerated():
            if self.run is not None:
                return
            x, w = self.geom(i)
            if w <= 0:
                if attempt < 25:
                    self.pill.setVisibility(4)
                    self.ed.handler.postDelayed(
                self.ed.Run(lambda: self.set(i, attempt + 1, prev, then)), 30)
                return
            self.pill.setVisibility(0)
            if prev is not None and (abs(prev[0] - x) > 0.5 or abs(prev[1] - w) > 0.5):
                self.apply(prev[0], prev[1])
                if then is not None:
                    then()
                self.slide(i)
            else:
                self.apply(x, w)
                if then is not None:
                    then()
    def slide(self, i, on_frame=None, on_end=None):
        self.cancel()
        try:
            x1, w1 = self.geom(i)
            if w1 <= 0 or self.x is None:
                self.set(i)
                if on_frame:
                    on_frame(1.0)
                if on_end:
                    on_end()
                return
            x0, w0 = self.x, self.w
            tok = {}
            self.run = tok
            VA = _cls("android.animation.ValueAnimator")
            anim = VA.ofFloat(jarray(jfloat)([0.0, 1.0])) if jfloat else VA.ofFloat(0.0, 1.0)
            anim.setDuration(int(self.DUR * 1000))
            with tolerated():
                anim.setInterpolator(_cls("android.view.animation.PathInterpolator")(0.33, 1.0, 0.68, 1.0))
            def upd(f):
                if self.run is not tok:
                    return
                with tolerated():
                    self.apply(x0 + (x1 - x0) * f, w0 + (w1 - w0) * f)
                    if on_frame:
                        on_frame(f)
                if f >= 1.0:
                    self.run = None
                    if on_end:
                        on_end()
            anim.addUpdateListener(_anim_proxy()(upd))
            tok["anim"] = anim
            anim.start()
        except Exception:
            self.run = None
            if on_end:
                on_end()


_GLASS_CLS = None
_GLASS_SEEN = set()


def _glass_note(stage, e=None):
    return None


def _jcls(name):
    try:
        return jclass(name)
    except Exception:
        return find_class(name)


def _glass_follow_on():
    with tolerated():
        pl = _PLUGIN_REF.get("plugin")
        if pl is not None:
            return bool(pl.get_setting("glass_follow_tg", True))
    return True


def _glass_flags():
    if not _glass_follow_on():
        return (False, False)
    try:
        sdk = int(jclass("android.os.Build$VERSION").SDK_INT)
        if sdk < 31:
            return (False, False)
        blur = bool(_jcls("org.telegram.messenger.SharedConfig").chatBlurEnabled())
        if blur:
            try:
                uc = _jcls("org.telegram.messenger.UserConfig")
                pi = _jcls("org.telegram.ui.Components.blur3.drawable.color.impl.BlurredBackgroundProviderImpl")
                blur = bool(pi.checkBlurEnabled(int(uc.selectedAccount), None))
            except Exception as e:
                _glass_note("checkBlurEnabled", e)
        if not blur:
            return (False, False)
        lm = _jcls("org.telegram.messenger.LiteMode")
        try:
            flag = int(lm.FLAG_LIQUID_GLASS)
        except Exception:
            flag = 1 << 18
        liq = bool(sdk >= 33 and lm.isEnabled(flag))
        if ("mode", liq) not in _GLASS_SEEN:
            _GLASS_SEEN.add(("mode", liq))
            _glass_note("mode sdk=" + str(sdk) + " flag=" + str(flag) + " liquid=" + str(liq))
        return (True, liq)
    except Exception as e:
        _glass_note("flags", e)
        return (False, False)


def _glass_classes():
    global _GLASS_CLS
    if _GLASS_CLS is not None:
        return _GLASS_CLS or None
    try:
        b3 = "org.telegram.ui.Components.blur3."
        C = {
       "Sup": _jcls(b3 + "DownscaleScrollableNoiseSuppressor"),
       "Src": _jcls(b3 + "source.BlurredBackgroundSourceRenderNode"),
       "RectF": jclass("android.graphics.RectF"),
       }
        I_render = _jcls(b3 + "RenderNodeWithHash$Renderer")
        I_capture = _jcls(b3 + "capture.IBlur3Capture")
        I_prov = _jcls(b3 + "drawable.color.BlurredBackgroundProvider")
        I_pre = jclass("android.view.ViewTreeObserver$OnPreDrawListener")
        I_att = jclass("android.view.View$OnAttachStateChangeListener")
        class Renderer(dynamic_proxy(I_render)):
            def __init__(self, draw, calc):
                super().__init__()
                self.draw, self.calc = draw, calc
            def renderNodeUpdateDisplayList(self, canvas):
                try:
                    self.draw(canvas)
                except Exception as e:
                    _glass_note("render", e)
            def renderNodeCalculateHash(self, h):
                try:
                    self.calc(h)
                except Exception:
                    h.unsupported()
        class Capture(dynamic_proxy(I_capture)):
            def __init__(self, cap, calc):
                super().__init__()
                self.cap, self.calc = cap, calc
            def capture(self, canvas, pos):
                try:
                    self.cap(canvas, pos)
                except Exception as e:
                    _glass_note("capture", e)
            def captureCalculateHash(self, h, pos):
                try:
                    self.calc(h, pos)
                except Exception:
                    h.unsupported()
        class Provider(dynamic_proxy(I_prov)):
            def __init__(self, v):
                super().__init__()
                self.v = v
            def getBackgroundColor(self):
                return self.v["bg"]()
            def getShadowColor(self):
                return self.v.get("sh_color", 0)
            def getStrokeColorTop(self):
                return self.v["top"]
            def getStrokeColorBottom(self):
                return self.v["bottom"]
            def getStrokeWidthTop(self):
                return float(self.v["w_top"])
            def getStrokeWidthBottom(self):
                return float(self.v["w_bottom"])
            def isShadowAlwaysVisible(self):
                return False
            def getShadowRadius(self):
                return float(self.v.get("sh_r", 0.0))
            def getShadowDx(self):
                return 0.0
            def getShadowDy(self):
                return float(self.v.get("sh_dy", 0.0))
        class PreDraw(dynamic_proxy(I_pre)):
            def __init__(self, fn):
                super().__init__()
                self.fn = fn
            def onPreDraw(self):
                with tolerated():
                    self.fn()
                return True
        class Attach(dynamic_proxy(I_att)):
            def __init__(self, on, off):
                super().__init__()
                self.on, self.off = on, off
            def onViewAttachedToWindow(self, v):
                with tolerated():
                    self.on()
            def onViewDetachedFromWindow(self, v):
                with tolerated():
                    self.off()
        C.update(Renderer=Renderer, Capture=Capture, Provider=Provider, PreDraw=PreDraw, Attach=Attach)
        _GLASS_CLS = C
    except Exception as e:
        _glass_note("classes", e)
        _GLASS_CLS = False
    return _GLASS_CLS or None


class _SheetGlass:
    def __init__(self, act, root, c_bg):
        self.act, self.root, self.c_bg = act, root, int(c_bg)
        self.d = float(act.getResources().getDisplayMetrics().density)
        self.mode = None
        self.broken = False
        self.attached = False
        self.parts = None
        self.surfaces = []
        self.glued = []
        self.stage = None
        self.pages = []
        self.lib_sv = self.lib_page = self.lib_detail = None
        self.tick = 0
        self.ver = 0
        self.sig = None
        self.ov = None
        self.force = False
        self.fades = None
        self.fade_key = None
        self.failed = False
        self.insets = []
        self.top_solid = False
        self.flat = False
        self.flat_cb = None
        try:
            C = _glass_classes()
            if C is None:
                self.broken = True
                return
            self.C = C
            self.pre = C["PreDraw"](self._update)
            self.attach_l = C["Attach"](self._on_attach, self._on_detach)
            root.addOnAttachStateChangeListener(self.attach_l)
            if root.isAttachedToWindow():
                self._on_attach()
        except Exception as e:
            _glass_note("init", e)
            self.broken = True
    def _on_attach(self):
        if self.attached or self.broken:
            return
        self.attached = True
        with tolerated():
            self.root.getViewTreeObserver().addOnPreDrawListener(self.pre)
        self.tick = 0
        self._apply(_glass_flags())
        self.force = True
        self.ov = None
        for sf in self.surfaces:
            sf["ox"] = sf["oy"] = None
    def _on_detach(self):
        if not self.attached:
            return
        self.attached = False
        with tolerated():
            self.root.getViewTreeObserver().removeOnPreDrawListener(self.pre)
    def set_flat_cb(self, cb):
        self.flat_cb = cb
        if self.flat:
            self._flat(True, True)
    def _flat(self, on, force=False):
        on = bool(on)
        if on == self.flat and not force:
            return
        self.flat = on
        if self.flat_cb is not None:
            try:
                self.flat_cb(on)
            except Exception as e:
                _glass_note("flat", e)
    def _apply(self, mode):
        if self.broken or mode == self.mode:
            return
        self.mode = mode
        for sf in self.surfaces:
            self._surface_off(sf)
        self.parts = None
        self.ov = None
        self.sig = None
        self._overlap(0, 0)
        if not mode[0] or self.failed:
            self._flat(True)
            return
        try:
            self._attach_parts()
        except Exception as e:
            _glass_note("build", e)
            self._detach_parts()
    def _attach_parts(self):
        self.parts = {"rects": jclass("java.util.ArrayList")(), "rect": self.C["RectF"]()}
        self._build_source()
        for sf in self.surfaces:
            self._surface_on(sf)
        self._flat(True)
    def _detach_parts(self):
        self.parts = None
        self.failed = True
        for sf in self.surfaces:
            self._surface_off(sf)
        self._flat(True)
    def set_layout(self, stage, pages, lib_sv=None, lib_page=None, lib_detail=None):
        self.stage, self.pages = stage, [x for x in pages if x is not None]
        self.lib_sv, self.lib_page, self.lib_detail = lib_sv, lib_page, lib_detail
    def add_inset(self, view):
        lp = view.getLayoutParams()
        self.insets.append((view, int(lp.bottomMargin)))
    def add_spacer(self, view):
        if view is not None:
            self.glued.append(view)
    def add_surface(self, view, radius, color, alpha, fill=None):
        if view is None:
            return
        try:
            orig = view.getBackground()
            view.setOutlineProvider(None)
            view.setTranslationZ(0.01)
        except Exception:
            orig = None
        sf = {"v": view, "r": float(radius), "color": int(color), "alpha": float(alpha), "orig": orig,
       "fill": fill, "drw": None, "ox": None, "oy": None, "layered": False}
        self.surfaces.append(sf)
        self.glued.append(view)
        if self.parts is not None:
            self._surface_on(sf)
    def _build_source(self):
        C, root, me = self.C, self.root, self
        sup, src = C["Sup"](), C["Src"](None)
        def draw(canvas):
            canvas.drawColor(jint(me.c_bg))
            sup.draw(canvas, -2)
        def calc(h):
            h.add(me.c_bg)
            h.add(1 if me.mode and me.mode[1] else 0)
        src.setupRenderer(C["Renderer"](draw, calc))
        def cap(canvas, pos):
            canvas.drawColor(jint(me.c_bg))
            st = me.stage
            if st is not None and st.getWidth() > 0:
                canvas.save()
                canvas.translate(float(st.getLeft()), float(st.getTop() + st.getTranslationY()))
                st.draw(canvas)
                canvas.restore()
        def cap_hash(h, pos):
            h.add(me.ver)
            h.add(root.getWidth())
            h.add(root.getHeight())
        self.parts.update(sup=sup, src=src, capture=C["Capture"](cap, cap_hash))
    def _surface_on(self, sf):
        if self.parts is None or "src" not in self.parts:
            return
        C, d = self.C, self.d
        liq = bool(self.mode and self.mode[1])
        a8 = int(round((0.85 if liq else 0.76) * 255))
        col = _signed((a8 << 24) | (sf["color"] & 0xFFFFFF))
        c = self.c_bg
        dark = (0.299 * ((c >> 16) & 255) + 0.587 * ((c >> 8) & 255) + 0.114 * (c & 255)) < 128
        prov = C["Provider"]({"bg": lambda: col,
       "top": _signed(0x06FFFFFF if dark else 0x11000000), "bottom": _signed(0x11FFFFFF if dark else 0x20000000),
       "w_top": 0.4 * d, "w_bottom": 0.4 * d,
       "sh_color": _signed(0x04FFFFFF if dark else 0x20000000), "sh_r": 2.667 * d, "sh_dy": 0.85 * d})
        drw = self.parts["src"].createDrawable()
        if self.mode and self.mode[1]:
            drw.setLiquidGlassEffectAllowed()
        drw.setColorProvider(prov)
        r = sf["r"]
        drw.setRadius(r, r, r, r, False)
        sf["drw"], sf["prov"], sf["ox"], sf["oy"] = drw, prov, None, None
        v, o = sf["v"], sf["orig"]
        sf["layered"] = bool(o is not None and str(o.getClass().getName()) == "android.graphics.drawable.LayerDrawable")
        if sf["layered"]:
            if sf.get("card") is None:
                sf["card"] = o.getDrawable(0)
            o.setDrawable(0, drw)
            with tolerated():
                sf["fill"].setAlpha(110)
        else:
            self._pad_bg(v, drw)
    def _surface_off(self, sf):
        if sf["drw"] is None:
            return
        with tolerated():
            o = sf["orig"]
            if sf["layered"]:
                o.setDrawable(0, sf["card"] if sf.get("card") is not None else o.getDrawable(0))
                with tolerated():
                    sf["fill"].setAlpha(255)
            else:
                self._pad_bg(sf["v"], o)
        sf["drw"] = None
    def _pad_bg(self, v, drawable):
        with tolerated():
            pl, pt, pr, pb = int(v.getPaddingLeft()), int(v.getPaddingTop()), int(v.getPaddingRight()), int(v.getPaddingBottom())
            v.setBackground(drawable)
            v.setPadding(pl, pt, pr, pb)
    def _run(self, up):
        root, tot = self.root, 0
        n = int(root.getChildCount())
        i = int(root.indexOfChild(self.stage)) + (-1 if up else 1)
        while 0 <= i < n:
            ch = root.getChildAt(i)
            if int(ch.getVisibility()) != 8:
                if not any(ch.equals(v) for v in self.glued):
                    break
                lp = ch.getLayoutParams()
                tot += int(ch.getHeight()) + int(lp.topMargin) + int(lp.bottomMargin)
            i += -1 if up else 1
        return tot
    def _gap(self, up):
        root = self.root
        n = int(root.getChildCount())
        i = int(root.indexOfChild(self.stage)) + (-1 if up else 1)
        while 0 <= i < n:
            ch = root.getChildAt(i)
            if int(ch.getVisibility()) != 8:
                lp = ch.getLayoutParams()
                return int(lp.bottomMargin if up else lp.topMargin)
            i += -1 if up else 1
        return 0
    def _fade(self, top, bot):
        st = self.stage
        want = self.parts is None and self.flat
        w, h = int(st.getWidth()), int(st.getHeight())
        gt, gb = self._gap(True), self._gap(False)
        x0, x1 = -int(st.getLeft()), int(self.root.getWidth()) - int(st.getLeft())
        key = (want, w, h, top, bot, gt, gb, x0, x1)
        if key == self.fade_key:
            return
        self.fade_key = key
        ov = st.getOverlay()
        if self.fades is None:
            GD = jclass("android.graphics.drawable.GradientDrawable")
            OR = jclass("android.graphics.drawable.GradientDrawable$Orientation")
            CD = jclass("android.graphics.drawable.ColorDrawable")
            c = self.c_bg & 0xFFFFFF
            clear, solid = _signed(c), _signed(0xFF000000 | c)
            self.fades = [GD(OR.TOP_BOTTOM, jarray(jint)([clear, solid])), CD(solid),
          GD(OR.BOTTOM_TOP, jarray(jint)([clear, solid])), CD(solid)]
        for d in self.fades:
            with tolerated():
                ov.remove(d)
        if not want or w <= 0 or h <= 0:
            return
        f = int(round(28 * self.d))
        m = int(round(4 * self.d))
        b = self.fades
        if bot > 0:
            e = min(h + gb + m + int(round(14 * self.d)), h + bot)
            b[0].setBounds(x0, h - f, x1, e)
            b[1].setBounds(x0, e, x1, h + bot)
            ov.add(b[0])
            ov.add(b[1])
        if top > 0:
            e = -gt - m
            b[2].setBounds(x0, e, x1, f)
            b[3].setBounds(x0, -top, x1, e)
            ov.add(b[2])
            ov.add(b[3])
    def _overlap(self, top, bot):
        st = self.stage
        if st is None:
            return
        with tolerated():
            for i in range(int(st.getChildCount())):
                lp = st.getChildAt(i).getLayoutParams()
                if int(lp.topMargin) != -top or int(lp.bottomMargin) != -bot:
                    lp.topMargin, lp.bottomMargin = -top, -bot
                    st.getChildAt(i).setLayoutParams(lp)
            lift = int(round(28 * self.d)) if bot > 0 and self.parts is None and self.flat else 0
            for v, base in self.insets:
                lp = v.getLayoutParams()
                if int(lp.bottomMargin) != base + bot + lift:
                    lp.bottomMargin = base + bot + lift
                    v.setLayoutParams(lp)
            det = self.lib_detail is not None and int(self.lib_detail.getVisibility()) == 0
            pbot = bot + lift
            for pg in self.pages:
                self._set_pad(pg, top, pbot)
            if self.lib_sv is not None:
                self._set_pad(self.lib_sv, 0 if det else top, pbot)
                if self.lib_page is not None:
                    self.lib_page.setPadding(0, int(top if det else 0), 0, 0)
                    self.lib_page.setClipToPadding(False)
    def _set_pad(self, v, top, bot):
        if v is not None and (int(v.getPaddingTop()) != top or int(v.getPaddingBottom()) != bot):
            v.setClipToPadding(False)
            v.setPadding(int(v.getPaddingLeft()), int(top), int(v.getPaddingRight()), int(bot))
    def _update(self):
        try:
            self._update_impl()
        except Exception as e:
            _glass_note("update", e)
    def _update_impl(self):
        if self.broken:
            return
        self.tick += 1
        if self.tick % 30 == 1:
            flags = _glass_flags()
            if flags != self.mode:
                self._apply(flags)
        p, st, root = self.parts, self.stage, self.root
        if st is None:
            return
        dims = (0 if self.top_solid else self._run(True), self._run(False))
        if dims != self.ov:
            self.ov = dims
            self._overlap(*dims)
        try:
            self._fade(*dims)
        except Exception as e:
            _glass_note("fade", e)
        if p is None:
            return
        w, h = int(root.getWidth()), int(root.getHeight())
        if w <= 0 or h <= 0:
            return
        n = int(st.getChildCount())
        sig = (w, h, tuple(int(x.getScrollY()) for x in self.pages), int(st.getHeight()),
       tuple((int(st.getChildAt(i).getTranslationX()), int(st.getChildAt(i).getVisibility())) for i in range(n)))
        changed = sig != self.sig
        if changed or self.tick % 20 == 0 or self.force:
            self.force = False
            if changed or self.tick % 20 == 0:
                self.sig = sig
                self.ver += 1
            rect, rects = p["rect"], p["rects"]
            rect.set(0.0, 0.0, float(w), float(h))
            rects.clear()
            rects.add(rect)
            p["sup"].setupRenderNodes(rects, 1)
            p["sup"].invalidateResultRenderNodes(p["capture"], w, h)
            p["src"].setSize(w, h)
            p["src"].updateDisplayListIfNeeded()
        for sf in self.surfaces:
            if sf["drw"] is None:
                continue
            v = sf["v"]
            ox, oy = float(v.getLeft() + v.getTranslationX()), float(v.getTop() + v.getTranslationY())
            if ox != sf["ox"] or oy != sf["oy"]:
                sf["ox"], sf["oy"] = ox, oy
                sf["drw"].setSourceOffset(ox, oy)
                v.invalidate()


def _sheet_glass(act, root, c_bg):
    try:
        return _SheetGlass(act, root, c_bg)
    except Exception:
        return None


class _SheetDrag:
    def __init__(self, owner, scrolls, top_y, can_start, can_up, begin, move, end):
        self.o = owner
        self.scrolls = scrolls
        self.top_y = top_y
        self.can_start = can_start
        self.can_up = can_up
        self.begin = begin
        self.move = move
        self.end = end
        self.slop = int(jclass("android.view.ViewConfiguration").get(owner.act).getScaledTouchSlop())
        self.g = None
    def _under(self, x, y):
        out = []
        for v in self.scrolls():
            if _hit(v, x, y):
                out.append(v)
        return out
    @staticmethod
    def _scroller(g, direction):
        for v in g["under"]:
            with tolerated():
                if v.canScrollVertically(direction):
                    return v
        return None
    def _cancel_children(self, target, ev):
        with tolerated():
            c = _cls("android.view.MotionEvent").obtain(ev)
            c.setAction(3)
            target.dispatchTouchEvent(c)
            c.recycle()
    def _first(self):
        try:
            return bool(self.o.p.get_setting("sheet_expand_first", False))
        except Exception:
            return False
    def _apply(self, g, dy):
        if g.get("own") == "sheet":
            self.move(dy)
            g["last"] = "sheet"
            return
        if dy < 0:
            sv = self._scroller(g, 1)
            defer_expand = False
            if not self._first() and sv is None:
                try:
                    callback = getattr(self.o, "_sd_defer_expand", None)
                    defer_expand = bool(callback()) if callback is not None else False
                except Exception:
                    defer_expand = False
            if self._first() or (sv is None and not defer_expand):
                if self.can_up():
                    self.move(dy)
                    g["last"] = g["own"] = "sheet"
                    return
        else:
            sv = self._scroller(g, -1)
        if sv is not None:
            g["rem"] -= dy
            n = int(g["rem"])
            if n:
                g["rem"] -= n
                sv.scrollBy(0, n)
            g["last"] = "scroll"
            g["sv"] = sv
        elif dy > 0:
            self.move(dy)
            g["last"] = g["own"] = "sheet"
    def on_touch(self, target, ev):
        a = int(ev.getActionMasked())
        if a == 0:
            self.g = None
            with tolerated():
                skip = getattr(self.o, "_sd_skip", None)
                if skip is not None and skip(ev):
                    return None
            if float(ev.getY()) < self.top_y() or not self.can_start():
                return None
            self.o.sheet_lock = False
            rx, ry = float(ev.getRawX()), float(ev.getRawY())
            self.g = {"x0": rx, "y0": ry, "ly": ry, "t": int(ev.getEventTime()),
          "t0": int(ev.getEventTime()), "v": 0.0,
          "claimed": False, "rem": 0.0, "last": None, "sv": None,
          "under": self._under(rx, ry)}
            return None
        g = self.g
        if g is None or a == 4:
            return None
        if a == 5 and not g["claimed"]:
            self.g = None
            return None
        if a not in (1, 2, 3):
            return True if g["claimed"] else None
        rx, ry = float(ev.getRawX()), float(ev.getRawY())
        t = int(ev.getEventTime())
        dy = ry - g["ly"]
        if a == 2:
            g["v"] = 0.5 * g["v"] + 0.5 * dy / max(1, t - g["t"]) * 1000.0
        g["ly"], g["t"] = ry, t
        if not g["claimed"]:
            if a != 2:
                self.g = None
                return None
            total = ry - g["y0"]
            if abs(total) < self.slop or abs(total) < abs(rx - g["x0"]) or dy == 0:
                return None
            if dy > 0:
                if self._scroller(g, -1) is not None:
                    return None
            elif not self.can_up():
                return None
            elif not self._first():
                upward_scroller = self._scroller(g, 1)
                if upward_scroller is not None:
                    return None
                with tolerated():
                    defer = getattr(self.o, "_sd_defer_expand", None)
                    if defer is not None and defer():
                        return None
            if getattr(self.o, "drag", None) is not None or self.o.sheet_lock:
                self.g = None
                return None
            g["claimed"] = True
            self._cancel_children(target, ev)
            self.begin()
        if a == 2:
            if dy != 0:
                self._apply(g, dy)
            return True
        self.g = None
        if g["last"] == "scroll" and a == 1:
            sv, vel = g["sv"], g["v"]
            if sv is not None and abs(vel) > 200:
                try:
                    sv.fling(int(-vel))
                except Exception:
                    with tolerated():
                        sv.fling(0, int(-vel))
        elif g["last"] == "sheet":
            self.end(g["v"] if a == 1 else 0.0)
        return True


def _attach_sheet_drag(owner, dlg, scrolls, top_y, can_start, can_up, begin, move, end):
    with tolerated():
        drag = _SheetDrag(owner, scrolls, top_y, can_start, can_up, begin, move, end)
        owner._sheet_drag = drag
        owner._sheet_hook = _window_hook(dlg, drag.on_touch)
