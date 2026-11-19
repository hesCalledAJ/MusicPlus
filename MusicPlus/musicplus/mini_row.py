from elyx import strings
from .compat import MethodHook, find_class, jarray, jclass, jfloat, jint, run_on_ui_thread
from . import reflect
from .android import _anim_proxy, _cls, _layoutchg_proxy, _mix, _proxies
from .helpers import _argb, _rd_index
from .safe import tolerated
from . import swap as _swap
from . import tint as _tint
import time

_FCV_CLASSES = ("org.telegram.ui.Components.FragmentContextView",)
_HOOKED = ("onAttachedToWindow", "checkPlayer", "updateStyle", "checkVisibility", "setVisibility")
_TICK_MS = 500
_HEIGHTS = (36, 42, 48, 56)
_HEIGHT_DEFAULT = 2
_CLOSE_GRACE_S = 0.7


def _theme(name, fallback):
    try:
        Theme = find_class("org.telegram.ui.ActionBar.Theme")
        return int(Theme.getColor(int(getattr(Theme, name))))
    except Exception:
        return fallback


def _lum(c):
    def ch(sh):
        return (((int(c) >> sh) & 255) / 255.0) ** 2.2
    return 0.2126 * ch(16) + 0.7152 * ch(8) + 0.0722 * ch(0)


def _contrast(a, b):
    x, y = _lum(a), _lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


