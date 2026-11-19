import json
import threading
import time
from ..compat import jarray, jclass, jfloat, jint, run_on_ui_thread
from elyx import strings
from ..android import _anim_proxy, _cls, _dismiss_proxy, _mix, _proxy, _viewlong_proxy, _wide_px
from ..lyrics import _LYR_RANK, _lyr_candidates, _lyr_fetch, _lyr_is_rtl, _lyr_word_ends
from ..lyrics_embedded import read as _lyr_embedded
from ..glass import _hit
from ..safe import tolerated


class _QueueEditorLyricsScroll:
    def _lyr_start(self):
        with tolerated():
            self.tab_pages["lyrics"].setKeepScreenOn(bool(self.p.get_setting("lyrics_keep_awake", True)))
        with tolerated():
            self._lyr_sync_insets()
        if self._lyr_running:
            return
        self._lyr_running = True
        self.handler.removeCallbacks(self.lyr_run)
        self.handler.post(self.lyr_run)

    def _lyr_tick(self):
        with tolerated():
            if self.tab != "lyrics" or not self.dialog.isShowing():
                self._lyr_running = False
                return
            self._lyr_update()
        self.handler.postDelayed(self.lyr_run, 80)

    def _lyr_set_status(self, text, tap=False):
        if not self.__dict__.get("_lyr_status_wired"):
            self._lyr_status_wired = True
            self.lyr_status.setOnClickListener(
                self.Click(lambda v: self._lyr_search_dialog() if self.__dict__.get("_lyr_status_tap") else None))
        self._lyr_status_tap = bool(tap and text)
        self.lyr_status.setClickable(self._lyr_status_tap)
        self.lyr_status.setPadding(self.dp(24), self.dp(14 if tap else 0), self.dp(24), self.dp(14 if tap else 0))
        self.lyr_status.setText(text)
        self.lyr_status.setVisibility(0 if text else 8)

    def _lyr_update(self):
        mc, pm = self._mini_playing()
        if pm is None:
            if self.lyr_key is not None:
                self.lyr_key = None
                self.lyr_data = None
                self.lyr_col.removeAllViews()
            self.lyr_free = False
            self._lyr_btn_show(False)
            self._lyr_set_status(strings("nothing_is_playing"))
            return
        key = self._key(pm)
        if key != self.lyr_key:
            self._lyr_load(key, pm)
            return
        data = self.lyr_data
        if not data or data["kind"] == "plain":
            if self.lyr_free or self.lyr_btn_vis:
                self.lyr_free = False
                self._lyr_btn_show(False)
            return
        dur = float(pm.getDuration())
        pr = float(pm.audioProgress)
        if self.lyr_stale:
            if pr == self.lyr_stale and not bool(mc.isMessagePaused()):
                pr = 0.0
            else:
                self.lyr_stale = 0.0
        pos = int(pr * dur * 1000) - int(getattr(self, "lyr_off", 0))
        lines = data["lines"]
        idx = -1
        for i, l in enumerate(lines):
            if l["t"] <= pos:
                idx = i
            else:
                break
        if idx != self.lyr_active:
            self._lyr_style_active(idx)
        self._lyr_follow_state()
        line = lines[idx] if idx >= 0 else None
        if line and line["w"]:
            wi = -1
            for i, w in enumerate(line["w"]):
                if w[0] <= pos:
                    wi = i
                else:
                    break
            if wi != self.lyr_word:
                self.lyr_word = wi
                self._lyr_paint_words(idx, wi)

    def _lyr_dim(self, active=False):
        return _mix(self.c_bg, self.c_text, 0.5 if active else 0.32)

    def _lyr_load(self, key, pm):
        self.lyr_key = key
        self.lyr_data = None
        self.lyr_active = -1
        self.lyr_word = -1
        self._lyr_sung = None
        try:
            self.lyr_stale = float(pm.audioProgress)
        except Exception:
            self.lyr_stale = 0.0
        self.lyr_token += 1
        token = self.lyr_token
        pref = self._lyr_pref(key)
        self.lyr_off = int(pref.get("off", 0) or 0)
        prefer = pref.get("src")
        self.lyr_free = False
        self._lyr_cancel_anim()
        self._lyr_btn_show(False)
        self.lyr_col.removeAllViews()
        self.lyr_views = []
        if key in self.lyr_cache:
            self._lyr_apply(self.lyr_cache[key])
            return
        self._lyr_set_status(strings("loading_lyrics"))
        title, artist = self._lyr_query(pm, key)[:2]
        try:
            dur = int(pm.getDuration())
        except Exception:
            dur = 0
        album = ""
        ed = self
        def done(res):
            if token != ed.lyr_token:
                return
            if res or online:
                ed.lyr_cache[key] = res
                while len(ed.lyr_cache) > 30:
                    ed.lyr_cache.pop(next(iter(ed.lyr_cache)), None)
            if res is None or res is not ed.lyr_data:
                ed._lyr_apply(res)
        path = None
        with tolerated():
            f = self.p._emb_file(pm)
            path = str(f.getAbsolutePath()) if f is not None else None
        online = self.p._net_ok()
        def early(res):
            def show():
                if token == ed.lyr_token and ed.lyr_data is None:
                    ed._lyr_apply(res)
            run_on_ui_thread(show)
        def work():
            emb = _lyr_embedded(path) if path else None
            if emb is not None:
                emb.setdefault("id", "local")
            try:
                res = _lyr_fetch(title, artist, album, dur, emb, online, None if prefer else early, prefer)
            except Exception:
                res = emb
            run_on_ui_thread(lambda: done(res))
        threading.Thread(target=work, daemon=True).start()

    def _lyr_apply(self, data):
        self.lyr_data = data
        self.lyr_views = []
        self.lyr_col.removeAllViews()
        if not data:
            self._lyr_set_status(strings("no_lyrics_found") + "\n" + strings("lyrics_tap_to_search"), tap=True)
            return
        self._lyr_set_status("")
        plain = data["kind"] == "plain"
        self.lyr_rtl = []
        prev_rtl = False
        for i, l in enumerate(data["lines"]):
            text = l["text"] or ("" if plain else "♪")
            rtl = _lyr_is_rtl(text, prev_rtl)
            prev_rtl = rtl
            self.lyr_rtl.append(rtl)
            tv = self._text(text, 16 if plain else 24, self.c_text if plain else self._lyr_dim(),
          bold=not plain, gravity=5 if rtl else 3)
            with tolerated():
                tv.setTextDirection(4 if rtl else 3)
            spare = 0 if plain else self.dp(24)
            tv.setPadding(spare if rtl else 0, self.dp(6 if plain else 10), 0 if rtl else spare, self.dp(6 if plain else 10))
            if not plain:
                tv.setOnClickListener(self.Click(lambda v, k=i: self._lyr_seek(k)))
                tv.setPivotX(0.0)
                tv.setAlpha(0.0)
                tv.animate().alpha(float(self._lyr_target(i, -1)[0])).setDuration(320).setInterpolator(self._lyr_ease()).start()
            self.lyr_col.addView(tv, self.LP(-1, -2))
            self.lyr_views.append(tv)
        foot = self._text((strings("lyrics") + ": ") + data["src"], 11, self.c_sub, gravity=3)
        foot.setPadding(0, self.dp(28), 0, self.dp(60))
        self.lyr_col.addView(foot, self.LP(-1, -2))
        self.lyr_sv.scrollTo(0, 0)
        self.lyr_last_y = 0


    @staticmethod
    def _lyr_argb(c):
        return jint(((int(c) & 0xFFFFFFFF) ^ 0x80000000) - 0x80000000)

    def _lyr_ease(self):
        e = getattr(self, "_lyr_ease_obj", None)
        if e is None:
            try:
                f = (lambda v: jfloat(v)) if jfloat is not None else (lambda v: v)
                e = jclass("android.view.animation.PathInterpolator")(f(0.22), f(1.0), f(0.36), f(1.0))
            except Exception:
                e = jclass("android.view.animation.DecelerateInterpolator")()
            self._lyr_ease_obj = e
        return e

    @staticmethod
    def _lyr_target(i, idx):
        d = abs(i - idx)
        if d == 0:
            return 1.0, 1.045
        return max(0.42, 1.0 - 0.17 * d), 1.0

    def _lyr_level(self, i, idx):
        views = self.lyr_views
        if not 0 <= i < len(views):
            return
        a, sc = self._lyr_target(i, idx)
        tv = views[i]
        with tolerated():
            rtl = i < len(getattr(self, "lyr_rtl", ())) and self.lyr_rtl[i]
            tv.setPivotX(float(int(tv.getWidth())) if rtl else 0.0)
            tv.setPivotY(float(int(tv.getHeight())) / 2.0)
            tv.animate().cancel()
            tv.animate().alpha(float(a)).scaleX(float(sc)).scaleY(float(sc)).setDuration(380).setInterpolator(self._lyr_ease()).start()

    def _lyr_color(self, i, to):
        views = self.lyr_views
        if not 0 <= i < len(views):
            return
        tv = views[i]
        prev = self.lyr_coloranim.pop(i, None)
        if prev is not None:
            with tolerated():
                prev.cancel()
        to = self._lyr_argb(to)
        try:
            cur = int(tv.getCurrentTextColor())
            an = jclass("android.animation.ObjectAnimator").ofArgb(tv, "textColor", jarray(jint)([jint(cur), jint(to)]))
            an.setDuration(320)
            an.setInterpolator(self._lyr_ease())
            self.lyr_coloranim[i] = an
            an.start()
        except Exception:
            tv.setTextColor(to)

    def _lyr_style_active(self, idx):
        old = self.lyr_active
        self.lyr_active = idx
        self.lyr_word = -1
        views = self.lyr_views
        lines = self.lyr_data["lines"]
        if 0 <= old < len(views):
            if lines[old]["w"]:
                views[old].setTextColor(self._lyr_argb(self.c_text))
                views[old].setText(lines[old]["text"] or "♪")
            self._lyr_color(old, self._lyr_dim())
        near = set()
        for c in (old, idx):
            near.update(range(c - 4, c + 5))
        for i in near:
            self._lyr_level(i, idx)
        if not (0 <= idx < len(views)):
            return
        line = lines[idx]
        tv = views[idx]
        if line["w"]:
            self._lyr_paint_words(idx, -1)
        else:
            self._lyr_color(idx, self.c_text)
        if not self.lyr_free:
            self._lyr_center(tv)

    def _lyr_max_scroll(self):
        return max(0, int(self.lyr_col.getHeight()) - self._usable_h(self.lyr_sv))

    def _lyr_center(self, tv):
        with tolerated():
            y = int(tv.getTop()) + int(tv.getHeight()) // 2 - self._usable_h(self.lyr_sv) // 2
            self._lyr_scroll_to(y)

    def _lyr_cancel_anim(self):
        an, self.lyr_anim = self.lyr_anim, None
        if an is not None:
            with tolerated():
                an.cancel()

    def _lyr_scroll_to(self, y):
        sv = self.lyr_sv
        y = max(0, min(int(y), self._lyr_max_scroll()))
        cur = int(sv.getScrollY())
        self._lyr_cancel_anim()
        dist = abs(y - cur)
        if dist < self.dp(2):
            return
        try:
            va = _cls("android.animation.ObjectAnimator").ofInt(sv, "scrollY", jarray(jint)([cur, y]))
            va.setInterpolator(self._lyr_ease())
            va.setDuration(int(max(420, min(850, 380 + dist * 0.3))))
            self.lyr_glide_to = y
            self.lyr_anim = va
            va.start()
        except Exception:
            sv.smoothScrollTo(0, y)

    def _lyr_synced(self):
        d = self.lyr_data
        return bool(d) and d["kind"] != "plain"

    def _lyr_touch(self, v, e):
        a = int(e.getActionMasked())
        if a == 0:
            self.lyr_touch, self.lyr_moved = True, False
            self.lyr_down_y = float(e.getRawY())
            self._lyr_cancel_anim()
        elif a == 2:
            if not self.lyr_moved and abs(float(e.getRawY()) - self.lyr_down_y) > self._lyr_slop:
                self.lyr_moved = True
                if self._lyr_synced():
                    self.lyr_free = True
            if self.lyr_moved:
                self.lyr_last_user = time.monotonic()
        elif a in (1, 3):
            self.lyr_touch = False
            if self.lyr_moved:
                self.lyr_last_user = time.monotonic()
        return False

    def _lyr_near_center(self):
        sv, views, idx = self.lyr_sv, self.lyr_views, self.lyr_active
        usable = self._usable_h(sv)
        if 0 <= idx < len(views):
            tv = views[idx]
            want = int(tv.getTop()) + int(tv.getHeight()) // 2 - usable // 2
        else:
            want = 0
        want = max(0, min(want, self._lyr_max_scroll()))
        return abs(int(sv.getScrollY()) - want) <= usable * 0.22

    def _lyr_follow_state(self):
        now = time.monotonic()
        y = int(self.lyr_sv.getScrollY())
        gliding = self.lyr_anim is not None and bool(self.lyr_anim.isRunning())
        if y != self.lyr_last_y and not gliding and y != self.__dict__.get("lyr_glide_to"):
            self.lyr_last_user = now
        self.lyr_last_y = y
        if not self.lyr_free:
            if self.lyr_btn_vis:
                self._lyr_btn_show(False)
            return
        near = self._lyr_near_center()
        if near and not self.lyr_touch and now - self.lyr_last_user > 0.8:
            self._lyr_resync()
        else:
            self._lyr_btn_show(not near)

    def _lyr_resync(self):
        self.lyr_free = False
        self._lyr_btn_show(False)
        idx, views = self.lyr_active, self.lyr_views
        if 0 <= idx < len(views):
            self._lyr_center(views[idx])
        else:
            self._lyr_scroll_to(0)

    def _lyr_btn_show(self, show):
        show = bool(show)
        if show == self.lyr_btn_vis:
            return
        self.lyr_btn_vis = show
        btn, off = self.lyr_btn, float(self.dp(10))
        with tolerated():
            btn.animate().cancel()
            if show:
                self.lyr_btn_bg.setColor(self._lyr_argb(_mix(self.c_bg, self.c_accent, 0.22)))
                self.lyr_btn_icon.setColorFilter(self.c_accent)
                self.lyr_btn_txt.setTextColor(self.c_accent)
                btn.setTranslationY(off)
                btn.setVisibility(0)
                btn.animate().alpha(1.0).translationY(0.0).setDuration(240).setInterpolator(self._lyr_ease()).start()
            else:
                def gone():
                    if not self.lyr_btn_vis:
                        btn.setVisibility(8)
                btn.animate().alpha(0.0).translationY(off).setDuration(160).withEndAction(self.Run(gone)).start()

    def _lyr_sync_insets(self):
        sv = self.lyr_sv
        pt, pb = int(sv.getPaddingTop()), int(sv.getPaddingBottom())
        if (pt, pb) == self.lyr_inset:
            return
        self.lyr_inset = (pt, pb)
        self.lyr_status.setTranslationY((pt - pb) / 2.0)
        lp = self.lyr_btn.getLayoutParams()
        lp.bottomMargin = pb + self.dp(14)
        self.lyr_btn.setLayoutParams(lp)

    def _lyr_paint_words(self, idx, wi):
        line = self.lyr_data["lines"][idx]
        tv = self.lyr_views[idx]
        text = line["text"]
        dim, full = int(self._lyr_dim(True)), int(self.c_text)
        n = len(text)
        ends = _lyr_word_ends(line)
        sung = min(n, ends[min(wi, len(ends) - 1)]) if wi >= 0 and ends else 0
        prev = self.__dict__.get("_lyr_sung")
        before = prev[1] if (prev and prev[0] == idx and prev[1] < sung) else sung
        self._lyr_sung = (idx, sung)
        old = self.__dict__.pop("_lyr_wanim", None)
        if old is not None:
            with tolerated():
                old.cancel()

        def paint(f):
            try:
                sp = jclass("android.text.SpannableString")(text)
                FG = jclass("android.text.style.ForegroundColorSpan")
                if before:
                    sp.setSpan(FG(full), 0, before, 33)
                if sung > before:
                    sp.setSpan(FG(int(_mix(dim, full, f))), before, sung, 33)
                if sung < n:
                    sp.setSpan(FG(dim), sung, n, 33)
                tv.setText(sp)
            except Exception:
                with tolerated():
                    tv.setText(text)
                    tv.setTextColor(self._lyr_argb(full if sung else dim))
        if sung > before:
            try:
                va = _cls("android.animation.ValueAnimator").ofFloat(jarray(jfloat)([0.0, 1.0]))
                va.setDuration(220)
                va.setInterpolator(self._lyr_ease())
                va.addUpdateListener(_anim_proxy()(lambda f: paint(float(f))))
                self._lyr_wanim = va
                paint(0.0)
                va.start()
                return
            except Exception:
                pass
        paint(1.0)

    def _lyr_seek(self, i):
        self.lyr_free = False
        with tolerated():
            mc, pm = self._mini_playing()
            dur = float(pm.getDuration()) * 1000.0
            frac = max(0.0, min(1.0, (self.lyr_data["lines"][i]["t"] + int(getattr(self, "lyr_off", 0))) / dur))
            mc.seekToProgress(pm, jfloat(frac) if jfloat else frac)

    def _frame_touch(self, e) -> bool:
        a = int(e.getActionMasked())
        y = float(e.getY())
        top = float(self.root.getTop())
        if a == 0:
            self._out = (y < top) and self.drag is None and self.sh is None
            return self._out
        if not self._out:
            return False
        if a == 1:
            self._out = False
            if y < top:
                with tolerated():
                    self.dialog.dismiss()
            return True
        if a == 3:
            self._out = False
        return True

    def _on_resize(self):
        with tolerated():
            dm = self.act.getResources().getDisplayMetrics()
            sz = (int(dm.widthPixels), int(dm.heightPixels))
            old = self._screen_sz
            if sz == old:
                return
            self._screen_sz = sz
            def apply():
                with tolerated():
                    self.density = float(dm.density)
                    self.screen_h = sz[1]
                    self.H = self.dp(self.ROW_DP)
                    if self.tabmode:
                        lp = self.root.getLayoutParams()
                        lp.width = _wide_px(self.act, 840) or -1
                        self.root.setLayoutParams(lp)
                    else:
                        self.h_max = int(sz[1] * 0.94)
                        self.h_min = self._calc_min_h()
                        self._set_h(min(self.h_max, max(self.h_min, int(self.cur_h * sz[1] / float(old[1])))))
                        win = self.dialog.getWindow()
                        win.setLayout(self._sheet_w(), self.h_max)
                        win.setGravity(80)
                    self.mini_box.setVisibility(0)
                    self.mini_box.setTranslationY(0.0)
                    if self.tab == "library":
                        self._lib_render()
            self.handler.postDelayed(self.Run(apply), 60)

    def _sheet_w(self):
        return _wide_px(self.act, 600) or -1

    def _calc_min_h(self) -> int:
        with tolerated():
            self.screen_h = int(self.act.getResources().getDisplayMetrics().heightPixels)
        if _wide_px(self.act, 600):
            return int(min(self.screen_h * 0.9, self.h_max))
        try:
            idx = int(self.p.get_setting("sheet_min_height", 4))
        except Exception:
            idx = 4
        pct = 30 + 10 * max(0, min(5, idx))
        h = int(self.screen_h * pct / 100.0)
        floor = self.dp(340)
        try:
            MS = jclass("android.view.View$MeasureSpec")
            w = _wide_px(self.act, 600) or int(self.act.getResources().getDisplayMetrics().widthPixels)
            self.stage.setVisibility(8)
            self.root.measure(MS.makeMeasureSpec(w, 1 << 30), MS.makeMeasureSpec(0, 0))
            fixed = int(self.root.getMeasuredHeight())
            self.stage.setVisibility(0)
            if fixed > 0:
                floor = fixed + int(self.H * 1.5)
        except Exception:
            with tolerated():
                self.stage.setVisibility(0)
        h = max(h, floor)
        return int(min(h, self.h_max - self.dp(40)))

    def _set_h(self, h):
        if self.tabmode:
            return
        self.cur_h = int(h)
        with tolerated():
            FLP = jclass("android.widget.FrameLayout$LayoutParams")
            self.root.setLayoutParams(FLP(-1, int(h), 80))

    def _animate_h(self, target, gone=False, done=None):
        a = self.cur_h
        n = 10
        self._anim_id += 1
        my = self._anim_id
        if gone:
            self._closing = True
        def step(k):
            if self._anim_id != my:
                return
            t = k / float(n)
            e = 1.0 - (1.0 - t) ** 3
            self._set_h(a + (target - a) * e)
            if k < n:
                self.handler.postDelayed(self.Run(lambda: step(k + 1)), 16)
            elif gone:
                with tolerated():
                    self.dialog.dismiss()
            else:
                self._load_visible_covers()
                if done is not None:
                    done()
        step(1)

    def _sd_skip(self, ev):
        g = getattr(self, "grab_view", None)
        if g is None:
            return False
        return _hit(g, float(ev.getRawX()), float(ev.getRawY()))

    def _grab_touch(self, v, e):
        a = int(e.getActionMasked())
        ry, t = float(e.getRawY()), int(e.getEventTime())
        if a == 0:
            self._gr = {"ly": ry, "t": t, "v": 0.0}
            self._sd_begin()
            return True
        g = getattr(self, "_gr", None)
        if g is None:
            return False
        if a == 2:
            dy = ry - g["ly"]
            g["v"] = 0.5 * g["v"] + 0.5 * dy / max(1, t - g["t"]) * 1000.0
            g["ly"], g["t"] = ry, t
            if dy:
                self._sd_move(dy)
            return True
        if a in (1, 3):
            self._gr = None
            self._sd_end(g["v"] if a == 1 else 0.0)
        return True

    def _sd_can_start(self):
        return self.sized and self.drag is None and not self._closing

    def _sd_can_up(self):
        return self.cur_h < self.h_max - 2

    def _sd_defer_expand(self):
        try:
            if getattr(self, "tab", "queue") != "queue":
                return False
            if bool(getattr(self, "queue_load_pending", False)):
                return True
            items = getattr(self, "items", ()) or ()
            if int(getattr(self, "win_end", len(items))) < len(items):
                try:
                    self._show_later()
                except Exception:
                    with tolerated():
                        pass
                return True
        except Exception:
            with tolerated():
                pass
        return False

    def _sd_begin(self):
        self._anim_id += 1

    def _sd_move(self, dy):
        self._set_h(max(self.dp(96), min(self.h_max, self.cur_h - dy)))

    def _sd_end(self, vel):
        h = self.cur_h
        lo, hi = self.h_min, self.h_max
        if vel > 1500:
            tgt = lo if h > lo + self.dp(8) else 0
        elif vel < -1500:
            tgt = hi
        elif h < lo * 0.65:
            tgt = 0
        elif h > (lo + hi) / 2.0:
            tgt = hi
        else:
            tgt = lo
        if tgt == 0:
            self._animate_h(self.dp(40), gone=True)
        else:
            self._animate_h(tgt)

    def _scroll_to_playing(self, attempt=0):
        self.queue_lazy_ready = True
        if self._current_row_visible():
            return
        if self.queue_load_pending:
            if attempt < 20:
                self.handler.postDelayed(self.Run(lambda: self._scroll_to_playing(attempt + 1)), 60)
            return
        pos = self._playing_pos()
        if pos < 0:
            if attempt < 8:
                self.handler.postDelayed(self.Run(lambda: self._scroll_to_playing(attempt + 1)), 90)
            return
        if pos < self.win_start or pos >= self.win_end:
            self._refresh(reset_loaded_range=True)
            self._snap_to_playing_predraw()
            self.handler.postDelayed(self.Run(lambda: self._scroll_to_playing(attempt + 1)), 70)
            return
        if not self._current_row_visible():
            self._smooth_scroll_to_position(pos)

    def _follow_playing(self):
        self.queue_lazy_ready = True
        pos = self._playing_pos()
        if (getattr(self, "tab", "queue") == "queue" and not self.queue_load_pending
                and 0 <= pos and self.win_start <= pos < self.win_end):
            self._smooth_scroll_to_position(pos)
            self._loc_fade(False)
        else:
            self._scroll_to_playing()

    def _usable_h(self, sv, fallback=0):
        h = int(sv.getHeight())
        if h <= 0:
            return fallback
        return max(1, h - int(sv.getPaddingTop()) - int(sv.getPaddingBottom()))

    def _snap_to_playing_predraw(self):
        with tolerated():
            pos = self._playing_pos()
            if pos < 0 or pos < self.win_start or pos >= self.win_end:
                return
            holder = []
            def pre_draw():
                with tolerated():
                    vto = self.scroll.getViewTreeObserver()
                    if holder:
                        vto.removeOnPreDrawListener(holder[0])
                    viewport = self._usable_h(self.scroll)
                    if viewport > 0:
                        y = (pos - self.win_start) * self.H - max(0, (viewport - self.H) // 2)
                        self.scroll.scrollTo(0, max(0, int(y)))
                return True
            pd = _proxy("android.view.ViewTreeObserver$OnPreDrawListener", "onPreDraw", ret=True)(pre_draw)
            holder.append(pd)
            self.scroll.getViewTreeObserver().addOnPreDrawListener(pd)

    def _smooth_scroll_to_position(self, pos):
        with tolerated():
            row_index = max(0, pos - self.win_start)
            viewport = self._usable_h(self.scroll)
            if viewport <= 0:
                viewport = self.dp(self.ROW_DP * 3.5)
            y = max(0, int(row_index * self.H - max(0, (viewport - self.H) // 2)))
            if abs(y - int(self.scroll.getScrollY())) > self.dp(4):
                self.scroll.smoothScrollTo(0, y)

    def _locate_current(self):
        pos = self._playing_pos()
        if pos < 0:
            return
        if pos < self.win_start or pos >= self.win_end:
            self._refresh(reset_loaded_range=True)
            self._snap_to_playing_predraw()
            self.handler.postDelayed(self.Run(self._scroll_to_playing), 70)
        else:
            self._smooth_scroll_to_position(pos)
        self._loc_fade(False)

    def _current_row_visible(self):
        pos = self._playing_pos()
        if pos < 0 or pos < self.win_start or pos >= self.win_end:
            return False
        try:
            height = self._usable_h(self.scroll)
            if height <= 0:
                return True
            top = int(self.scroll.getScrollY())
            row_top = (pos - self.win_start) * self.H
            return (row_top + self.H > top) and (row_top < top + height)
        except Exception:
            return True

    def _loc_fade(self, show):
        button = getattr(self, "mini_locate", None)
        if button is None:
            return
        with tolerated():
            vis = int(button.getVisibility()) == 0
            if show:
                self._loc_hiding = False
                if not vis:
                    button.animate().cancel()
                    button.setAlpha(0.0)
                    button.setVisibility(0)
                button.animate().alpha(1.0).setDuration(160).start()
            else:
                if not vis or getattr(self, "_loc_hiding", False):
                    return
                self._loc_hiding = True
                def done():
                    self._loc_hiding = False
                    button.setVisibility(8)
                    button.setAlpha(1.0)
                button.animate().cancel()
                button.animate().alpha(0.0).setDuration(160).withEndAction(self.Run(done)).start()

    def _update_locate_visibility(self):
        button = getattr(self, "mini_locate", None)
        if button is None:
            return
        with tolerated():
            _, pm = self._mini_playing()
            visible = pm is not None and (self.tab != "queue" or self._current_row_visible())
            want = pm is not None and not visible
            self._loc_want = want
            if not want:
                self._loc_fade(False)
            elif getattr(self, "_mini_anim", None) is not None:
                self._loc_fade(True)
            else:
                hidden_small = bool(getattr(self, "_mini_hid", False)) and not self._mo("mini_show_locate")
                self._loc_fade(not hidden_small)

    def _mini_fit_text(self):
        with tolerated():
            tc = getattr(self, "mini_tcol", None)
            ts = getattr(self, "_mini_ts", None)
            if tc is None or ts is None:
                return
            w = int(tc.getWidth())
            if w <= 0:
                return
            lp = self.mini_title.getLayoutParams()
            want = int(w / ts[0])
            if int(lp.width) != want:
                lp.width = want
                self.mini_title.setLayoutParams(lp)
            sw = int(w / ts[1])
            if int(self.mini_sub.getMaxWidth()) != sw:
                self.mini_sub.setMaxWidth(sw)

    def _mini_pin_lines(self, e):
        with tolerated():
            self.mini_title.setLineHeight(int(self.dp(22)))
            self.mini_sub.setLineHeight(int(self.dp(18)))

    def _mo(self, key):
        try:
            return bool(self.p._mini_opt(key))
        except Exception:
            return key == "mini_show_prev"

    def _mini_refresh_opts(self):
        with tolerated():
            if getattr(self, "mini_box", None) is None or getattr(self, "_mini_anim", None) is not None:
                return
            self._mini_finish(bool(getattr(self, "_mini_hid", False)))

    def _mini_cbtns(self):
        return ((self.mini_cprev, 34, 0, 3), (self.mini_cplay, 38, 5, 5), (self.mini_cnext, 34, 3, 3))

    def _mini_layout(self, e):
        self._mini_e = e
        box = self.mini_box
        dp = self.dp
        lerp = lambda a, b: a + (b - a) * e
        a_exp = max(0.0, min(1.0, (e - 0.35) / 0.65))
        size = dp(lerp(44, 92))
        with tolerated():
            gp = dp(lerp(9, 26))
            if gp != getattr(self, "_mini_glyph_pad", None):
                self._mini_glyph_pad = gp
                self.mini_glyph.setPadding(gp, gp, gp, gp)
        lp = self.mini_cov.getLayoutParams()
        lp.width = size
        lp.height = size
        self.mini_cov.setLayoutParams(lp)
        lp = self.mini_col.getLayoutParams()
        full = max(dp(92), int(getattr(self, "_col_h1", 0) or 0))
        lp.height = -2 if e >= 0.999 else int(dp(44) + (full - dp(44)) * e)
        self.mini_col.setLayoutParams(lp)
        h1 = int(getattr(self, "_head_h1", 0) or 0)
        lp = self.mini_head.getLayoutParams()
        lp.height = -2 if e >= 0.999 else (dp(44) if (e <= 0.001 or not h1) else int(h1 + (dp(44) - h1) * (1.0 - e)))
        self.mini_head.setLayoutParams(lp)
        box.setPadding(dp(lerp(12, 16)), dp(lerp(6, 12)), dp(lerp(12, 16)), dp(6))
        st = lerp(15.0 / 18.0, 1.0)
        ss = lerp(12.0 / 14.0, 1.0)
        self._mini_ts = (st, ss)
        for tv, sc, full, slot in ((self.mini_title, st, 22, 18 + 4 * e),
       (self.mini_sub, ss, 18, 15 + 3 * e)):
            tv.setPivotX(0.0)
            tv.setPivotY(0.0)
            tv.setScaleX(float(sc))
            tv.setScaleY(float(sc))
            lp = tv.getLayoutParams()
            lp.setMargins(int(lp.leftMargin), int(lp.topMargin), int(lp.rightMargin), dp(slot) - dp(full))
            tv.setLayoutParams(lp)
        self._mini_fit_text()
        for v, w0, ml0, mr0 in self._mini_cbtns():
            lp = v.getLayoutParams()
            lp.width = dp(w0)
            lp.setMargins(dp(ml0 * (1 - e) - w0 * e), 0, dp(mr0 * (1 - e)), 0)
            v.setLayoutParams(lp)
            v.setAlpha(1.0 if e < 0.999 else 0.0)
        if getattr(self, "mini_locate", None) is not None:
            lp = self.mini_locate.getLayoutParams()
            if self._mo("mini_show_locate"):
                lp.width = dp(40)
                self.mini_locate.setAlpha(1.0)
            else:
                lp.width = dp(40 * e)
                self.mini_locate.setAlpha(float(e))
            self.mini_locate.setLayoutParams(lp)
        lp = self.mini_like_btn.getLayoutParams()
        if self._mo("mini_show_like"):
            lp.width = dp(34 + 6 * e)
            like_a = float(getattr(self, "_like_rest_a", 1.0))
        else:
            lp.width = dp(40 * e)
            like_a = e
        lp.setMargins(dp(3 * (1 - e)), 0, 0, 0)
        self.mini_like_btn.setLayoutParams(lp)
        self.mini_like_btn.setTranslationX(0.0)
        self.mini_like_btn.setAlpha(float(like_a))
        for v in (self.mini_bar, self.mini_times, self.mini_ctl):
            v.setAlpha(a_exp)
        xa = 1.0 if e >= 0.999 else 0.0
        for fl in getattr(self, "_fly", ()):
            if fl[0] is self.mini_cprev and not self._mo("mini_show_prev"):
                fl[1].setAlpha(float(a_exp))
                sc = 0.6 + 0.4 * a_exp
                fl[1].setScaleX(float(sc))
                fl[1].setScaleY(float(sc))
            else:
                fl[1].setAlpha(xa)
        lp = self.mini_ctl.getLayoutParams()
        lp.height = -2 if e >= 1.0 else dp(66 * e)
        self.mini_ctl.setLayoutParams(lp)
        lp = self.mini_bar.getLayoutParams()
        lp.height = dp(24 * e)
        self.mini_bar.setLayoutParams(lp)
        self._mini_fill_update()

    def _mini_fill_update(self):
        clip = getattr(self, "mini_fill", None)
        if clip is None:
            return
        with tolerated():
            frac = max(0.0, min(1.0, float(getattr(self, "_mini_frac", 0.0))))
            if getattr(self, "_mini_anim", None) is not None:
                k = 1.0 - max(0.0, min(1.0, float(getattr(self, "_mini_e", 1.0))))
            else:
                k = 1.0 if getattr(self, "_mini_hid", False) else 0.0
            target = int(frac * k * 10000)
            anim = getattr(self, "_fill_anim", None)
            if anim is not None:
                with tolerated():
                    anim.cancel()
                self._fill_anim = None
            cur = int(clip.getLevel())
            if k < 1.0 or getattr(self, "_mini_anim", None) is not None or abs(target - cur) < 1 \
          or abs(target - cur) > 300 or target < cur:
                clip.setLevel(target)
                return
            va = _cls("android.animation.ValueAnimator").ofFloat(jarray(jfloat)([0.0, 1.0]))
            va.setDuration(520)
            va.setInterpolator(_cls("android.view.animation.LinearInterpolator")())
            def upd(f, c0=cur, c1=target):
                clip.setLevel(int(c0 + (c1 - c0) * f))
            va.addUpdateListener(_anim_proxy()(upd))
            self._fill_anim = va
            va.start()

    def _fly_center(self, v, chain):
        x = int(v.getLeft())
        y = int(v.getTop())
        for p in chain:
            x += int(p.getLeft())
            y += int(p.getTop())
        loc = jarray(jint)([0, 0])
        self.mini_box.getLocationInWindow(loc)
        return x + int(loc[0]) + int(v.getWidth()) / 2.0, y + int(loc[1]) + int(v.getHeight()) / 2.0

    def _fly_chains(self, cell, grp):
        return (self.mini_head, self.mini_col, self.mini_top), (cell, grp, self.mini_ctl)

    def _mini_capture(self):
        with tolerated():
            e = float(getattr(self, "_mini_e", 1.0))
            if getattr(self, "_mini_anim", None) is not None:
                return
            pos = self.__dict__.setdefault("_fpos", {})
            for i, (c, xv, cell, grp) in enumerate(getattr(self, "_fly", ())):
                cc, xc = self._fly_chains(cell, grp)
                if e >= 0.999 and int(xv.getWidth()) > 0:
                    pos[(i, "x")] = self._fly_center(xv, xc)
                    if int(self.mini_head.getHeight()) > 0:
                        self._head_h1 = int(self.mini_head.getHeight())
                    if int(self.mini_col.getHeight()) > 0:
                        self._col_h1 = int(self.mini_col.getHeight())
                elif e <= 0.001 and int(c.getWidth()) > 0:
                    pos[(i, "c")] = self._fly_center(c, cc)

    def _mini_fly(self):
        e = float(getattr(self, "_mini_e", 1.0))
        pos = self.__dict__.setdefault("_fpos", {})
        q = max(0.0, min(1.0, 1.0 - e))
        qs = q
        for i, (c, xv, cell, grp) in enumerate(getattr(self, "_fly", ())):
            cw = int(c.getWidth())
            xw = int(xv.getWidth())
            if cw <= 0 or xw <= 0:
                continue
            cc, xc = self._fly_chains(cell, grp)
            cx, cy = self._fly_center(c, cc)
            if e <= 0.001:
                pos[(i, "c")] = (cx, cy)
            if e >= 0.999:
                pos[(i, "x")] = self._fly_center(xv, xc)
                if int(self.mini_head.getHeight()) > 0:
                    self._head_h1 = int(self.mini_head.getHeight())
                if int(self.mini_col.getHeight()) > 0:
                    self._col_h1 = int(self.mini_col.getHeight())
            ax, ay = pos.get((i, "x")) or self._fly_center(xv, xc)
            bx, by = pos.get((i, "c")) or (cx, cy)
            c.setTranslationX(float(ax + (bx - ax) * qs - cx))
            c.setTranslationY(float(ay + (by - ay) * qs - cy))
            if i == 0:
                k = xw / float(cw)
            elif "RLottie" in str(xv.getClass().getName()):
                k = 1.0
            else:
                k = (xw - int(xv.getPaddingLeft()) * 2) / float(max(1, cw - int(c.getPaddingLeft()) * 2))
            sc = k + (1.0 - k) * qs
            c.setScaleX(float(sc))
            c.setScaleY(float(sc))

    def _mini_fly_stop(self):
        lst = getattr(self, "_mini_pd", None)
        if lst is not None:
            self._mini_pd = None
            with tolerated():
                self.mini_box.getViewTreeObserver().removeOnPreDrawListener(lst)

    def _mini_fly_reset(self):
        self._mini_fly_stop()
        for c, xv, _cell, _grp in getattr(self, "_fly", ()):
            for v, a in ((c, None), (xv, 1.0)):
                v.setTranslationX(0.0)
                v.setTranslationY(0.0)
                v.setScaleX(1.0)
                v.setScaleY(1.0)
                if a is not None:
                    v.setAlpha(a)

    def _mini_finish(self, compact):
        self._mini_fly_reset()
        with tolerated():
            self.handler.postDelayed(self.Run(self._mini_capture), 80)
        vis_exp = 8 if compact else 0
        vis_cmp = 0 if compact else 8
        for v in (self.mini_bar, self.mini_spacer, self.mini_times, self.mini_ctl):
            v.setVisibility(vis_exp)
        show_like = self._mo("mini_show_like")
        with tolerated():
            lp = self.mini_locate.getLayoutParams()
            lp.width = self.dp(40)
            self.mini_locate.setLayoutParams(lp)
            self.mini_locate.setAlpha(1.0)
            if compact and not self._mo("mini_show_locate"):
                self.mini_locate.animate().cancel()
                self.mini_locate.setVisibility(8)
                self._loc_hiding = False
            self._update_locate_visibility()
        self.mini_like_btn.setVisibility(8 if (compact and not show_like) else 0)
        for v in (self.mini_cprev, self.mini_cplay, self.mini_cnext):
            v.setVisibility(8 if (v is self.mini_cprev and not self._mo("mini_show_prev")) else vis_cmp)
        self.mini_sub.setClickable(not compact)
        self.mini_like_btn.setTranslationX(0.0)
        lp = self.mini_like_btn.getLayoutParams()
        lp.width = self.dp(34 if compact else 40)
        lp.setMargins(self.dp(3 if compact else 0), 0, 0, 0)
        self.mini_like_btn.setLayoutParams(lp)
        for v, w0, ml0, mr0 in self._mini_cbtns():
            lp = v.getLayoutParams()
            lp.width = self.dp(w0)
            lp.setMargins(self.dp(ml0), 0, self.dp(mr0), 0)
            v.setLayoutParams(lp)
        with tolerated():
            self.mini_head.setClipChildren(True)
        self.mini_like_btn.setAlpha(float(getattr(self, "_like_rest_a", 1.0)))
        for v in (self.mini_cprev, self.mini_cplay, self.mini_cnext):
            v.setAlpha(1.0)
        lp = self.mini_col.getLayoutParams()
        lp.height = self.dp(44) if compact else -2
        self.mini_col.setLayoutParams(lp)
        lp = self.mini_head.getLayoutParams()
        lp.height = self.dp(44) if compact else -2
        self.mini_head.setLayoutParams(lp)
        lp = self.mini_bar.getLayoutParams()
        lp.height = self.dp(24)
        self.mini_bar.setLayoutParams(lp)
        lp = self.mini_ctl.getLayoutParams()
        lp.height = -2
        self.mini_ctl.setLayoutParams(lp)

    def _mini_measure_expanded(self):
        e0 = float(getattr(self, "_mini_e", 1.0))
        try:
            bw = int(self.mini_box.getWidth())
            colw = bw - self.dp(32) - self.dp(92)
            if bw <= 0 or colw <= 0:
                return
            MS = _cls("android.view.View$MeasureSpec")
            self._mini_layout(1.0)
            exact = int(MS.makeMeasureSpec(colw, 1073741824))
            free = int(MS.makeMeasureSpec(0, 0))
            self.mini_col.measure(exact, free)
            ch = int(self.mini_col.getMeasuredHeight())
            self.mini_head.measure(int(MS.makeMeasureSpec(colw - self.dp(14), 1073741824)), free)
            hh = int(self.mini_head.getMeasuredHeight())
            if ch > 0:
                self._col_h1 = ch
            if hh > 0:
                self._head_h1 = hh
        except Exception:
            pass
        finally:
            with tolerated():
                self._mini_layout(e0)

    def _mini_apply(self, compact, animate=True, save=True):
        compact = bool(compact)
        self._mini_hid = compact
        if save:
            with tolerated():
                self.p.set_setting("mini_compact", compact)
        box = getattr(self, "mini_box", None)
        if box is None or getattr(self, "mini_cplay", None) is None:
            return
        try:
            old = getattr(self, "_mini_anim", None)
            if old is not None:
                with tolerated():
                    old.cancel()
                self._mini_anim = None
            start = float(getattr(self, "_mini_e", 1.0))
            target = 0.0 if compact else 1.0
            if start >= 0.999 and int(self.mini_col.getHeight()) > 0:
                self._col_h1 = int(self.mini_col.getHeight())
            self._mini_pp_snap()
            for v in (self.mini_bar, self.mini_spacer, self.mini_times, self.mini_ctl, self.mini_like_btn,
          self.mini_cprev, self.mini_cplay, self.mini_cnext):
                if v is self.mini_cprev and not self._mo("mini_show_prev"):
                    v.setVisibility(8)
                    continue
                v.setVisibility(0)
            if getattr(self, "_loc_want", False):
                self.mini_locate.setVisibility(0)
            self.mini_sub.setClickable(not compact)
            self.mini_ctl.setClipChildren(True)
            self.mini_col.setClipChildren(False)
            with tolerated():
                self.mini_head.setClipChildren(False)
            if animate and start != target:
                self._mini_measure_expanded()
            if not animate or start == target:
                self._mini_layout(target)
                self._mini_finish(compact)
                self.mini_ctl.setClipChildren(False)
                return
            anim = _cls("android.animation.ValueAnimator").ofFloat(jarray(jfloat)([0.0, 1.0])) \
          if jfloat else _cls("android.animation.ValueAnimator").ofFloat(0.0, 1.0)
            anim.setDuration(320)
            try:
                anim.setInterpolator(_cls("android.view.animation.PathInterpolator")(0.4, 0.0, 0.2, 1.0))
            except Exception:
                with tolerated():
                    anim.setInterpolator(_cls("android.view.animation.AccelerateDecelerateInterpolator")())
            def on_update(f):
                if getattr(self, "_mini_anim", None) is not anim:
                    return
                self._mini_layout(start + (target - start) * f)
                if f >= 1.0:
                    self._mini_anim = None
                    self._mini_finish(compact)
                    self.mini_ctl.setClipChildren(False)
            anim.addUpdateListener(_anim_proxy()(on_update))
            self._mini_anim = anim
            self._mini_fly_stop()
            def pre_draw():
                with tolerated():
                    self._mini_fly()
                return True
            pd = _proxy("android.view.ViewTreeObserver$OnPreDrawListener", "onPreDraw", ret=True)(pre_draw)
            self._mini_pd = pd
            box.getViewTreeObserver().addOnPreDrawListener(pd)
            anim.start()
        except Exception:
            with tolerated():
                self._mini_layout(0.0 if compact else 1.0)
                self._mini_finish(compact)

    def _mini_follow(self, sv):
        return

    def _on_scroll(self):
        self._mini_follow(self.scroll)
        self._last_scroll_change = time.monotonic()
        now = self._last_scroll_change
        if now - getattr(self, "_last_scroll_cover_work", 0.0) >= 0.10:
            self._last_scroll_cover_work = now
            self._load_visible_covers()
            self._update_locate_visibility()
        try:
            old = getattr(self, "_queue_scroll_check", None)
            if old is not None:
                self.handler.removeCallbacks(old)
            self._queue_scroll_check = self.Run(self._maybe_load_queue_rows)
            if now - getattr(self, "_last_queue_check", 0.0) >= 0.04:
                self._last_queue_check = now
                self._maybe_load_queue_rows()
            self.handler.postDelayed(self._queue_scroll_check, 50)
        except Exception:
            self._maybe_load_queue_rows()

    def _maybe_load_queue_rows(self):
        if (not self.queue_lazy_ready or self.queue_load_pending or
       self.drag is not None or self.tab != "queue"):
            return
        with tolerated():
            y = int(self.scroll.getScrollY())
            vh = int(self.scroll.getHeight())
            content_h = int(self.container.getHeight())
            if vh <= 0 or not self.items:
                return
            edge = self.H * self.QUEUE_EDGE_ROWS
            if y <= edge and self.win_start > 0:
                self._show_earlier()
            elif y + vh + edge >= content_h and self.win_end < len(self.items):
                self._show_later()

    def _restore_scroll(self, y):
        self.handler.postDelayed(self.Run(lambda: self.scroll.scrollTo(0, int(y))), 30)

    def _choose_initial_loaded_range(self, pi):
        n = len(self.items)
        if n <= 0:
            self.win_start, self.win_end = 0, 0
            return
        current = pi if 0 <= pi < n else 0
        if n > self.QUEUE_BATCH_ROWS:
            start = max(0, min(n - self.QUEUE_BATCH_ROWS,
          current - self.QUEUE_BATCH_ROWS // 2))
            self.win_start = start
            self.win_end = min(n, start + self.QUEUE_BATCH_ROWS)
        else:
            self.win_start, self.win_end = 0, n

    def _show_earlier(self):
        if self.queue_load_pending or self.win_start <= 0:
            return
        old_start = self.win_start
        new_start = max(0, old_start - self.QUEUE_PREPEND_ROWS)
        self.queue_load_pending = True
        token = self.queue_data_token
        def ready():
            if token != self.queue_data_token:
                return
            self._prepend_queue_rows(new_start, old_start)
            self.queue_load_pending = False
            self._prefetch_queue_neighbors()
            self.handler.postDelayed(self.Run(self._load_visible_covers), 30)
            self.handler.postDelayed(self.Run(self._maybe_load_queue_rows), 16)
        self._prefetch_queue_rows(new_start, old_start, ready)

    def _show_later(self):
        if self.queue_load_pending or self.win_end >= len(self.items):
            return
        old_end = self.win_end
        new_end = min(len(self.items), old_end + self.QUEUE_BATCH_ROWS)
        self.queue_load_pending = True
        token = self.queue_data_token
        def finished():
            if token != self.queue_data_token:
                return
            self.queue_load_pending = False
            self._prefetch_queue_neighbors()
            self.handler.postDelayed(self.Run(self._load_visible_covers), 30)
            self.handler.postDelayed(self.Run(self._maybe_load_queue_rows), 16)
        def ready():
            if token != self.queue_data_token:
                return
            self._append_queue_rows(old_end, new_end, finished)
        self._prefetch_queue_rows(old_end, new_end, ready)

    def _prefetch_queue_rows(self, start, end, callback=None):
        start = max(0, int(start))
        end = min(len(self.items), max(start, int(end)))
        token = self.queue_data_token
        snapshot = [(i, self.items[i], self._key(self.items[i]))
       for i in range(start, end)]
        missing = []
        for i, m, key in snapshot:
            if key is None:
                continue
            if key not in self.row_meta_cache or key not in self.dl_cache:
                missing.append((i, m, key))
        if not missing:
            if callback is not None:
                callback()
            return
        def worker():
            prepared = {}
            statuses = {}
            with tolerated():
                for i, m, key in missing:
                    try:
                        if key not in self.row_meta_cache:
                            prepared[key] = {
                      "title": self._title_of(m),
                      "author": self._author_of(m),
                      }
                    except Exception:
                        prepared[key] = {"title": "Audio", "author": ""}
                    try:
                        if key not in self.dl_cache:
                            if self.p._is_downloaded(m):
                                statuses[key] = 2
                            elif self.p._unavailable(m):
                                statuses[key] = 3
                            elif self.p._is_loading(m):
                                statuses[key] = 1
                            else:
                                statuses[key] = 0
                    except Exception:
                        statuses[key] = 0
            def finish_on_ui():
                if token != self.queue_data_token:
                    return
                self.row_meta_cache.update(prepared)
                for key, state in statuses.items():
                    if self.dl_cache.get(key) != 2:
                        self.dl_cache[key] = state
                if callback is not None:
                    callback()
            try:
                posted = self.handler.post(self.Run(finish_on_ui))
                if not posted:
                    run_on_ui_thread(finish_on_ui)
            except Exception:
                with tolerated():
                    run_on_ui_thread(finish_on_ui)
        try:
            Thread = jclass("java.lang.Thread")
            t = Thread(self.Run(worker))
            t.setName("MusicPlus-row-prefetch")
            t.setDaemon(True)
            t.start()
        except Exception:
            worker()

    def _prefetch_queue_neighbors(self):
        if not self.items:
            return
        if self.win_start > 0:
            self._prefetch_queue_rows(max(0, self.win_start - self.QUEUE_PREPEND_ROWS), self.win_start)
        if self.win_end < len(self.items):
            self._prefetch_queue_rows(self.win_end, min(len(self.items), self.win_end + self.QUEUE_BATCH_ROWS))

    def _restyle_queue_edges(self, indices):
        pi = self._playing_pos()
        for i in set(int(x) for x in indices):
            if i < self.win_start or i >= self.win_end:
                continue
            r = self.row_refs.get(i)
            if not r:
                continue
            first = (i == self.win_start)
            last = (i == self.win_end - 1)
            if r.get("first", False) != first or r.get("last", False) != last:
                r["first"] = first
                r["last"] = last
                self._apply_sel(r)
            self._style_row(i, pi)

    def _prepend_queue_rows(self, new_start, old_start):
        if new_start >= old_start:
            return
        old_y = int(self.scroll.getScrollY())
        self.win_start = int(new_start)
        new_rows = []
        for i in range(new_start, old_start):
            row = self._make_row(i, self.items[i], self._playing_pos())
            insert_at = len(new_rows)
            self.container.addView(row, insert_at, self.LP(-1, self.H))
            new_rows.append(row)
        self.rows = new_rows + self.rows
        self._restyle_queue_edges((old_start,))
        self._update_title()
        if not self.sized:
            lp = self.stage.getLayoutParams()
            lp.height = min(max(1, len(self.rows)) * self.H, int(self.screen_h * 0.38))
            self.stage.setLayoutParams(lp)
        self._restore_scroll(max(0, old_y + (old_start - new_start) * self.H))
        self._update_locate_visibility()

    def _append_queue_rows(self, old_end, new_end, done=None, mark=None, on_mark=None):
        if new_end <= old_end:
            if done is not None:
                done()
            return
        token = self.queue_data_token
        chunk = max(1, int(self.QUEUE_CHUNK_ROWS))
        cur = int(old_end)
        target = int(new_end)

        def step():
            nonlocal cur
            if token != self.queue_data_token:
                return
            nonlocal on_mark
            stop = min(target, cur + chunk)
            pi = self._playing_pos()
            first = cur
            budget = self.__dict__.get("_row_budget")
            fade = bool(self.__dict__.get("_fade_rows"))
            t0 = time.monotonic()
            i = cur
            while i < stop:
                row = self._make_row(i, self.items[i], pi)
                self.container.addView(row, self.LP(-1, self.H))
                self.rows.append(row)
                if fade:
                    with tolerated():
                        row.setAlpha(0.0)
                        row.animate().alpha(1.0).setDuration(160).start()
                i += 1
                if budget and time.monotonic() - t0 > budget:
                    break
            cur = i
            self.win_end = cur
            self._restyle_queue_edges((first - 1, cur - 1))
            self._update_title()
            if not self.sized:
                lp = self.stage.getLayoutParams()
                lp.height = min(max(1, len(self.rows)) * self.H, int(self.screen_h * 0.38))
                self.stage.setLayoutParams(lp)
            if on_mark is not None and cur >= mark:
                cb, on_mark = on_mark, None
                cb()
            if cur < target:
                self.handler.post(self.Run(step))
            else:
                self._update_locate_visibility()
                if done is not None:
                    done()
        step()

    def _refresh(self, reset_loaded_range=True, scroll_to=None):
        self.queue_data_token += 1
        self.__dict__.pop("_fade_rows", None)
        self.__dict__.pop("_row_budget", None)
        self.queue_load_pending = False
        if self.sel:
            before = len(self.sel)
            self.sel &= {self._key(m) for m in self.items}
            if before and not self.sel:
                self._set_sel_mode(False)
        pi = self._playing_pos()
        self._rf_sig_new = None
        if reset_loaded_range and scroll_to is None and self.items and not self.sel_mode and self.drag is None:
            try:
                sig = (hash(tuple(self.keys)), self.ghost, pi, self.tab, bool(self.reversed))
                now = time.monotonic()
                if sig == getattr(self, "_rf_sig", None) and now - getattr(self, "_rf_t", 0.0) < 1.5 \
             and int(self.container.getChildCount()) > 0:
                    self._update_title()
                    return
                self._rf_sig, self._rf_t = sig, now
            except Exception:
                self._rf_sig = None
        else:
            self._rf_sig = None
        if reset_loaded_range or self.win_end <= self.win_start:
            self._choose_initial_loaded_range(pi)
        self.container.removeAllViews()
        with tolerated():
            self.scroll.setFillViewport(False)
        self.rows = []
        self.row_refs = {}
        full_end = self.win_end
        staged = bool(self.__dict__.pop("_fast_first", False)) and full_end - self.win_start > 12
        if staged:
            self.win_end = self.win_start
            self.queue_load_pending = True
            _tok, _from = self.queue_data_token, self.win_start
            revealed = [False]
            view_rows = max(6, int(self.screen_h // max(1, self.H)) + 1)
            anchor = pi if _from <= pi < full_end else _from
            reveal_at = min(full_end, anchor + view_rows // 2 + 4)
            def _reveal():
                if revealed[0] or _tok != self.queue_data_token:
                    return
                revealed[0] = True
                self._snap_to_playing_predraw()
                self._fade_rows = True
                self._queue_loading_hide()
                self.handler.postDelayed(self.Run(self._load_visible_covers), 40)
            def _fill():
                if _tok != self.queue_data_token:
                    return
                def _done():
                    if _tok != self.queue_data_token:
                        return
                    for k in ("QUEUE_CHUNK_ROWS", "_row_budget", "_fade_rows"):
                        self.__dict__.pop(k, None)
                    self.queue_load_pending = False
                    _reveal()
                    self.handler.postDelayed(self.Run(self._load_visible_covers), 80)
                self.QUEUE_CHUNK_ROWS = 12
                self._row_budget = 0.006
                self._append_queue_rows(_from, full_end, _done, reveal_at, _reveal)
            self.handler.post(self.Run(_fill))
        else:
            if getattr(self, "_resuming", False) and not self.items:
                self._queue_loading_show_once()
            else:
                self._queue_loading_hide()
            for i in range(self.win_start, self.win_end):
                row = self._make_row(i, self.items[i], pi)
                self.container.addView(row, self.LP(-1, self.H))
                self.rows.append(row)
        self._styled_playing = pi
        self._ghost_render()
        if not self.items and self.tab == "queue" and not getattr(self, "_resuming", False):
            with tolerated():
                self.scroll.setFillViewport(True)
                self.container.addView(self._empty_view(), self.LP(-1, -1))
        self._update_title()
        if not self.sized:
            lp = self.stage.getLayoutParams()
            lp.height = min(max(1, len(self.rows)) * self.H, int(self.screen_h * 0.38))
            self.stage.setLayoutParams(lp)
        if scroll_to is not None:
            self._restore_scroll(scroll_to)
        self._prefetch_queue_neighbors()
        self.handler.postDelayed(self.Run(self._load_visible_covers), 60)

    def _empty_view(self):
        LL = _cls("android.widget.LinearLayout")
        FL = _cls("android.widget.FrameLayout")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        box = LL(self.act)
        box.setOrientation(1)
        box.setGravity(17)
        box.setPadding(self.dp(32), self.dp(24), self.dp(32), self.dp(24))
        soft = (self.c_accent & 0x00FFFFFF) | 0x26000000
        bubble = FL(self.act)
        bg = GD()
        bg.setShape(1)
        bg.setColor(soft)
        bubble.setBackground(bg)
        bubble.addView(self._glyph_icon(("msg_media", "msg_music", "player_new_play"), self.c_accent, pad=22, size=34, bold=True),
       _cls("android.widget.FrameLayout$LayoutParams")(-1, -1))
        box.addView(bubble, self.LP(self.dp(88), self.dp(88)))
        t = self._text(strings("nothing_in_your_queue"), 20, self.c_text, bold=True, gravity=17)
        t.setPadding(0, self.dp(20), 0, self.dp(6))
        box.addView(t, self.LP(-2, -2))
        sub = self._text(strings("play_a_track_from_any_chat"), 14, self.c_sub, gravity=17)
        sub.setLineSpacing(0.0, 1.15)
        box.addView(sub, self.LP(-2, -2))
        btn = self._text(strings("open_library"), 15, -1, bold=True, gravity=17)
        pill = GD()
        pill.setCornerRadius(float(self.dp(22)))
        pill.setColor(self.c_accent)
        btn.setBackground(pill)
        btn.setPadding(self.dp(26), 0, self.dp(26), 0)
        btn.setOnClickListener(self.Click(lambda v: self._set_tab("library")))
        lp = self.LP(-2, self.dp(44))
        lp.topMargin = self.dp(22)
        box.addView(btn, lp)
        return box

    def _ghost_track(self):
        c = getattr(self.p, "_closed", None)
        return c["first"] if c else None

    def _make_row(self, i, m, playing_pos):
        LP = self.LP
        key = self._key(m)
        meta = self.row_meta_cache.get(key) if key is not None else None
        if meta is None:
            meta = {"title": self._title_of(m), "author": self._author_of(m)}
            if key is not None:
                self.row_meta_cache[key] = meta
        base = self._track_row_base(
       m, i == self.win_start, i == self.win_end - 1,
       meta.get("title") or "Audio", meta.get("author") or "",
       background=False, always_author=True,
       )
        row, lead, art, scrim, info, t1, t2 = (
       base[k] for k in ("row", "lead", "art", "scrim", "info", "title", "author")
       )
        play_iv, play_pp = self._track_play_icon(lead, m, fallback=True)
        ov = self._track_overlays(lead)
        chk, badge, arrow, spin = ov["check"], ov["badge"], ov["arrow"], ov["spin"]
        handle = self._drag_handle(strings("drag_to_reorder_track"))
        idx_box = [i]
        handle.setOnTouchListener(
       self._hold_drag(lambda v, e, box=idx_box, rw=row: self._on_handle_row(box, rw, v, e)))
        row.addView(handle, LP(self.dp(40), -1))
        more = self._glyph_icon(("ic_ab_other", "msg_more", "ic_more_vert"), self.c_sub,
       bold=True)
        more.setOnClickListener(self.Click(lambda v, mm=m: self._track_menu(mm, True)))
        row.addView(more, LP(self.dp(40), -1))
        row.setOnClickListener(self.Click(lambda v, mm=m: self._row_click(mm)))
        row.setOnLongClickListener(_viewlong_proxy()(lambda v, mm=m: self._row_long(mm, v)))
        R = {
       "play": play_iv, "play_pp": play_pp, "t1": t1, "info": info, "lead": lead,
       "art": art, "scrim": scrim, "cover": False, "badge": badge, "arrow": arrow,
       "spin": spin, "state": -1, "m": m, "t2": t2, "check": chk, "more": more,
       "row": row, "first": i == self.win_start, "last": i == self.win_end - 1,
       "idx_box": idx_box, "liked": base.get("liked"),
       }
        self.row_refs[i] = R
        self._apply_dl(R, self._dl_state(m))
        self._apply_sel(R)
        self._style_row(i, playing_pos)
        return row

    def _is_loading(self, m) -> bool:
        return self.p._is_loading(m)

    def _dl_state(self, m, refresh=False) -> int:
        k = self._key(m)
        if not refresh and k in self.dl_cache:
            return int(self.dl_cache[k])
        if self.p._is_downloaded(m):
            v = 2
        elif self.p._unavailable(m):
            v = 3
        elif self._is_loading(m):
            v = 1
        else:
            v = 0
        self.dl_cache[k] = v
        return v

    def _apply_dl(self, R, st):
        if R["state"] == st:
            return
        R["state"] = st
        R["badge"].setVisibility(8 if st in (2, 3) else 0)
        R["arrow"].setVisibility(0 if st == 0 else 8)
        R["spin"].setVisibility(0 if st == 1 else 8)

    def _visible_queue_index_range(self, margin_rows=2):
        try:
            sy = max(0, int(self.scroll.getScrollY()))
            vh = int(self.scroll.getHeight()) or self.dp(self.ROW_DP * 3)
            count = len(self.rows)
            start_local = min(count, max(0, sy // self.H - int(margin_rows)))
            end_local = min(count, max(start_local,
          (sy + vh) // self.H + int(margin_rows) + 1))
            return self.win_start + start_local, self.win_start + end_local
        except Exception:
            return self.win_start, self.win_end

    def _lib_dim_offline(self, R):
        a = 0.4 if (R["state"] == 3 or (R["state"] != 2 and self.p._offline_active())) else 1.0
        R["info"].setAlpha(a)
        R["lead"].setAlpha(a)

    def _lib_refresh_dl(self):
        try:
            sy = int(self.lib_sv.getScrollY())
            h = int(self.lib_sv.getHeight()) or self.dp(520)
        except Exception:
            return
        top, bot = sy - self.H * 2, sy + h + self.H * 2
        for refs in list(self.lib_track_rows.values()):
            R = refs.get("dl")
            if not R or R["state"] == 2:
                continue
            with tolerated():
                y0 = int(R["row"].getTop())
                if y0 + self.H < top or y0 > bot:
                    continue
                st = self._dl_state(R["m"], refresh=True)
                if st != R["state"]:
                    self._apply_dl(R, st)
                    self._lib_dim_offline(R)

    def _refresh_dl(self):
        if self.tab == "library":
            self._lib_refresh_dl()
            return
        if self.tab != "queue":
            return
        pi = self._playing_pos()
        start, end = self._visible_queue_index_range(2)
        for i in range(start, end):
            R = self.row_refs.get(i)
            if not R or R["state"] == 2:
                continue
            st = self._dl_state(R["m"], refresh=True)
            if st != R["state"]:
                self._apply_dl(R, st)
                self._style_row(i, pi)
                if st == 2 and not R.get("has_art"):
                    R["cover"] = False
                    R["ctries"] = 0
                    self.handler.postDelayed(self.Run(self._load_visible_covers), 200)

    def _verify_cover(self, R):
        R["chk_n"] = R.get("chk_n", 0) + 1
        has = False
        with tolerated():
            has = R["art"].getImageReceiver().getBitmap() is not None
        if has:
            R["chk"] = False
            return
        ok = self._row_embedded(R)
        if ok:
            R["chk"], R["has_art"] = False, True
            if R.get("scrim") is not None:
                R["scrim"].setVisibility(0)
        elif ok is False or R["chk_n"] >= 5:
            R["chk"] = False
        else:
            self._cover_retry_later(1200)

    def _cover_retry_later(self, delay=3000):
        if getattr(self, "_cov_retry", False):
            return
        self._cov_retry = True
        def run():
            self._cov_retry = False
            with tolerated():
                if self.dialog.isShowing():
                    self._load_visible_covers()
        self.handler.postDelayed(self.Run(run), delay)

    def _row_embedded(self, R):
        m = R["m"]
        k = self._key(m)
        bmp = self.p._emb_get(k)
        if bmp:
            R["art"].setImageBitmap(bmp)
            return True
        if bmp is False:
            return False
        if self.p._emb_fetch(m, lambda: self._apply_embedded(k)):
            return None
        return False

    def _apply_embedded(self, k):
        bmp = self.p._emb_get(k)
        if not bmp:
            return
        for R in list(self.row_refs.values()):
            with tolerated():
                if R.get("art") is not None and self._key(R["m"]) == k:
                    R["art"].setImageBitmap(bmp)
                    R["has_art"] = True
                    R["cover"] = True
                    if R.get("scrim") is not None:
                        R["scrim"].setVisibility(0)

    def _load_visible_covers(self):
        with tolerated():
            start, end = self._visible_queue_index_range(2)
            hq = bool(self.p.get_setting("hq_thumbs", True))
            d = self.COVER_DP * 2 if hq else self.COVER_DP
            flt = f"{d}_{d}"
            for i in range(start, end):
                R = self.row_refs.get(i)
                if not R or R["art"] is None:
                    continue
                if R["cover"]:
                    if R.get("chk"):
                        self._verify_cover(R)
                    continue
                R["cover"] = True
                ok = bool(self._load_cover(R["art"], R["m"], 0, flt, hq))
                if ok:
                    R["chk"], R["chk_n"] = True, 0
                    self._cover_retry_later(1200)
                if not ok:
                    ok = self._row_embedded(R)
                if ok is False:
                    R["ctries"] = R.get("ctries", 0) + 1
                    R["cover"] = R["ctries"] >= 3
                    if not R["cover"]:
                        self._cover_retry_later()
                elif ok:
                    R["has_art"] = True
                if R.get("scrim") is not None:
                    R["scrim"].setVisibility(0 if ok else 8)

    def _lib_progress_make(self, idle):
        LL = jclass("android.widget.LinearLayout")
        box = LL(self.act)
        box.setOrientation(0)
        box.setGravity(16)
        box.setPadding(self.dp(3), 0, self.dp(3), 0)
        pb = jclass("android.widget.ProgressBar")(self.act)
        with tolerated():
            pb.getIndeterminateDrawable().setColorFilter(
          self.c_text, jclass("android.graphics.PorterDuff$Mode").SRC_IN)
        box.addView(pb, self.LP(self.dp(18), self.dp(18)))
        tv = self._text("", 12, self.c_text, bold=True, gravity=17, single=True)
        with tolerated():
            tv.setEllipsize(None)
            tv.setMaxLines(1)
            tv.setIncludeFontPadding(False)
            tv.setMinWidth(self.dp(34))
        tv.setPadding(self.dp(3), 0, 0, 0)
        box.addView(tv, self.LP(-2, -2))
        box.setVisibility(idle)
        with tolerated():
            box.setContentDescription(strings("library_loading"))
        self.lib_prog_box, self.lib_prog_text, self._lib_prog_idle = box, tv, idle
        return box

    def _lib_resolver_refresh(self):
        if self.__dict__.get("_lib_rr_pending"):
            return
        if self.lib_state[0] != "pl" or getattr(self, "tab", None) != "library":
            return
        self._lib_rr_pending = True
        def run():
            self._lib_rr_pending = False
            with tolerated():
                if self.lib_state[0] != "pl" or self.tab != "library" or not self.dialog.isShowing():
                    return
                sy = int(self.lib_sv.getScrollY())
                self._lib_render()
                self.handler.postDelayed(self.Run(lambda: self.lib_sv.scrollTo(0, sy)), 40)
        self.handler.postDelayed(self.Run(run), 200)

    def _lib_empty_loading_view(self, subtitle):
        LL = jclass("android.widget.LinearLayout")
        FL = jclass("android.widget.FrameLayout")
        frame = FL(self.act)
        try:
            height = int(self.lib_sv.getHeight())
        except Exception:
            height = 0
        if height <= 0:
            try:
                dm = self.act.getResources().getDisplayMetrics()
                height = int(dm.heightPixels) - self.dp(260)
            except Exception:
                height = self.dp(360)
        with tolerated():
            if self.lib_search_bar.getVisibility() == 0:
                height -= self.dp(60)
        height = max(self.dp(240), height)
        frame.setMinimumHeight(height)
        group = LL(self.act)
        group.setOrientation(1)
        group.setGravity(17)
        pb = jclass("android.widget.ProgressBar")(self.act)
        with tolerated():
            pb.getIndeterminateDrawable().setColorFilter(
          self.c_accent, jclass("android.graphics.PorterDuff$Mode").SRC_IN)
        group.addView(pb, self.LP(self.dp(42), self.dp(42)))
        pct = self._text("", 15, self.c_text, bold=True, gravity=17, single=False)
        pct_lp = self.LP(-2, -2)
        pct_lp.setMargins(0, self.dp(12), 0, 0)
        group.addView(pct, pct_lp)
        frame.addView(group, FL.LayoutParams(-1, height, 17))
        self.lib_empty_progress_text = pct
        self.lib_empty_progress_label = None
        self.lib_box.addView(frame, self.LP(-1, height))
        self._lib_progress_refresh()

    def _lib_progress_refresh(self):
        box = getattr(self, "lib_prog_box", None)
        with tolerated():
            st = self.p._prog_state()
            b = getattr(self.p, "_queue_build_state", None)
            if st is None and b is not None and b.get("token") == getattr(self.p, "_queue_build_token", None):
                try:
                    st = min(99, int(b.get("loaded", 0) * 100 / max(1, int(b.get("total", 1)))))
                except Exception:
                    st = -1
            show = st is not None
            if box is not None:
                box.setVisibility(0 if show else self._lib_prog_idle)
                if show:
                    self.lib_prog_text.setText(f"{st}%" if st >= 0 else "")
            empty_text = getattr(self, "lib_empty_progress_text", None)
            if empty_text is not None:
                empty_text.setText(f"{st}%" if st is not None and st >= 0 else "")
            if getattr(self, "lib_detail_meta", None) is not None and self.lib_detail_base_meta.startswith((strings("loading_tracks").rstrip("…"), "Loading tracks")):
                self.lib_detail_meta.setText(strings("loading_tracks"))


    def _lyr_pref_all(self):
        try:
            d = json.loads(self.p.get_setting("lyrics_prefs_v1", "") or "{}")
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _lyr_pref(self, key):
        return self._lyr_pref_all().get("%d:%d" % tuple(key), {}) if key else {}

    def _lyr_pref_put(self, key, **kw):
        if not key:
            return
        d = self._lyr_pref_all()
        k = "%d:%d" % tuple(key)
        cur = dict(d.pop(k, {}))
        cur.update(kw)
        cur = {a: b for a, b in cur.items() if b not in (None, "", 0)}
        if cur:
            d[k] = cur
        while len(d) > 400:
            d.pop(next(iter(d)))
        self.p.set_setting("lyrics_prefs_v1", json.dumps(d))

    @staticmethod
    def _lyr_fmt_off(ms):
        ms = int(ms)
        return "%s%.1f s" % ("+" if ms > 0 else ("-" if ms < 0 else ""), abs(ms) / 1000.0)

    def _lyr_menu(self):
        from ..sheets import _ActionSheet
        if self.lyr_key is None:
            self.p._bulletin(strings("nothing_is_playing"), error=True)
            return
        pref = self._lyr_pref(self.lyr_key)
        data = self.lyr_data
        cur = (data or {}).get("src") or strings("no_lyrics_found")
        auto = not pref.get("src")
        custom = self._lyr_custom_label(self.lyr_key)
        opts = [
       (strings("lyrics_source"), strings("lyrics_source_sub"), False, self._lyr_pick_source,
        cur if auto else cur),
       (strings("lyrics_search_edit"), strings("lyrics_search_edit_sub"), False, self._lyr_search_dialog, custom),
       (strings("lyrics_sync"), strings("lyrics_sync_sub"), False, self._lyr_sync_dialog,
        self._lyr_fmt_off(self.lyr_off) if self.lyr_off else ""),
       None,
       (strings("keep_screen_on_in_lyrics"), "", False, self._lyr_toggle_awake,
        strings("state_on") if self.p.get_setting("lyrics_keep_awake", True) else strings("state_off"),
        lambda: bool(self.p.get_setting("lyrics_keep_awake", True))),
       ]
        if pref:
            opts += [None, (strings("lyrics_reset_track"), strings("lyrics_reset_track_sub"), True, self._lyr_reset_track)]
        _ActionSheet(self.p, self.act).show_sheet(strings("lyrics_options"), self._title_of_key(), opts)

    def _title_of_key(self):
        with tolerated():
            mc, pm = self._mini_playing()
            if pm is not None:
                return self._title_of(pm)
        return ""

    def _lyr_toggle_awake(self):
        on = not bool(self.p.get_setting("lyrics_keep_awake", True))
        self.p.set_setting("lyrics_keep_awake", on)
        with tolerated():
            self.tab_pages["lyrics"].setKeepScreenOn(on)

    def _lyr_reset_track(self):
        key = self.lyr_key
        self._lyr_pref_put(key, src=None, off=0, q=None)
        self.__dict__.setdefault("lyr_cands", {}).pop(key, None)
        self.lyr_off = 0
        self.lyr_cache.pop(key, None)
        self.lyr_key = None

    def _lyr_use(self, cand):
        key = self.lyr_key
        if key is None:
            return
        self.lyr_cache[key] = cand
        self.lyr_token += 1
        self.lyr_active = -1
        self.lyr_word = -1
        self._lyr_sung = None
        self.lyr_free = False
        self.lyr_off = 0
        self._lyr_cancel_anim()
        self._lyr_btn_show(False)
        self._lyr_apply(cand)
        self._lyr_pref_put(key, src=cand.get("id"), off=0)

    def _lyr_pick_source(self):
        key = self.lyr_key
        if key is None:
            return
        cached = self.__dict__.setdefault("lyr_cands", {})
        if key in cached:
            self._lyr_source_sheet(key, cached[key])
            return
        mc, pm = self._mini_playing()
        if pm is None:
            return
        self.p._bulletin(strings("lyrics_searching"))
        title, artist = self._lyr_query(pm, key)[:2]
        try:
            dur = int(pm.getDuration())
        except Exception:
            dur = 0
        path = None
        with tolerated():
            f = self.p._emb_file(pm)
            path = str(f.getAbsolutePath()) if f is not None else None
        online = self.p._net_ok()
        def work():
            emb = _lyr_embedded(path) if path else None
            if emb is not None:
                emb.setdefault("id", "local")
            try:
                res = _lyr_candidates(title, artist, "", dur, emb, online)
            except Exception:
                res = [dict(emb, note="")] if emb else []
            def show():
                if online:
                    cached[key] = res
                self._lyr_source_sheet(key, res)
            run_on_ui_thread(show)
        threading.Thread(target=work, daemon=True).start()

    def _lyr_source_sheet(self, key, cands):
        from ..sheets import _ActionSheet
        if key != self.lyr_key:
            return
        pref = self._lyr_pref(key)
        cur_id = pref.get("src")
        kinds = {"word": strings("lyrics_kind_word"), "line": strings("lyrics_kind_line"),
                 "plain": strings("lyrics_kind_plain")}
        def radio(selected):
            return "radio_on" if selected else "radio_off"
        opts = [(strings("lyrics_auto"), strings("lyrics_auto_sub"), False, self._lyr_reset_source,
                 radio(not cur_id))]
        if not cands:
            opts.append((strings("lyrics_none_found"), "", False, lambda: None, "", None, None, True))
        for c in cands:
            if c.get("id") == "local":
                label = strings("lyrics_local")
            else:
                label = c.get("src", "")
                if c.get("note"):
                    label += " · " + c["note"]
            opts.append((label, kinds.get(c.get("kind"), ""), False,
                         (lambda cc=c: self._lyr_use(cc)),
                         radio(bool(cur_id) and cur_id == c.get("id"))))
        custom = self._lyr_custom_label(key)
        opts += [None, (strings("lyrics_search_edit"), strings("lyrics_search_edit_sub"), False,
                        self._lyr_search_dialog, "")]
        _ActionSheet(self.p, self.act).show_sheet(strings("lyrics_source"), custom or self._title_of_key(), opts)

    def _lyr_reset_source(self):
        key = self.lyr_key
        self._lyr_pref_put(key, src=None, off=0)
        self.lyr_cache.pop(key, None)
        self.lyr_off = 0
        self.lyr_key = None


    def _lyr_query(self, pm, key=None):
        q = self._lyr_pref(key if key is not None else self._key(pm)).get("q")
        if isinstance(q, (list, tuple)) and len(q) == 2 and str(q[0]).strip():
            return str(q[0]), str(q[1] or ""), True
        return self._title_of(pm), self._author_of(pm), False

    def _lyr_custom_label(self, key):
        q = self._lyr_pref(key).get("q") if key else None
        if isinstance(q, (list, tuple)) and len(q) == 2 and str(q[0]).strip():
            return ("%s \u2014 %s" % (q[0], q[1])) if q[1] else str(q[0])
        return ""

    def _lyr_search_dialog(self):
        key = self.lyr_key
        if key is None:
            return
        mc, pm = self._mini_playing()
        if pm is None:
            return
        act, dp, LP = self.act, self.dp, self.LP
        LL = _cls("android.widget.LinearLayout")
        ET = _cls("android.widget.EditText")
        Dialog = _cls("android.app.Dialog")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        CD = _cls("android.graphics.drawable.ColorDrawable")
        file_t, file_a = self._title_of(pm).strip(), self._author_of(pm).strip()
        cur_t, cur_a, _custom = self._lyr_query(pm, key)
        st = {"busy": False, "closed": False}
        dlg = Dialog(act)
        dlg.requestWindowFeature(1)
        root = LL(act)
        root.setOrientation(1)
        bg = GD()
        bg.setColor(self.c_bg)
        bg.setCornerRadius(float(dp(18)))
        root.setBackground(bg)
        root.setPadding(dp(20), dp(18), dp(20), dp(8))
        root.addView(self._text(strings("lyrics_search_title"), 18, self.c_text, bold=True), LP(-1, -2))
        note = self._text(strings("lyrics_search_note"), 13, self.c_sub)
        note.setPadding(0, dp(4), 0, dp(14))
        root.addView(note, LP(-1, -2))

        def field(label, initial, hint, ime):
            lab = self._text(label, 12, self.c_sub, bold=True)
            lab.setPadding(dp(4), 0, 0, dp(4))
            root.addView(lab, LP(-1, -2))
            row = LL(act)
            row.setOrientation(0)
            row.setGravity(16)
            rb = GD()
            rb.setColor(_mix(self.c_bg, self.c_text, 0.08))
            rb.setCornerRadius(float(dp(12)))
            row.setBackground(rb)
            row.setPadding(dp(12), 0, dp(4), 0)
            et = ET(act)
            et.setSingleLine(True)
            et.setTextSize(16)
            et.setTextColor(self.c_text)
            et.setHintTextColor(self.c_sub)
            et.setHint(hint)
            et.setBackgroundColor(0)
            et.setPadding(0, 0, dp(4), 0)
            et.setText(initial or "")
            with tolerated():
                et.setTextDirection(1)
                et.setGravity(0x00800003 | 16)
            et.setImeOptions(ime)
            row.addView(et, LP(0, dp(48), 1.0))
            clear = self._glyph_icon(("msg_close", "ic_close_white", "msg_cancel"), self.c_sub, pad=8, size=18)
            clear.setOnClickListener(self.Click(lambda v: (et.setText(""), et.requestFocus())))
            row.addView(clear, LP(dp(38), dp(44)))
            lp = LP(-1, -2)
            lp.setMargins(0, 0, 0, dp(10))
            root.addView(row, lp)
            return et

        title_et = field(strings("lyrics_field_title"), cur_t, strings("lyrics_field_title"), 5)
        artist_et = field(strings("lyrics_field_artist"), cur_a, strings("lyrics_field_artist"), 3)

        def file_tags():
            if st["busy"]:
                return
            title_et.setText(file_t)
            artist_et.setText(file_a)

        msg = self._text("", 13, getattr(self, "c_red", self.c_accent), gravity=3)
        msg.setPadding(dp(4), dp(2), dp(4), dp(6))
        msg.setVisibility(8)
        root.addView(msg, LP(-1, -2))

        def say(text):
            msg.setText(text)
            msg.setVisibility(0 if text else 8)

        row = LL(act)
        row.setOrientation(0)
        row.setGravity(16)
        reset_b = self._text(strings("lyrics_reset"), 15, self.c_sub, bold=True, gravity=17)
        reset_b.setPadding(dp(16), dp(12), dp(16), dp(12))
        reset_b.setOnClickListener(self.Click(lambda v: file_tags()))
        row.addView(reset_b, LP(-2, -2))
        row.addView(_cls("android.view.View")(act), LP(0, 1, 1.0))
        cancel_b = self._text(strings("cancel"), 15, self.c_sub, bold=True, gravity=17)
        cancel_b.setPadding(dp(16), dp(12), dp(16), dp(12))
        cancel_b.setOnClickListener(self.Click(lambda v: dlg.dismiss()))
        row.addView(cancel_b, LP(-2, -2))
        go_b = self._text(strings("lyrics_search_go"), 15, self.c_accent, bold=True, gravity=17)
        go_b.setPadding(dp(16), dp(12), dp(16), dp(12))
        row.addView(go_b, LP(-2, -2))
        root.addView(row, LP(-1, -2))

        def busy(on):
            st["busy"] = on
            go_b.setText(strings("lyrics_search_busy") if on else strings("lyrics_search_go"))
            go_b.setAlpha(0.5 if on else 1.0)
            for e in (title_et, artist_et):
                e.setEnabled(not on)
            with tolerated():
                dlg.setCanceledOnTouchOutside(not on)

        def finish(res, t, a):
            if st["closed"]:
                return
            busy(False)
            found = [c for c in res if c.get("id") != "local"]
            if not found:
                say(strings("lyrics_search_nothing"))
                return
            self._lyr_pref_put(key, q=None if (t == file_t and a == file_a) else [t, a])
            self.__dict__.setdefault("lyr_cands", {})[key] = res
            st["closed"] = True
            dlg.dismiss()
            if key != self.lyr_key:
                return
            best = max(found, key=lambda c: _LYR_RANK.get(c.get("kind"), 0))
            self._lyr_use(best)
            self._lyr_source_sheet(key, res)

        def go():
            if st["busy"]:
                return
            t, a = str(title_et.getText()).strip(), str(artist_et.getText()).strip()
            if not t:
                say(strings("lyrics_search_need_title"))
                title_et.requestFocus()
                return
            if not self.p._net_ok():
                say(strings("lyrics_search_offline"))
                return
            say("")
            busy(True)
            try:
                dur = int(pm.getDuration())
            except Exception:
                dur = 0
            path = None
            with tolerated():
                f = self.p._emb_file(pm)
                path = str(f.getAbsolutePath()) if f is not None else None

            def work():
                emb = _lyr_embedded(path) if path else None
                if emb is not None:
                    emb.setdefault("id", "local")
                try:
                    res = _lyr_candidates(t, a, "", dur, emb, True)
                except Exception:
                    res = []
                run_on_ui_thread(lambda: finish(res, t, a))
            threading.Thread(target=work, daemon=True).start()

        go_b.setOnClickListener(self.Click(lambda v: go()))
        artist_et.setOnEditorActionListener(_proxy(
            "android.widget.TextView$OnEditorActionListener", "onEditorAction",
            lambda v, a, e: (int(a),), ret=True)(lambda a: (go() or True) if a in (3, 6) else False))
        dlg.setOnDismissListener(_dismiss_proxy()(lambda d=None: st.__setitem__("closed", True)))
        dlg.setContentView(root)
        dlg.setCanceledOnTouchOutside(True)
        win = dlg.getWindow()
        if win is not None:
            win.setBackgroundDrawable(CD(0))
            wpx = int(act.getResources().getDisplayMetrics().widthPixels * 0.92)
            win.setLayout(min(wpx, dp(440)), -2)
            win.setGravity(17)
            with tolerated():
                win.setSoftInputMode(16 | 4)
        dlg.show()
        with tolerated():
            title_et.requestFocus()
            title_et.selectAll()

    def _lyr_sync_dialog(self):
        act = self.act
        dp = self.dp
        LL = _cls("android.widget.LinearLayout")
        View = _cls("android.view.View")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        CD = _cls("android.graphics.drawable.ColorDrawable")
        Dialog = _cls("android.app.Dialog")
        key = self.lyr_key
        if key is None:
            return
        dlg = Dialog(act)
        dlg.requestWindowFeature(1)
        root = LL(act)
        root.setOrientation(1)
        bg = GD()
        bg.setColor(self.c_bg)
        r = float(dp(16))
        bg.setCornerRadii(jarray(jfloat)([r, r, r, r, 0.0, 0.0, 0.0, 0.0]))
        root.setBackground(bg)
        root.setPadding(dp(20), dp(20), dp(20), dp(20))
        root.addView(self._text(strings("lyrics_sync"), 18, self.c_text, bold=True), self.LP(-1, -2))
        val = self._text("", 34, self.c_text, bold=True, gravity=17)
        val.setPadding(0, dp(14), 0, dp(4))
        root.addView(val, self.LP(-1, -2))
        hint = self._text(strings("lyrics_sync_hint"), 13, self.c_sub, gravity=17)
        hint.setPadding(0, 0, 0, dp(16))
        root.addView(hint, self.LP(-1, -2))
        def show():
            val.setText(self._lyr_fmt_off(self.lyr_off) if self.lyr_off else "0.0 s")
        def bump(delta):
            self.lyr_off = max(-30000, min(30000, int(self.lyr_off) + int(delta)))
            self._lyr_pref_put(key, off=self.lyr_off)
            show()
        def reset():
            self.lyr_off = 0
            self._lyr_pref_put(key, off=0)
            show()
        def mk(label, fn, accent=False):
            tv = self._text(label, 16, self.c_accent if accent else self.c_text, bold=True, gravity=17, single=True)
            b = GD()
            b.setCornerRadius(float(dp(12)))
            b.setColor(_mix(self.c_bg, self.c_text, 0.1))
            tv.setBackground(b)
            tv.setOnClickListener(self.Click(lambda v: fn()))
            with tolerated():
                self._press_fx(tv)
            return tv
        def row(items):
            line = LL(act)
            line.setOrientation(0)
            for n, tv in enumerate(items):
                if n:
                    line.addView(View(act), self.LP(dp(8), 1))
                line.addView(tv, self.LP(0, dp(48), 1.0))
            lp = self.LP(-1, -2)
            root.addView(line, lp)
            sp = View(act)
            root.addView(sp, self.LP(-1, dp(8)))
        row([mk("-1 s", lambda: bump(-1000)), mk("-0.1 s", lambda: bump(-100)),
             mk("+0.1 s", lambda: bump(100)), mk("+1 s", lambda: bump(1000))])
        row([mk(strings("lyrics_reset"), reset), mk(strings("lyrics_done"), lambda: dlg.dismiss(), True)])
        show()
        dlg.setContentView(root)
        dlg.setCanceledOnTouchOutside(True)
        win = dlg.getWindow()
        if win is not None:
            win.setBackgroundDrawable(CD(0))
            win.setLayout(_wide_px(act, 600) or -1, -2)
            win.setGravity(80)
        dlg.show()