class _Row:

    def __init__(self, mgr, fcv):
        self.mgr, self.p, self.fcv = mgr, mgr.p, fcv
        self.ctx = fcv.getContext()
        self.density = float(self.ctx.getResources().getDisplayMetrics().density)
        self.Touch, self.Click, self.Run = _proxies()
        self.handler = jclass("android.os.Handler")(jclass("android.os.Looper").getMainLooper())
        self.tick = self.Run(self._tick)
        self.running = False
        self.vis = None
        self.label = None
        self.paused = None
        self.cover_key = "__none__"
        self.cover_ok = False
        self.cover_tries = 0
        self.bmp_used = None
        self.sizes = None
        self.taken = False
        self.hidden = {}
        self.style_field = None
        self.orig_h = None
        self.closed_at = None
        self.pop_left = 0
        self.pop_run = self.Run(self._pop_poll)
        self.pre = None
        self.pre_key = None
        self.pre_tint = None
        self.pre_tries = 0
        self.samp_wait = 0
        self.prog_anim = None
        self.prog_lvl = 0.0
        self.prog_key = None
        self._pp_dp = self._glyph_dp = None
        self.cr = None
        self._build()
        t = self.mgr.tint
        if t is not None and self.p.get_setting("dynamic_tint", True):
            with tolerated():
                self._set_tint(t)

    def dp(self, v):
        return int(round(v * self.density))

    def height_px(self):
        try:
            i = int(self.p.get_setting("bar_height", _HEIGHT_DEFAULT))
        except Exception:
            i = _HEIGHT_DEFAULT
        return self.dp(_HEIGHTS[max(0, min(len(_HEIGHTS) - 1, i))])


    def _res(self, *names):
        with tolerated():
            r = self.ctx.getResources()
            pkg = self.ctx.getPackageName()
            for n in names:
                i = int(r.getIdentifier(n, "drawable", pkg))
                if i:
                    return i
        idx = _rd_index()
        for n in names:
            if n in idx:
                return idx[n]
        return 0

    def _text(self, size, color, bold=False):
        tv = _cls("android.widget.TextView")(self.ctx)
        tv.setTextSize(float(size))
        tv.setTextColor(color)
        if bold:
            tv.setTypeface(jclass("android.graphics.Typeface").DEFAULT_BOLD)
        tv.setGravity(51)
        tv.setSingleLine(True)
        tv.setEllipsize(jclass("android.text.TextUtils$TruncateAt").END)
        with tolerated():
            tv.setIncludeFontPadding(False)
        return tv

    def _icon(self, names, fallback, tint, fn, pad):
        iv = _cls("android.widget.ImageView")(self.ctx)
        iv.setImageResource(int(self._res(*names) or fallback))
        iv.setColorFilter(tint)
        iv.setPadding(pad, pad, pad, pad)
        iv.setOnClickListener(self.Click(lambda v: fn()))
        return iv

    def _skip_btn(self, nxt, fn):
        Dr = _cls("android.R$drawable")
        try:
            raw = int(self.ctx.getResources().getIdentifier("player_prev", "raw", self.ctx.getPackageName()))
            if not raw:
                raw = int(getattr(find_class("org.telegram.messenger.R$raw"), "player_prev"))
            self._raw = raw
            iv = find_class("org.telegram.ui.Components.RLottieImageView")(self.ctx)
            iv.setScaleType(_cls("android.widget.ImageView$ScaleType").CENTER)
            iv.setAnimation(raw, 22, 22)
            for layer in ("Triangle 3", "Triangle 4", "Rectangle 4"):
                iv.setLayerColor(layer, self.c_title)
            if nxt:
                iv.setRotation(180.0)
            def tap(v):
                fn()
                with tolerated():
                    iv.setProgress(0.0)
                    iv.playAnimation()
            iv.setOnClickListener(self.Click(tap))
            return iv
        except Exception:
            return self._icon(("ic_action_next",) if nxt else ("ic_action_previous",),
          Dr.ic_media_next if nxt else Dr.ic_media_previous, self.c_title, fn, self.dp(6))

    def _build(self):
        ctx, dp = self.ctx, self.dp
        LL = _cls("android.widget.LinearLayout")
        FL = _cls("android.widget.FrameLayout")
        FLP = _cls("android.widget.FrameLayout$LayoutParams")
        LP = _cls("android.widget.LinearLayout$LayoutParams")
        IV = _cls("android.widget.ImageView")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        Dr = _cls("android.R$drawable")
        white = _theme("key_windowBackgroundWhite", -1)
        self.c_bg = _theme("key_inappPlayerBackground", white)
        strong = _theme("key_windowBackgroundWhiteBlackText", _argb(255, 33, 33, 33))
        if _contrast(strong, self.c_bg) < 7.0:
            strong = max((_argb(255, 0, 0, 0), _argb(255, 255, 255, 255)), key=lambda k: _contrast(k, self.c_bg))
        self.c_title = self.c_close = strong
        self.c_sub = _mix(self.c_bg, strong, 0.68)
        self.base_accent = _theme("key_inappPlayerPlayPause", _theme("key_windowBackgroundWhiteBlueText", _argb(255, 42, 139, 234)))
        self.c_accent = self.base_accent
        self.tint_anim = None
        self.sample_left = 0
        self.late_left = 0
        self.sampled = False
        self.last_bmp = None
        self.last_bmp_key = None
        self.dir = 1
        self.liked = None
        self.ticks = 0
        root = LL(ctx)
        root.setOrientation(0)
        root.setGravity(16)
        root.setPadding(dp(12), 0, dp(4), 0)
        root.setClickable(True)
        self.clip = None
        self.fill = None
        try:
            fill = GD()
            self.fill = fill
            fill.setColor(self._wash(self.c_accent))
            clip = _cls("android.graphics.drawable.ClipDrawable")(fill, 8388611, 1)
            clip.setLevel(0)
            root.setBackground(clip)
            self.clip = clip
        except Exception:
            pass
        cov = FL(ctx)
        cbg = GD()
        cbg.setColor(_mix(self.c_bg, self.c_sub, 0.14))
        cbg.setShape(1)
        cbg.setCornerRadius(float(dp(20)))
        cov.setBackground(cbg)
        self.cbg = cbg
        with tolerated():
            cov.setClipToOutline(True)
        glyph = IV(ctx)
        glyph.setImageResource(int(self._res("files_music", "msg_filled_data_music") or Dr.ic_media_play))
        glyph.setColorFilter(self.c_sub)
        glyph.setPadding(dp(6), dp(6), dp(6), dp(6))
        glyph.setVisibility(4)
        self.glyph = glyph
        cov.addView(glyph, FLP(-1, -1))
        try:
            self.cover = find_class("org.telegram.ui.Components.BackupImageView")(ctx)
            self.cover.setRoundRadius(dp(20))
            self.cover_biv = True
        except Exception:
            self.cover = IV(ctx)
            self.cover.setScaleType(_cls("android.widget.ImageView$ScaleType").CENTER_CROP)
            self.cover_biv = False
        cov.addView(self.cover, FLP(-1, -1))
        self.cov = cov
        cover_tap = self.Click(lambda v: self._toggle())
        cov.setOnClickListener(cover_tap)
        self.cover.setOnClickListener(cover_tap)
        root.addView(cov, LP(dp(40), dp(40)))
        col = LL(ctx)
        col.setOrientation(1)
        col.setGravity(16)
        self.title = self._text(14, self.c_title, bold=True)
        self.sub = self._text(12, self.c_sub)
        col.addView(self.title, LP(-1, -2))
        col.addView(self.sub, LP(-1, -2))
        clp = LP(0, -2, 1.0)
        clp.setMargins(dp(12), 0, dp(4), 0)
        root.addView(col, clp)
        self.prev = self._skip_btn(False, self._prev)
        root.addView(self.prev, LP(dp(38), dp(38)))
        self.play = IV(ctx)
        pbg = GD()
        pbg.setShape(1)
        pbg.setColor(self.c_accent)
        self.play.setBackground(pbg)
        self.pbg = pbg
        self.pp = None
        try:
            pp = find_class("org.telegram.ui.Components.PlayPauseDrawable")(22)
            pp.setColor(-1)
            self.play.setImageDrawable(pp)
            with tolerated():
                pp.setParent(self.play)
            self.pp = pp
        except Exception:
            self.play.setImageResource(int(Dr.ic_media_play))
            self.play.setColorFilter(-1)
        self.play.setPadding(dp(9), dp(9), dp(9), dp(9))
        self.play.setOnClickListener(self.Click(lambda v: self._toggle()))
        plp = LP(dp(40), dp(40))
        plp.setMargins(dp(2), 0, dp(2), 0)
        root.addView(self.play, plp)
        self.next = self._skip_btn(True, self._next)
        root.addView(self.next, LP(dp(38), dp(38)))
        slot = FL(ctx)
        self.close = self._icon(("msg_close", "ic_close_white", "msg_cancel"),
       int(Dr.ic_menu_close_clear_cancel), self.c_close, self._close, dp(12))
        self.close.setContentDescription(strings("close"))
        slot.addView(self.close, FLP(-1, -1))
        self.like_ids = (int(self._res("media_like") or 0), int(self._res("media_like_active") or 0))
        self.like = self._icon(("media_like",), int(Dr.btn_star_big_off), self.c_title, self._like_tap, dp(11))
        self.like.setVisibility(8)
        slot.addView(self.like, FLP(-1, -1))
        self.slot = slot
        root.addView(slot, LP(dp(44), dp(44)))
        st = {"x": 0.0, "y": 0.0, "moved": False, "done": False}
        slop = float(int(jclass("android.view.ViewConfiguration").get(ctx).getScaledTouchSlop()))
        def on_touch(v, e):
            a = int(e.getActionMasked())
            if a == 0:
                st["x"], st["y"] = float(e.getRawX()), float(e.getRawY())
                st["moved"] = st["done"] = False
                with tolerated():
                    v.getParent().requestDisallowInterceptTouchEvent(True)
                return True
            if a == 2:
                dx, dy = float(e.getRawX()) - st["x"], float(e.getRawY()) - st["y"]
                if abs(dx) > slop or abs(dy) > slop:
                    st["moved"] = True
                if not st["done"] and abs(dx) > slop * 4 and abs(dx) > abs(dy) * 1.5:
                    st["done"] = True
                    (self._next if dx < 0 else self._prev)()
                return True
            if a == 1:
                if not st["moved"] and not st["done"]:
                    self._open()
                return True
            return a == 3
        root.setOnTouchListener(self.Touch(on_touch))
        root.addOnLayoutChangeListener(_layoutchg_proxy()(self._fit))
        root.setVisibility(8)
        self.vis = 8
        self.root = root
        self.fcv.addView(root, FLP(-1, self.height_px(), 48))

    @staticmethod
    def _wash(c):
        return (int(c) & 0xFFFFFF) | 0x38000000

    def _env(self):
        r = self.ctx.getResources()
        dens = float(r.getDisplayMetrics().density)
        try:
            fs = float(r.getConfiguration().fontScale)
        except Exception:
            fs = 1.0
        return dens, fs

    def _fit(self):
        try:
            h, w = int(self.root.getHeight()), int(self.root.getWidth())
            if h <= 0 or w <= 0:
                return
            dens, fs = self._env()
        except Exception:
            return
        key = (h, w, round(dens, 3), round(fs, 2))
        if key == self.sizes:
            return
        if abs(dens - self.density) > 0.001:
            self._pp_dp = self._glyph_dp = None
        self.density = dens
        try:
            self._apply_fit(h, w, fs)
            self.sizes = key
            self._fit_fail = 0
        except Exception:
            self._fit_fail = getattr(self, "_fit_fail", 0) + 1
            if self._fit_fail >= 5:
                self.sizes = key

    def _apply_fit(self, h, w, fs):
        dp, dens = self.dp, self.density
        hd, wd = h / dens, w / dens
        clamp = lambda lo, v, hi: max(lo, min(hi, v))
        cover = int(clamp(26, round(hd * 0.70), 42))
        inset = max(0, int(round((h - dp(cover)) / 2.0)))
        play_dp = int(clamp(36, round(hd * 0.86), 48))
        btn_dp = int(clamp(34, round(hd * 0.78), 44))
        slot_dp = int(clamp(36, round(hd * 0.80), 44))
        disc = clamp(24, round(hd * 0.58), 34)
        pp_dp = int(round(disc * 0.52))
        glyph = int(clamp(14, round(hd * 0.34), 20))
        ico = int(clamp(16, round(hd * 0.34), 20))
        btn_w = int(max(30, min(btn_dp, glyph + 14)))
        slot_w = int(max(32, min(slot_dp, ico + 14)))
        play_t, btn, slot = dp(play_dp), dp(btn_dp), dp(slot_dp)
        need = (inset / dens + cover + 12 + 4 + btn_w + play_dp + 4 + btn_w + slot_w + 4 + 96)
        show_prev = need <= wd
        for v, sw_, sh_ in ((self.cov, dp(cover), dp(cover)), (self.play, play_t, play_t),
                            (self.prev, dp(btn_w), btn), (self.next, dp(btn_w), btn), (self.slot, dp(slot_w), slot)):
            lp = v.getLayoutParams()
            lp.width, lp.height = sw_, sh_
            v.setLayoutParams(lp)
        self.prev.setVisibility(0 if show_prev else 8)
        plp = self.play.getLayoutParams()
        plp.leftMargin, plp.rightMargin = (dp(2) if show_prev else 0), dp(2)
        self.play.setLayoutParams(plp)
        circle = True
        r = int(dp(cover) // 2)
        with tolerated():
            self.cbg.setShape(1 if circle else 0)
            self.cbg.setCornerRadius(float(r))
        if self.cover_biv:
            with tolerated():
                self.cover.setRoundRadius(r)
        self.root.setPadding(inset, 0, dp(4), 0)
        pgap = max(0, int(round((play_t - dp(disc)) / 2.0)))
        self.play.setBackground(_cls("android.graphics.drawable.InsetDrawable")(self.pbg, int(pgap)))
        pad = int(round((play_t - dp(pp_dp)) / 2.0))
        self.play.setPadding(pad, pad, pad, pad)
        self._resize_pp(pp_dp)
        for iv in (self.prev, self.next):
            self._resize_skip(iv, glyph)
        ph, pv = int(round((dp(slot_w) - dp(ico)) / 2.0)), int(round((slot - dp(ico)) / 2.0))
        for v in (self.close, self.like):
            v.setPadding(ph, pv, ph, pv)
        self.title.setTextSize(float(clamp(13, 12 + hd / 28.0, 15)))
        self.sub.setTextSize(float(clamp(11, 10 + hd / 28.0, 12.5)))
        want = dp(clamp(1, (hd - 34) / 8.0, 3))
        room = h - dp(8) - int(self.title.getLineHeight()) - int(self.sub.getLineHeight())
        slp = self.sub.getLayoutParams()
        slp.topMargin = int(max(0, min(want, room)))
        self.sub.setLayoutParams(slp)


    def _resize_pp(self, size_dp):
        if self.pp is None or size_dp == getattr(self, "_pp_dp", None):
            return
        self._pp_dp = size_dp
        with tolerated():
            pp = find_class("org.telegram.ui.Components.PlayPauseDrawable")(size_dp)
            pp.setColor(-1)
            if self.paused is not None:
                pp.setPause(not self.paused, False)
            self.play.setImageDrawable(pp)
            with tolerated():
                pp.setParent(self.play)
            self.pp = pp

    def _resize_skip(self, iv, size_dp):
        if getattr(self, "_raw", None) is None or getattr(iv, "setAnimation", None) is None:
            return
        if getattr(self, "_glyph_dp", None) == size_dp:
            return
        with tolerated():
            iv.setAnimation(self._raw, size_dp, size_dp)
            for layer in ("Triangle 3", "Triangle 4", "Rectangle 4"):
                iv.setLayerColor(layer, self.c_title)
        self._glyph_dp = size_dp if iv is self.next else getattr(self, "_glyph_dp", None)


    def _mc(self):
        return self.p._get_mc()

    def _nudge(self):
        for d in (120, 400):
            self.handler.postDelayed(self.Run(self.update), d)

    def _toggle(self):
        with tolerated():
            mc = self._mc()
            pm = mc.getPlayingMessageObject()
            if pm is None:
                return
            if bool(mc.isMessagePaused()):
                mc.playMessage(pm)
            else:
                mc.pauseMessage(pm)
        self.update()
        self._nudge()

    def _next(self):
        self.dir = 1
        with tolerated():
            self._mc().playNextMessage()
        self._nudge()

    def _prev(self):
        self.dir = -1
        with tolerated():
            self._mc().playPreviousMessage()
        self._nudge()

    def _open(self):
        ok = False
        with tolerated():
            ok = bool(self.fcv.performClick())
        if not ok:
            with tolerated():
                self.p._open_queue_editor()

    def _close(self):
        with tolerated():
            native = reflect.field(self.fcv, "closeButton")
            if native is not None and bool(native.performClick()):
                return
        p = self.p
        if p.get_setting("lock_queue", False):
            with tolerated():
                p._confirm_close_player([True, True])
            return
        with tolerated():
            self._mc().cleanupPlayer(True, True)

    def _like_tap(self):
        with tolerated():
            pm = self._mc().getPlayingMessageObject()
            if pm is not None:
                self.p._toggle_track_liked(pm)
                self.refresh_like(pm, True)
                self.like.animate().scaleX(1.25).scaleY(1.25).setDuration(110).withEndAction(
            self.Run(lambda: self.like.animate().scaleX(1.0).scaleY(1.0).setDuration(140).start())).start()

    def refresh_like(self, pm, force=False):
        liked = bool(pm is not None and self.p._is_track_liked(pm))
        if liked == self.liked and not force:
            return
        self.liked = liked
        with tolerated():
            self.like.setImageResource(self.like_ids[1 if liked else 0] or self.like_ids[0])
            self.like.setColorFilter(self.c_accent if liked else self.c_title)
            self.like.setContentDescription(
          strings("remove_from_liked_songs") if liked else strings("add_to_liked_songs"))

    def _slot_show(self, paused, animate):
        shown, hidden = (self.close, self.like) if paused else (self.like, self.close)
        hidden.setVisibility(8)
        shown.setVisibility(0)
        if animate:
            shown.setAlpha(0.0)
            shown.animate().alpha(1.0).setDuration(160).start()
        else:
            shown.setAlpha(1.0)


    def retheme(self):
        white = _theme("key_windowBackgroundWhite", -1)
        self.c_bg = _theme("key_inappPlayerBackground", white)
        strong = _theme("key_windowBackgroundWhiteBlackText", _argb(255, 33, 33, 33))
        if _contrast(strong, self.c_bg) < 7.0:
            strong = max((_argb(255, 0, 0, 0), _argb(255, 255, 255, 255)), key=lambda k: _contrast(k, self.c_bg))
        self.c_title = self.c_close = strong
        self.c_sub = _mix(self.c_bg, strong, 0.68)
        self.base_accent = _theme("key_inappPlayerPlayPause",
            _theme("key_windowBackgroundWhiteBlueText", _argb(255, 42, 139, 234)))
        with tolerated():
            self.title.setTextColor(self.c_title)
        with tolerated():
            self.sub.setTextColor(self.c_sub)
        with tolerated():
            self.close.setColorFilter(self.c_close)
        with tolerated():
            self.glyph.setColorFilter(self.c_sub)
        with tolerated():
            self.cbg.setColor(_mix(self.c_bg, self.c_sub, 0.14))
        for iv in (self.prev, self.next):
            with tolerated():
                for layer in ("Triangle 3", "Triangle 4", "Rectangle 4"):
                    iv.setLayerColor(layer, self.c_title)
        with tolerated():
            self.like.setColorFilter(self.c_accent if self.liked else self.c_title)
        if self.p.get_setting("dynamic_tint", True) and self.sampled:
            self.sample_left = 3
            self.sampled = False
        else:
            t = self.mgr.tint
            self._set_tint(t if (t is not None and self.p.get_setting("dynamic_tint", True)) else self.base_accent)
        with tolerated():
            self.root.invalidate()

    def _set_tint(self, c):
        self.c_accent = c
        with tolerated():
            self.pbg.setColor(c)
            self.play.invalidate()
        with tolerated():
            if self.fill is not None:
                self.fill.setColor(self._wash(c))
                self.root.invalidate()
        if self.liked:
            with tolerated():
                self.like.setColorFilter(c)

    def _animate_tint(self, to):
        frm = self.c_accent
        self.mgr.tint = to
        self.mgr.tint_key = self.cover_key
        _tint.set_current(to)
        if self.tint_anim is not None:
            with tolerated():
                self.tint_anim.cancel()
        if frm == to:
            return
        _tint.set_dur(self._fade_ms())
        try:
            va = _tint.ease(_cls("android.animation.ValueAnimator").ofFloat(jarray(jfloat)([0.0, 1.0])))
            va.addUpdateListener(_anim_proxy()(_tint.throttled(lambda f: self._set_tint(_mix(frm, to, f)))))
            self.tint_anim = va
            va.start()
        except Exception:
            self._set_tint(to)
        with tolerated():
            ed = getattr(self.p, "_editor", None)
            if ed is not None:
                ed._tint_poll()
        _tint.set_dur(None)

    def _fade_ms(self):
        with tolerated():
            xf = getattr(self.p, "_xf", None)
            last = getattr(xf, "last", None) if xf is not None else None
            if last is not None:
                left = last[0] - (time.monotonic() - last[1]) * 1000.0
                if left > _tint.DUR_MS:
                    return int(min(left, 12000))
        return None

    def _art_bitmap(self, mc):
        bmp = None
        with tolerated():
            e = self.p._emb_get(self.cover_key)
            bmp = e if (e is not None and e is not False) else None
        if bmp is None and self.cover_biv:
            with tolerated():
                bmp = self.cover.getImageReceiver().getBitmap()
        if bmp is None:
            with tolerated():
                bmp = self.p._info_cover(mc, mc.getPlayingMessageObject())
        return bmp

    def _sample(self, mc):
        bmp = self._art_bitmap(mc)
        if bmp is None:
            return None, None, False
        ready, c = _tint.get(bmp, self.c_bg)
        if not ready:
            _tint.request(bmp, self.c_bg)
            return None, None, True
        return (c, bmp, False) if c is not None else (None, None, False)

    def update_tint(self, mc):
        if not self.p.get_setting("dynamic_tint", True):
            self.sample_left = 0
            if _tint.current() is not None:
                _tint.set_current(None)
                self.mgr.tint = None
            if self.c_accent != self.base_accent:
                self._animate_tint(self.base_accent)
                _tint.set_current(None)
                self.mgr.tint = None
            return
        late = self.sample_left <= 0
        if late and (self.sampled or self.late_left <= 0):
            return
        if late:
            self.late_left -= 1
        c, bmp, wait = self._sample(mc)
        if wait and self.samp_wait < 8:
            self.samp_wait += 1
            return
        self.samp_wait = 0
        if not late:
            self.sample_left -= 1
        if c is not None:
            stale = (bmp is self.last_bmp and self.last_bmp_key != self.cover_key)
            if stale:
                return
            self.last_bmp, self.last_bmp_key = bmp, self.cover_key
            self.sampled = True
            self.sample_left = 0
            self.late_left = 0
            diff = sum(abs(((c >> s) & 255) - ((self.c_accent >> s) & 255)) for s in (16, 8, 0))
            if diff > 10:
                self._animate_tint(c)


    def attach(self):
        with tolerated():
            self.attach_order()
        if not self.running:
            self.running = True
            self._fit()
            self.handler.removeCallbacks(self.tick)
            self.handler.post(self.tick)

    def _tick(self):
        if not self.running:
            return
        with tolerated():
            if not bool(self.root.isAttachedToWindow()):
                self.running = False
                return
            self.attach_order()
            self.update()
        with tolerated():
            ed = getattr(self.p, "_editor", None)
            if ed is not None:
                ed.revive_tick()
        self.handler.postDelayed(self.tick, _TICK_MS)

    def revive(self):
        with tolerated():
            if self.prog_anim is not None:
                self.prog_anim.cancel()
        self.prog_anim = None
        self.prog_key = None
        self.sizes = None
        self._fit_fail = 0
        self.vis = None
        self.label = None
        self.paused = None
        self.cover_key = "__none__"
        self.cover_ok = False
        self.cover_tries = 0
        self.closed_at = None
        with tolerated():
            self.handler.removeCallbacks(self.tick)
        self.running = False
        with tolerated():
            self.fcv.requestLayout()
            self.root.requestLayout()
        self.attach()
        with tolerated():
            self.update()

    def attach_order(self):
        n = int(self.fcv.getChildCount())
        if n and reflect.identity_hash(self.fcv.getChildAt(n - 1)) != reflect.identity_hash(self.root):
            self.root.bringToFront()

    def applicable(self, pm):
        if pm is None or not self.p.get_setting("replace_row", True):
            return False
        with tolerated():
            if not bool(pm.isMusic()):
                return False
            style = reflect.field(self.fcv, "currentStyle")
            is_music = reflect.field(self.fcv, "isMusic")
            return style is None or int(style) == 0 or bool(is_music)
        return False

    @staticmethod
    def _title_of(m):
        for getter in ("getMusicTitle", "getFileName"):
            with tolerated():
                t = getattr(m, getter)()
                if t and str(t).strip():
                    return str(t)
        return "Audio"

    @staticmethod
    def _author_of(m):
        with tolerated():
            a = m.getMusicAuthor()
            if a and str(a).strip():
                return str(a)
        return ""

    def takeover(self, on):
        fcv, h = self.fcv, self.height_px()
        if on:
            with tolerated():
                me = reflect.identity_hash(self.root)
                for i in range(int(fcv.getChildCount())):
                    c = fcv.getChildAt(i)
                    k = reflect.identity_hash(c)
                    if k == me:
                        continue
                    vis = int(c.getVisibility())
                    if vis != 8:
                        self.hidden[k] = (c, vis)
                        c.setVisibility(8)
                    elif k not in self.hidden:
                        self.hidden[k] = (c, 8)
            with tolerated():
                lp = fcv.getLayoutParams()
                if lp is not None and int(lp.height) > 0 and int(lp.height) != h:
                    if self.orig_h is None:
                        self.orig_h = int(lp.height)
                    lp.height = h
                    fcv.setLayoutParams(lp)
                mine = self.root.getLayoutParams()
                if int(mine.height) != h:
                    mine.height = h
                    self.root.setLayoutParams(mine)
        elif self.taken:
            with tolerated():
                for c, vis in list(self.hidden.values()):
                    c.setVisibility(vis)
                self.hidden.clear()
            with tolerated():
                if self.orig_h is not None:
                    lp = fcv.getLayoutParams()
                    lp.height = self.orig_h
                    fcv.setLayoutParams(lp)
                    self.orig_h = None
        self.taken = bool(on)

    def stock_line_off(self):
        if not self.taken:
            return None
        f = self.style_field
        if f is None:
            f = False
            cls = self.fcv.getClass()
            while cls is not None:
                with tolerated():
                    h = cls.getDeclaredField("currentStyle")
                    h.setAccessible(True)
                    f = h
                    break
                cls = cls.getSuperclass()
            self.style_field = f
        if f is False:
            return None
        old = int(f.getInt(self.fcv))
        if old != 0:
            return None
        f.setInt(self.fcv, -1)
        return old

    def stock_line_on(self, old):
        self.style_field.setInt(self.fcv, int(old))

    def enforce(self):
        if not self.taken:
            return
        for c, _ in list(self.hidden.values()):
            if int(c.getVisibility()) != 8:
                self.takeover(True)
                return

    def _music_host(self):
        style = reflect.field(self.fcv, "currentStyle")
        return style is None or int(style) == 0 or bool(reflect.field(self.fcv, "isMusic"))

    def update(self):
        mc = self._mc()
        pm = None
        with tolerated():
            pm = mc.getPlayingMessageObject() if mc is not None else None
        show = self.applicable(pm)
        if not show and pm is None and self.taken:
            if self.closed_at is None:
                self.closed_at = time.monotonic()
            keep = False
            with tolerated():
                keep = (time.monotonic() - self.closed_at < _CLOSE_GRACE_S and self._music_host()
                        and int(self.fcv.getVisibility()) == 0)
            if keep:
                self.takeover(True)
                return
        self.closed_at = None
        self.takeover(show)
        vis = 0 if show else 8
        if vis != self.vis:
            self.vis = vis
            self.root.setVisibility(vis)
        if not show:
            return
        label = (self._title_of(pm), self._author_of(pm))
        if label != self.label:
            first = self.label is None
            self.label = label
            d, self.dir = self.dir, 1
            sh = self.dp(14)

            def set_sub():
                self.sub.setText(label[1])
                self.sub.setVisibility(0 if label[1] else 8)
            _swap.swap_text(self.title, lambda: self.title.setText(label[0]), sh, d, self.Run, not first)
            if first or not label[1]:
                set_sub()
            else:
                _swap.swap_text(self.sub, set_sub, sh, d, self.Run, True)
        key = None
        with tolerated():
            key = (int(pm.getId()), int(pm.getDialogId()))
        if key != self.cover_key:
            had = self.cover_key != "__none__"
            self.cover_key, self.cover_tries = key, 0
            self.cover_ok = self._set_cover(mc, pm, key)
            if had:
                with tolerated():
                    self.cover.animate().cancel()
                    self.cover.setAlpha(0.0)
                self.pop_left = 12
                self._pop_poll()
            self.sample_left = 20 if had else 40
            self.late_left = 60
            self.sampled = False
            with tolerated():
                self.p._emb_fetch(pm, lambda: None)
            pt = self.pre_tint
            if pt is not None and pt[0] == key and self.p.get_setting("dynamic_tint", True):
                self.sample_left = 0
                self.sampled = True
                self._animate_tint(pt[1])
            self.refresh_like(pm, True)
        elif self.cover_tries < 20 and (not self.cover_ok or not self._has_image()):
            self.cover_tries += 1
            self.cover_ok = self._set_cover(mc, pm, key)
        self._glyph(not self.cover_ok and self.cover_tries >= 3 and not self._has_image())
        paused = bool(mc.isMessagePaused())
        self.ticks += 1
        if self.ticks % 6 == 0:
            self.refresh_like(pm)
        self.update_tint(mc)
        with tolerated():
            self._preload()
        if paused != self.paused:
            first = self.paused is None
            self.paused = paused
            self._slot_show(paused, not first)
            if self.pp is not None:
                with tolerated():
                    self.pp.setPause(not paused, not first)
            else:
                self.play.setImageResource(int(_cls("android.R$drawable").ic_media_play if paused
                                               else _cls("android.R$drawable").ic_media_pause))
        with tolerated():
            self._progress(pm, paused, key)

    def _progress(self, pm, paused, key):
        if self.clip is None:
            return
        p = max(0.0, min(1.0, float(pm.audioProgress)))
        dur = 0
        with tolerated():
            dur = int(pm.getDuration())
        spd = 1.0
        with tolerated():
            spd = max(0.25, float(self.p._pb_settings()[0]))
        va = self.prog_anim
        running = False
        if va is not None:
            with tolerated():
                running = bool(va.isRunning())
        if paused or dur <= 0 or key != self.prog_key:
            self.prog_key = key
            self._stop_glide()
            self._set_level(p)
            return
        drift_s = abs(p - self._lvl()) * dur
        if running and abs(spd - getattr(self, "prog_spd", spd)) < 1e-6 and drift_s <= 1.5:
            return
        self._stop_glide()
        if drift_s > 1.5 or not running and drift_s > 0.3:
            self._set_level(p)
        start = self._lvl()
        left_ms = int((1.0 - start) * dur * 1000.0 / spd)
        if left_ms < 50:
            self._set_level(p)
            return
        self.prog_spd = spd
        try:
            va = _cls("android.animation.ObjectAnimator").ofInt(
                self.clip, "level", jarray(jint)([int(start * 10000), 10000]))
            va.setInterpolator(_cls("android.view.animation.LinearInterpolator")())
            va.setDuration(left_ms)
            self.prog_anim = va
            va.start()
        except Exception:
            self._set_level(p)

    def _stop_glide(self):
        va, self.prog_anim = self.prog_anim, None
        if va is not None:
            with tolerated():
                va.cancel()

    def _lvl(self):
        with tolerated():
            return max(0.0, min(1.0, int(self.clip.getLevel()) / 10000.0))
        return self.prog_lvl

    def _set_level(self, frac):
        self.prog_lvl = max(0.0, min(1.0, float(frac)))
        with tolerated():
            self.clip.setLevel(int(self.prog_lvl * 10000))


    @staticmethod
    def _thumb(doc):
        thumbs = doc.thumbs
        if thumbs is None or int(thumbs.size()) == 0:
            return None
        real = []
        for i in range(int(thumbs.size())):
            t = thumbs.get(i)
            try:
                name = str(t.getClass().getSimpleName())
                if "Stripped" in name or "Path" in name or "Empty" in name:
                    continue
                real.append((int(t.w) * int(t.h), t))
            except Exception:
                continue
        real.sort(key=lambda x: x[0])
        if real:
            return real[0][1]
        try:
            return find_class("org.telegram.messenger.FileLoader").getClosestPhotoSizeWithSize(thumbs, 90)
        except Exception:
            return None

    def _has_image(self):
        with tolerated():
            if self.cover_biv:
                return self.cover.getImageReceiver().getBitmap() is not None
            return self.cover.getDrawable() is not None
        return False

    def _pop_poll(self):
        if self.pop_left <= 0:
            return
        self.pop_left -= 1
        if self._has_image() or self.pop_left == 0:
            self.pop_left = 0
            _swap.pop_in(self.cover)
            return
        with tolerated():
            self.handler.postDelayed(self.pop_run, 100)


    def _preload(self):
        nm = self.p._native_next()
        nk = self.p._msg_key(nm) if nm is not None else None
        if nk is None:
            self.pre_key, self.pre_tint = None, None
            return
        if nk != self.pre_key:
            self.pre_key, self.pre_tint, self.pre_tries = nk, None, 0
            with tolerated():
                self.p._emb_fetch(nm, lambda: None)
            loc = self._loc_of(nm)
            if loc is not None and self.cover_biv:
                with tolerated():
                    if self.pre is None:
                        self.pre = find_class("org.telegram.ui.Components.BackupImageView")(self.ctx)
                        self.pre.getImageReceiver().onAttachedToWindow()
                    self.pre.setImage(loc, "64_64", _cls("android.graphics.drawable.ColorDrawable")(0), nm)
            return
        if self.pre_tint is None and self.pre_tries < 16 and self.p.get_setting("dynamic_tint", True):
            bmp = None
            with tolerated():
                e = self.p._emb_get(nk)
                bmp = e if (e is not None and e is not False) else None
            if bmp is None and self.pre is not None:
                with tolerated():
                    bmp = self.pre.getImageReceiver().getBitmap()
            if bmp is None or self._pre_pick(nk, bmp) is None:
                self.pre_tries += 1

    def _pre_pick(self, nk, bmp):
        with tolerated():
            ready, c = _tint.get(bmp, self.c_bg)
            if not ready:
                _tint.request(bmp, self.c_bg)
                return False
            if c is not None:
                self.pre_tint = (nk, c)
                return True
        return None

    def _glyph(self, show):
        if show != getattr(self, "_glyph_on", False):
            self._glyph_on = show
            with tolerated():
                self.glyph.setVisibility(0 if show else 4)

    def _loc_of(self, pm):
        IL = find_class("org.telegram.messenger.ImageLocation")
        loc = None
        with tolerated():
            doc = pm.getDocument()
            size = self._thumb(doc) if doc is not None else None
            if size is not None:
                loc = IL.getForDocument(size, doc)
        if loc is None:
            with tolerated():
                url = pm.getArtworkUrl(True)
                if url and str(url).strip():
                    loc = IL.getForPath(str(url))
        return loc

    def _set_cover(self, mc, pm, key):
        pre = None
        with tolerated():
            pre = self.p._emb_get(key)
        if pre is not None and pre is not False:
            with tolerated():
                self.cover.setImageBitmap(pre)
                self.bmp_used = (pre, key)
                return True
        with tolerated():
            self.p._emb_fetch(pm, lambda: None)
        bmp = None
        with tolerated():
            bmp = self.p._info_cover(mc, pm)
        if bmp is not None:
            used = self.bmp_used
            if not (used is not None and used[0] is bmp and used[1] != key and self.cover_tries < 3):
                with tolerated():
                    self.cover.setImageBitmap(bmp)
                    self.bmp_used = (bmp, key)
                    return True
        loc = self._loc_of(pm)
        if loc is not None and self.cover_biv:
            with tolerated():
                rcv = self.cover.getImageReceiver()
                rcv.setCrossfadeDuration(0)
                rcv.setAllowStartAnimation(False)
            with tolerated():
                self.cover.setImage(loc, "64_64", _cls("android.graphics.drawable.ColorDrawable")(0), pm)
                return True
        if bmp is None:
            with tolerated():
                if self.cover_biv:
                    self.cover.getImageReceiver().clearImage()
                    self.cover.setImageDrawable(_cls("android.graphics.drawable.ColorDrawable")(0))
                else:
                    self.cover.setImageDrawable(None)
        return False

    def destroy(self):
        self.running = False
        with tolerated():
            if self.prog_anim is not None:
                self.prog_anim.cancel()
        with tolerated():
            self.takeover(False)
        with tolerated():
            self.handler.removeCallbacks(self.tick)
        with tolerated():
            self.handler.removeCallbacks(self.pop_run)
        if self.pre is not None:
            with tolerated():
                self.pre.getImageReceiver().onDetachedFromWindow()
            self.pre = None
        with tolerated():
            self.fcv.removeView(self.root)


class _MiniRows:
    def __init__(self, plugin):
        self.p = plugin
        self.tint = None
        self.tint_key = None
        self.rows = {}

    def install(self):
        cls = None
        for name in _FCV_CLASSES:
            cls = find_class(name)
            if cls is not None:
                break
        if cls is None:
            return False
        mgr = self
        class RowHook(MethodHook):
            def after_hooked_method(self, param):
                with tolerated():
                    mgr.touch(param.thisObject)
        class EnforceHook(MethodHook):
            def before_hooked_method(self, param):
                with tolerated():
                    row = mgr.rows.get(reflect.identity_hash(param.thisObject))
                    if row is not None:
                        row.enforce()
        class HeightHook(MethodHook):
            def after_hooked_method(self, param):
                with tolerated():
                    row = mgr.rows.get(reflect.identity_hash(param.thisObject))
                    if row is not None and row.taken and int(param.getResult()) > 0:
                        param.setResult(row.height_px())
        class MeasureHook(MethodHook):
            def after_hooked_method(self, param):
                with tolerated():
                    fcv = param.thisObject
                    row = mgr.rows.get(reflect.identity_hash(fcv))
                    if row is not None and row.taken:
                        h = row.height_px()
                        if int(fcv.getMeasuredHeight()) != h:
                            reflect.invoke(fcv, "setMeasuredDimension", int(fcv.getMeasuredWidth()), h)
        saved = {}

        class StyleHook(MethodHook):
            def before_hooked_method(self, param):
                with tolerated():
                    obj = param.thisObject
                    row = mgr.rows.get(reflect.identity_hash(obj))
                    old = row.stock_line_off() if row is not None else None
                    if old is not None:
                        saved[reflect.identity_hash(obj)] = old

            def after_hooked_method(self, param):
                with tolerated():
                    key = reflect.identity_hash(param.thisObject)
                    old = saved.pop(key, None)
                    row = mgr.rows.get(key)
                    if old is not None and row is not None:
                        row.stock_line_on(old)

        hooked = []
        for name, hook in ([(n, RowHook) for n in _HOOKED] + [("dispatchDraw", EnforceHook), ("dispatchDraw", StyleHook),
                            ("onMeasure", MeasureHook)] + [(n, HeightHook) for n in self._height_methods(cls)]):
            with tolerated():
                u = self.p.hook_all_methods(cls, name, hook())
                if u:
                    self.p._hooks.extend(u if isinstance(u, list) else [u])
                    hooked.append(name)
        with tolerated():
            LA = find_class("org.telegram.ui.LaunchActivity")
            if LA is not None:
                class ResumeHook(MethodHook):
                    def after_hooked_method(self, param):
                        with tolerated():
                            mgr.revive()
                u = self.p.hook_all_methods(LA, "onResume", ResumeHook())
                if u:
                    self.p._hooks.extend(u if isinstance(u, list) else [u])
        self.revive()
        return bool(hooked)

    @staticmethod
    def _height_methods(cls):
        names = []
        with tolerated():
            for m in cls.getDeclaredMethods():
                n = str(m.getName())
                if ("eight" in n and int(m.getParameterTypes().__len__()) == 0
                        and str(m.getReturnType().getName()) == "int" and n not in names):
                    names.append(n)
        return names

    _BAR_FIELDS = ("fragmentContextView", "fragmentLocationContextView")

    def _scan(self):
        out = []
        with tolerated():
            LA = find_class("org.telegram.ui.LaunchActivity")
            act = LA.instance if LA is not None else None
            if act is None:
                return out
            cls = find_class(_FCV_CLASSES[0])
            layouts = []
            for name in ("actionBarLayout", "rightActionBarLayout", "layersActionBarLayout"):
                with tolerated():
                    lay = reflect.field(act, name)
                    if lay is not None:
                        layouts.append(lay)
            for lay in layouts:
                with tolerated():
                    stack = lay.getFragmentStack()
                    for i in range(int(stack.size())):
                        frag = stack.get(i)
                        for fname in self._BAR_FIELDS:
                            with tolerated():
                                v = reflect.field(frag, fname)
                                if v is not None and cls.isInstance(v):
                                    out.append(v)
        return out

    def _revive_now(self, scan):
        if scan:
            for fcv in self._scan():
                with tolerated():
                    h = reflect.identity_hash(fcv)
                    if h not in self.rows:
                        self.touch(fcv)
        for row in list(self.rows.values()):
            with tolerated():
                if bool(row.root.isAttachedToWindow()):
                    row.revive()

    def revive(self):
        for delay, scan in ((0, True), (300, False), (1200, True)):
            run_on_ui_thread(lambda sc=scan, d=delay: self._revive_now(sc and (d == 0 or not self.rows)), delay)

    def touch(self, fcv):
        h = reflect.identity_hash(fcv)
        row = self.rows.get(h)
        if row is None:
            if not hasattr(fcv, "addView"):
                return
            self._prune()
            row = _Row(self, fcv)
            self.rows[h] = row
        row.attach()
        row.update()

    def _prune(self):
        for h, row in list(self.rows.items()):
            gone = False
            with tolerated():
                gone = (row.fcv.getParent() is None and not bool(row.root.isAttachedToWindow()))
            if gone:
                row.destroy()
                self.rows.pop(h, None)

    _THEME_EVENTS = ("didSetNewTheme", "needSetDayNightTheme")

    def install_theme_listener(self):
        from .android import _proxy
        NC = find_class("org.telegram.messenger.NotificationCenter")
        L = _proxy("org.telegram.messenger.NotificationCenter$NotificationCenterDelegate", "didReceivedNotification")
        self._theme_ev = (NC, L(self._on_theme))
        for name in self._THEME_EVENTS:
            with tolerated():
                NC.getGlobalInstance().addObserver(self._theme_ev[1], int(getattr(NC, name)))

    def _on_theme(self, *a):
        for delay in (60, 400):
            for row in list(self.rows.values()):
                run_on_ui_thread(row.retheme, delay)

    def stop(self):
        ev = getattr(self, "_theme_ev", None)
        self._theme_ev = None
        if ev is not None:
            for name in self._THEME_EVENTS:
                with tolerated():
                    ev[0].getGlobalInstance().removeObserver(ev[1], int(getattr(ev[0], name)))
        for row in list(self.rows.values()):
            row.destroy()
        self.rows.clear()
