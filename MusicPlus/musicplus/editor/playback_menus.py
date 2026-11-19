import time
from ..compat import (
 BulletinHelper,
 find_class,
 get_last_fragment,
 jarray,
 jclass,
 jfloat,
 jint,
)
from elyx import strings
from ..helpers import _argb, _fmt_time
from ..android import _cls, _legacy_public_save, _mediastore_save, _mix
from ..safe import tolerated
from .. import swap as _swap
from .. import tint


class _QueueEditorPlaybackMenus:
    def _save_cover_gallery(self, art, pm):
        try:
            bmp = None
            with tolerated():
                receiver = art.getImageReceiver()
                for name in ("getBitmapSafe", "getBitmap", "getBitmapDrawable"):
                    with tolerated():
                        bmp = self._as_bitmap(getattr(receiver, name)())
                        if bmp is not None:
                            break
            if bmp is None:
                with tolerated():
                    bmp = self._as_bitmap(art.getDrawable())
            if bmp is None:
                with tolerated():
                    used = getattr(self, "_bmp_used", None)
                    bmp = self._as_bitmap(used[0]) if used is not None else None
            if bmp is None:
                with tolerated():
                    receiver = self.cover.getImageReceiver()
                    bmp = self._as_bitmap(receiver.getBitmapSafe())
            if bmp is None:
                self._toast(strings("album_artwork_hasnt_loaded_yet"), True)
                return
            with tolerated():
                cfg = bmp.getConfig()
                hardware = getattr(_cls("android.graphics.Bitmap$Config"), "HARDWARE", None)
                if hardware is not None and cfg == hardware:
                    bmp = bmp.copy(_cls("android.graphics.Bitmap$Config").ARGB_8888, False)
            try:
                if bool(bmp.isRecycled()):
                    raise RuntimeError("artwork was released, reopen the track")
            except AttributeError:
                pass
            title = str(self.p._read(pm, "getMusicTitle", "getTitle") or "album_art")
            safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in title).strip()[:80]
            if not safe:
                safe = "album_art"
            filename = safe + "_cover.jpg"
            JPEG = _cls("android.graphics.Bitmap$CompressFormat").JPEG
            def write(stream):
                if not bool(bmp.compress(JPEG, 96, stream)):
                    raise RuntimeError("Bitmap compression failed")
            ctx = find_class("org.telegram.messenger.ApplicationLoader").applicationContext
            err = ""
            try:
                _mediastore_save(ctx, "images", filename, "image/jpeg", write)
                self._toast(strings("saved_cover_to_gallery"))
                return
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
            with tolerated():
                _legacy_public_save(ctx, "Pictures", filename, write)
                self._toast(strings("saved_cover_to_gallery"))
                return
            with tolerated():
                tmp = jclass("java.io.File")(ctx.getCacheDir(), filename)
                out = jclass("java.io.FileOutputStream")(tmp)
                try:
                    write(out)
                finally:
                    out.close()
                MC = find_class("org.telegram.messenger.MediaController")
                MC.saveFile(str(tmp.getAbsolutePath()), ctx, 0, filename, "image/jpeg")
                self._toast(strings("saved_cover_to_gallery"))
                return
            raise RuntimeError(err or "no save method worked")
        except Exception as e:
            reason = str(e).strip().splitlines()[0][:70] if str(e).strip() else ""
            self._toast(strings("could_not_save_artwork_to_gallery") + (f" ({reason})" if reason else ""), True)

    def _toast(self, message, error=False):
        with tolerated():
            _cls("android.widget.Toast").makeText(self.act, str(message), 1 if error else 0).show()

    def _mini_pause_ui(self, paused):
        self._mini_pp_state = bool(paused)
        def shown(name):
            with tolerated():
                v = getattr(self, name, None)
                return v is not None and int(v.getVisibility()) == 0
            return True
        cpp = getattr(self, "mini_cpp", None)
        if cpp is not None:
            with tolerated():
                cpp.setPause(not paused, shown("mini_cplay"))
        pp = getattr(self, "mini_pp", None)
        if pp is not None:
            with tolerated():
                pp.setPause(not paused, shown("mini_play"))
                return
        self.mini_play.setImageResource(self._ic_play if paused else self._ic_pause)

    def _mini_pp_snap(self):
        st = getattr(self, "_mini_pp_state", None)
        if st is None:
            return
        for name in ("mini_cpp", "mini_pp"):
            d = getattr(self, name, None)
            if d is not None:
                with tolerated():
                    d.setPause(not st, False)

    def _skip_btn(self, nxt, fn):
        Dr = _cls("android.R$drawable")
        try:
            raw = int(self.act.getResources().getIdentifier("player_prev", "raw", self.act.getPackageName()))
            if not raw:
                raw = int(getattr(find_class("org.telegram.messenger.R$raw"), "player_prev"))
            iv = find_class("org.telegram.ui.Components.RLottieImageView")(self.act)
            iv.setScaleType(_cls("android.widget.ImageView$ScaleType").CENTER)
            iv.setAnimation(raw, 20, 20)
            for layer in ("Triangle 3", "Triangle 4", "Rectangle 4"):
                iv.setLayerColor(layer, self.c_player_text)
            if nxt:
                iv.setRotation(180.0)
            def tap(v):
                fn()
                with tolerated():
                    iv.setProgress(jfloat(0.0) if jfloat else 0.0)
                    iv.playAnimation()
            iv.setOnClickListener(self.Click(tap))
            return iv
        except Exception:
            return self._icon(("ic_action_next",) if nxt else ("ic_action_previous",),
          Dr.ic_media_next if nxt else Dr.ic_media_previous, self.c_player_text, fn)

    def _mini_playing(self):
        mc = self.p._get_mc()
        try:
            return mc, (mc.getPlayingMessageObject() if mc is not None else None)
        except Exception:
            return mc, None

    def _open_mini_artist(self):
        from ..editor import _QueueEditor
        _mc, message = self._mini_playing()
        if message is None:
            message = self._ghost_track()
        artist = (_QueueEditor._author_of(message) or "").strip() if message is not None else ""
        if not artist:
            self.p._bulletin(strings("no_artist_is_available_for_this"), error=True)
            return
        self.p._view_artist_in_library(artist, message)

    def _on_seek(self, kind, val):
        bar = self.mini_bar
        cur = self.mini_cur
        if kind == "start":
            self.seeking = True
        elif kind == "change":
            _, pm = self._mini_playing()
            if pm is not None:
                cur.setText(_fmt_time(int(pm.getDuration()) * val / 1000.0))
        elif kind == "stop":
            self.seeking = False
            mc, pm = self._mini_playing()
            if pm is not None:
                frac = int(bar.getProgress()) / 1000.0
                with tolerated():
                    mc.seekToProgress(pm, jfloat(frac) if jfloat else frac)

    def _mini_toggle(self):
        mc, pm = self._mini_playing()
        if mc is None:
            return
        with tolerated():
            if pm is None:
                if getattr(self.p, "_closed", None) is not None and self.p._rs_reopen_closed(play=True, done=self._reload):
                    pass
                elif self.items:
                    mc.playMessage(self.items[0])
                elif self.p._resume_available():
                    self.p._resume_restore(play=True, done=self._reload)
            elif bool(mc.isMessagePaused()):
                mc.playMessage(pm)
            else:
                mc.pauseMessage(pm)
        self._mini_update()
        self._nudge_update()

    def _mini_empty_ui(self, empty):
        empty = bool(empty)
        if getattr(self, "_mini_empty", None) == empty:
            return
        self._mini_empty = empty
        views = [self.mini_cprev, self.mini_cnext]
        for i, fl in enumerate(getattr(self, "_fly", ())):
            if i >= 1:
                views.append(fl[1])
        for v in views:
            with tolerated():
                v.setEnabled(not empty)
                v.setImageAlpha(110 if empty else 255)
        with tolerated():
            self.mini_bar.setEnabled(not empty)

    def _mini_next(self):
        self._swap_dir = 1
        with tolerated():
            if self._mini_playing()[1] is None:
                return
            self.p._get_mc().playNextMessage()

    def _mini_prev(self):
        self._swap_dir = -1
        with tolerated():
            if self._mini_playing()[1] is None:
                return
            self.p._get_mc().playPreviousMessage()

    def _update_mini_like(self, msg):
        liked = bool(msg is not None and self.p._is_track_liked(msg))
        color = int(self.c_player_progress if liked else self.c_player_button)
        sig = (liked, msg is not None, color)
        if getattr(self, "_like_sig", None) == sig:
            return
        self._like_sig = sig
        with tolerated():
            self.mini_like_btn.setImageResource(self._like_ids[1 if liked else 0])
            self.mini_like_btn.setColorFilter(color)
            self.mini_like_btn.setEnabled(True)
            self._like_rest_a = 1.0
            if getattr(self, "_mini_anim", None) is None and (self._mo("mini_show_like") or not getattr(self, "_mini_hid", False)):
                self.mini_like_btn.setAlpha(self._like_rest_a)
            self.mini_like_btn.setContentDescription(
          strings("remove_from_liked_songs") if liked else strings("add_to_liked_songs"))

    def _like_bounce(self):
        with tolerated():
            b = self.mini_like_btn
            b.animate().cancel()
            b.setScaleX(0.55)
            b.setScaleY(0.55)
            b.animate().scaleX(1.0).scaleY(1.0).setDuration(420).setInterpolator(
          _cls("android.view.animation.OvershootInterpolator")(4.0)).start()

    def _mini_toggle_like(self):
        _, pm = self._mini_playing()
        if pm is None:
            pm = self._ghost_track()
        if pm is None:
            self.p._bulletin(strings("nothing_is_playing"), error=True)
            return
        self.p._toggle_track_liked(pm)
        self._like_sig = None
        self._update_mini_like(pm)
        self._like_bounce()
        if getattr(self, "tab", None) == "library":
            self._lib_render()

    def _repeat_mode(self) -> int:
        try:
            return int(getattr(self._sc(), "repeatMode", 0))
        except Exception:
            return 0

    def _sc(self):
        sc = getattr(self, "_SC", None)
        if sc is None:
            sc = self._SC = find_class("org.telegram.messenger.SharedConfig")
        return sc

    PB_SPEEDS = (0.75, 1.0, 1.25, 1.5, 2.0)
    _TUNE_ICONS = ("msg_customize", "msg_filter", "msg_settings", "ic_ab_settings")
    _LOOP_ORDER_ICONS = {
    ("all", "shuffle"): ("player_new_repeatall_shuffle", "player_new_shuffle_repeatall", "player_new_repeat_shuffle"),
    ("all", "reverse"): ("player_new_repeatall_order", "player_new_order_repeatall", "player_new_repeat_order"),
    ("one", "reverse"): ("player_new_repeatone_order", "player_new_order_repeatone", "player_new_repeat_order"),
    }

    def _pb_state(self):
        p = self.p
        shuf, rev = p._read_order()
        mode = getattr(p, "_sleep_mode", None)
        sleep = ""
        if mode == "min":
            left = max(0, int(getattr(p, "_sleep_end", time.time()) - time.time()))
            sleep = "<1m" if left < 60 else f"{(left + 59) // 60}m"
        elif mode == "eot":
            sleep = "eot"
        xf = getattr(p, "_xf", None)
        try:
            spd, pit = p._pb_settings()
            spd = round(float(spd), 2)
        except Exception:
            spd, pit = 1.0, 0
        return {"rep": self._repeat_mode(), "shuf": bool(shuf), "rev": bool(rev and not shuf),
       "speed": spd, "pitch": pit, "sleep": sleep,
       "xf": int(xf.sec()) if xf is not None else 0,
       "eq": bool(getattr(p, "_eq", None) is not None and p._eq.active()),
       "off": bool(p._offline_active())}

    def _pb_default(self, st):
        return not (st["rep"] or st["shuf"] or st["rev"] or st["speed"] != 1.0 or st["pitch"]
       or st["sleep"] or st["xf"] or st["eq"] or st["off"])

    def _pill_items(self, st):
        items = []
        if st["sleep"] == "eot":
            items.append(("i", ("msg_stories_timer",)))
        elif st["sleep"]:
            items.append(("t", st["sleep"]))
        if st["speed"] != 1.0 or st["pitch"]:
            bits = []
            if st["speed"] != 1.0:
                bits.append(f"{st['speed']:g}×")
            if st["pitch"]:
                bits.append(f"{st['pitch']:+d}")
            items.append(("t", " ".join(bits)))
        if st["rep"] or st["shuf"] or st["rev"]:
            items.append(("lo", (st["rep"], st["shuf"], st["rev"])))
        if st["eq"]:
            items.append(("i", ("msg_download_settings", "msg_equalizer", "equalizer", "msg_filter", "msg_customize")))
        if st["xf"]:
            items.append(("i", ("msg_blur_linear",)))
        if st["off"]:
            items.append(("i", ("menu_download_off_24", "msg_download")))
        if len(items) > 3:
            n = len(items) - 2
            items = items[:2] + [("t", f"+{n}")]
        return items

    def _loop_order_res(self, rep, shuf, rev):
        loop = "one" if rep == 2 else "all" if rep == 1 else None
        order = "shuffle" if shuf else "reverse" if rev else None
        names = self._LOOP_ORDER_ICONS.get((loop, order)) if loop and order else None
        if names:
            r = int(self._res(*names) or 0)
            if r:
                return [r]
        out = []
        if loop:
            out.append(int(self._res("player_new_repeatone" if rep == 2 else "player_new_repeatall") or 0))
        if order:
            out.append(int(self._res("player_new_order", "player_reverse") if rev else self._res("player_new_shuffle", "player_shuffle", "msg_shuffle") or 0))
        return [r for r in out if r]

    def _pill_update(self):
        pill = getattr(self, "mini_pill", None)
        if pill is None:
            return
        st = self._pb_state()
        key = tuple(sorted(st.items()))
        if getattr(self, "_rep_state", None) == key:
            return
        self._rep_state = key
        GD = _cls("android.graphics.drawable.GradientDrawable")
        IV = _cls("android.widget.ImageView")
        LPl = _cls("android.widget.LinearLayout$LayoutParams")
        pill.removeAllViews()
        idle = self._pb_default(st)
        g = GD()
        g.setCornerRadius(float(self.dp(18)))
        g.setColor(_mix(self.c_player_bg, self.c_player_button, 0.14) if idle
       else _mix(self.c_player_bg, self.c_player_progress, 0.24))
        pill.setBackground(g)
        tint = self.c_player_button if idle else self.c_player_progress
        def add_icon(res):
            iv = IV(self.act)
            iv.setImageResource(res)
            iv.setColorFilter(tint)
            lp = LPl(self.dp(18), self.dp(18))
            if pill.getChildCount():
                lp.setMargins(self.dp(5), 0, 0, 0)
            pill.addView(iv, lp)
        def add_text(t):
            tv = self._text(t, 12, tint, bold=True, single=True)
            lp = LPl(-2, -2)
            if pill.getChildCount():
                lp.setMargins(self.dp(5), 0, 0, 0)
            pill.addView(tv, lp)
        if idle:
            pill.setPadding(self.dp(10), 0, self.dp(10), 0)
            add_icon(int(self._res(*self._TUNE_ICONS)))
            return
        pill.setPadding(self.dp(11), 0, self.dp(11), 0)
        for kind, val in self._pill_items(st):
            if kind == "t":
                add_text(val)
            elif kind == "i":
                add_icon(int(self._res(*val)))
            else:
                for r in self._loop_order_res(*val):
                    add_icon(r)

    def _open_playback_sheet(self):
        from ..sheets import _PlaybackSheet
        from .. import crashlog
        crashlog.arm("Playback sheet open")
        try:
            _PlaybackSheet(self.p, self.act).show()
            self.handler.postDelayed(self.Run(lambda: crashlog.disarm("Playback sheet open")), 2500)
        except Exception as e:
            crashlog.disarm("Playback sheet failed")
            crashlog.crumb("playback open: " + type(e).__name__ + ": " + str(e)[:80])
            self.p._bulletin(strings("couldnt_do_that"), error=True)


    def _pb_apply(self, force=True):
        self.p._pb_apply_now(force)

    def _pb_reapply(self):
        p = self.p
        with tolerated():
            p._eq_sync()
        with tolerated():
            self._pb_apply(force=False)



    def _nudge_update(self):
        for d in (120, 350, 800):
            with tolerated():
                self.handler.postDelayed(self.Run(self._mini_update_safe), d)

    def _mini_update_safe(self):
        with tolerated():
            if self.dialog.isShowing():
                self._mini_update()

    def _mini_tick(self):
        alive = False
        with tolerated():
            alive = bool(self.dialog.isShowing())
        if not alive:
            return
        self._last_tick = time.monotonic()
        go = True
        try:
            go = self._mini_tick_body() is not False
        finally:
            if go:
                self.handler.postDelayed(self.mini_run, 500)

    def revive_tick(self):
        with tolerated():
            if not self.dialog.isShowing() or time.monotonic() - getattr(self, "_last_tick", time.monotonic()) < 3.0:
                return
            self.handler.removeCallbacks(self.mini_run)
            self.handler.post(self.mini_run)

    def _mini_tick_body(self):
        with tolerated():
            self._tint_poll()
        with tolerated():
            current_fragment = get_last_fragment()
            if current_fragment is not None:
                name = str(current_fragment.getClass().getName()).lower()
                args = current_fragment.getArguments() if hasattr(current_fragment, "getArguments") else None
                selecting = False
                if args is not None:
                    with tolerated():
                        selecting = bool(args.getBoolean("onlySelect", False))
                    with tolerated():
                        da = jclass("org.telegram.ui.DialogsActivity")
                        selecting = selecting or int(args.getInt("dialogsType", -1)) == int(da.DIALOGS_TYPE_FORWARD)
                sharing = "shareactivity" in name or "chooseractivity" in name or "sendtoactivity" in name
                if ("dialogsactivity" in name and selecting) or sharing:
                    if not self.tabmode:
                        self.dialog.dismiss()
                        return False
        with tolerated():
            self._mini_update()
        with tolerated():
            self._refresh_dl()
        with tolerated():
            if self.tab == "lyrics" and not self._lyr_running:
                self._lyr_start()
        return True

    def _cover_telegram(self, pm) -> bool:
        return self._load_cover(self.cover, pm, 0, "512_512", hq=True)

    @staticmethod
    def _best_thumb(doc, hq=False):
        thumbs = doc.thumbs
        if thumbs is None or int(thumbs.size()) == 0:
            return None
        FL = find_class("org.telegram.messenger.FileLoader")
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
            return real[-1][1] if hq else real[0][1]
        try:
            return FL.getClosestPhotoSizeWithSize(thumbs, 512 if hq else 90)
        except Exception:
            return None

    def _load_cover(self, view, pm, want=0, flt="184_184", hq=False, prefer_url=False) -> bool:
        IL = find_class("org.telegram.messenger.ImageLocation")
        loc = None
        if prefer_url:
            with tolerated():
                url = pm.getArtworkUrl(False if hq else True)
                if url and str(url).strip():
                    loc = IL.getForPath(str(url))
        doc = pm.getDocument()
        if loc is None and doc is not None:
            size = self._best_thumb(doc, hq)
            if size is not None:
                with tolerated():
                    loc = IL.getForDocument(size, doc)
        if loc is None:
            with tolerated():
                url = pm.getArtworkUrl(False if hq else True)
                if url and str(url).strip():
                    loc = IL.getForPath(str(url))
        if loc is None:
            return False
        try:
            with tolerated():
                rcv = view.getImageReceiver()
                rcv.setCrossfadeDuration(0)
                rcv.setAllowStartAnimation(False)
            view.setImage(loc, flt, _cls("android.graphics.drawable.ColorDrawable")(0), pm)
            return True
        except Exception:
            return False

    def _set_cover(self, mc, pm) -> bool:
        return self._set_cover_mini(mc, pm)

    def _set_cover_mini(self, mc, pm) -> bool:
        self._cover_src = None
        with tolerated():
            self.p._emb_fetch(pm, lambda: None)
        e = None
        with tolerated():
            e = self.p._emb_get(self._cover_key)
        if e is not None and e is not False:
            with tolerated():
                self.cover.setImageBitmap(e)
                self._bmp_used = (e, self._cover_key)
                self._cover_src = "bmp"
                return True
        bmp = None
        with tolerated():
            bmp = self.p._info_cover(mc, pm)
        used = getattr(self, "_bmp_used", None)
        shared_bmp_pending = False
        if bmp is not None and used is not None and used[0] is bmp and used[1] != self._cover_key:
            self._cover_repeat_tries = getattr(self, "_cover_repeat_tries", 0) + 1
            if self._cover_repeat_tries <= 3:
                bmp = None
            else:
                shared_bmp_pending = True
        with tolerated():
            if bmp is not None:
                self.cover.setImageBitmap(bmp)
                if shared_bmp_pending:
                    self._cover_src = "bmp_pending"
                else:
                    self._bmp_used = (bmp, self._cover_key)
                    self._cover_src = "bmp"
                    with tolerated():
                        if self._cover_key is not None:
                            self.p._emb_put(self._cover_key, bmp)
                            self._apply_embedded(self._cover_key)
                return True
        if self.cover_biv:
            with tolerated():
                if self._cover_telegram(pm):
                    self._cover_src = "thumb"
                    return True
        with tolerated():
            if self.cover_biv:
                self.cover.getImageReceiver().clearImage()
                self.cover.setImageDrawable(_cls("android.graphics.drawable.ColorDrawable")(0))
            else:
                self.cover.setImageDrawable(None)
        return False

    def _tint_from_cover(self):
        if not self.tabmode:
            return
        if not self.p.get_setting("dynamic_tint", True):
            if tint.current() is not None:
                tint.set_current(None)
            return
        left = getattr(self, "_tint_left", 0)
        if left <= 0:
            return
        self._tint_left = left - 1
        bmp = None
        with tolerated():
            if self.cover_biv:
                bmp = self.cover.getImageReceiver().getBitmap()
        if bmp is None:
            with tolerated():
                mc0 = self.p._get_mc()
                bmp = self.p._info_cover(mc0, mc0.getPlayingMessageObject())
        if bmp is None:
            with tolerated():
                e = self.p._emb_get(self._cover_key)
                bmp = e if (e is not None and e is not False) else None
        c = None
        if bmp is not None:
            ready, c = tint.get(bmp, self.c_player_bg)
            if not ready:
                tint.request(bmp, self.c_player_bg)
                w = getattr(self, "_tint_wait", 0)
                if w < 8:
                    self._tint_wait, self._tint_left = w + 1, left
                    return
            self._tint_wait = 0
        if c is not None:
            last = getattr(self, "_tint_bmp", None)
            if last is not None and last[0] is bmp and last[1] != self._cover_key and self._tint_left > 0:
                return
            self._tint_bmp = (bmp, self._cover_key)
            self._tint_left, self._tint_got = 0, True
            if c != tint.current():
                tint.set_current(c)

    def _pick_show(self, m):
        k = self._key(m)
        if k is None:
            return
        self._pick_key, self._pick_t = k, time.monotonic()
        self._lib_update_playing_icons(k, False)
        label = (self._title_of(m), self._author_of(m))
        if label != self._mini_last:
            self._mini_last = label
            self.mini_title.setText(label[0])
            self.mini_sub.setText(label[1])
        if k != self._cover_key:
            self._cover_key = k
            self._tint_left, self._tint_got = 10, False
            self._cover_repeat_tries = 0
            self._cover_ok = self._set_cover(self.p._get_mc(), m)
            self._cover_retry = 40
        with tolerated():
            self.mini_glyph.setVisibility(4 if self._cover_ok else 0)
        self._mini_state = ("pl", False)
        self._paused = False
        self._mini_pause_ui(False)
        self._mini_empty_ui(False)

    def _pick_clear(self):
        self._pick_key = None

    def _mini_update(self):
        mc, pm = self._mini_playing()
        playing_key = self._key(pm) if pm is not None else None
        pk = self.__dict__.get("_pick_key")
        if pk is not None:
            if playing_key == pk or time.monotonic() - self._pick_t > 6.0:
                self._pick_key = None
            else:
                self._lib_update_playing_icons(pk, False)
                return
        try:
            self._lib_update_playing_icons(
          playing_key, bool(mc is None or pm is None or mc.isMessagePaused()))
        except Exception:
            self._lib_update_playing_icons(playing_key, pm is None)
        self._update_mini_like(pm if pm is not None else self._ghost_track())
        self._mini_empty_ui(pm is None)
        with tolerated():
            self._pb_reapply()
            self._pill_update()
        if pm is None:
            _c = getattr(self.p, "_closed", None)
            self._mini_frac = float(_c["frac"]) if _c else 0.0
            self._mini_fill_update()
            with tolerated():
                self._loc_want = False
                self._loc_fade(False)
            with tolerated():
                plx = self.p._get_playlist(mc) if mc is not None else None
                if (plx is None or int(plx.size()) == 0) and self.pl_size != 0 \
             and self.tabmode and self.drag is None and getattr(self.p, "_closed", None) is None:
                    self._reload()
            g = self._ghost_track()
            if g is not None:
                gk = self._key(g)
                if self._mini_state != ("ghost", gk):
                    self._mini_state = ("ghost", gk)
                    self.mini_title.setText(self._title_of(g))
                    self.mini_sub.setText(self._author_of(g))
                    self._mini_last = None
                    self._mini_pause_ui(True)
                    with tolerated():
                        self._cover_key = self._key(g)
                        self._cover_ok = self._set_cover(mc, g)
                return
            if self._mini_state != "none":
                self._mini_state = "none"
                with tolerated():
                    self.mini_glyph.setVisibility(0)
                self.mini_title.setText(strings("nothing_is_playing"))
                self.mini_sub.setText("")
                self._mini_pause_ui(True)
            return
        k = self._key(pm)
        pl = self.p._get_playlist(mc) if mc is not None else None
        if self.drag is None:
            if pl is not None and int(pl.size()) != self.pl_size and not self._build_active() \
                    and not getattr(self, "queue_load_pending", False):
                self.playing_key = k
                self._reload()
                self._snap_to_playing_predraw()
                self._scroll_to_playing()
            elif k != self.playing_key:
                self.playing_key = k
                self._on_track_changed()
                self._follow_playing()
        label = (self._title_of(pm), self._author_of(pm))
        if label != self._mini_last:
            first = self._mini_last is None
            self._mini_last = label
            d, self._swap_dir = getattr(self, "_swap_dir", 1), 1
            sh = self.dp(18)
            _swap.swap_text(self.mini_title, lambda: self.mini_title.setText(label[0]), sh, d, self.Run, not first)
            _swap.swap_text(self.mini_sub, lambda: self.mini_sub.setText(label[1]), sh, d, self.Run, not first)
        if k != self._cover_key:
            if self._cover_key is not None:
                _swap.pop_in(self.cover)
            self._cover_key = k
            self._tint_left, self._tint_got = 10, False
            self._cover_repeat_tries = 0
            self._cover_ok = self._set_cover(mc, pm)
            self._cover_retry = 40
        elif (not self._cover_ok or getattr(self, "_cover_src", None) != "bmp") \
       and self._cover_retry > 0:
            self._cover_retry -= 1
            self._cover_ok = self._set_cover(mc, pm)
        self._tint_from_cover()
        with tolerated():
            has = (self.cover.getImageReceiver().getBitmap() is not None) if self.cover_biv \
                else (self.cover.getDrawable() is not None)
            self.mini_glyph.setVisibility(4 if (has or self._cover_ok) else 0)
        paused = bool(mc.isMessagePaused())
        if self._mini_state != ("pl", paused):
            self._mini_state = ("pl", paused)
            self._paused = paused
            self._mini_pause_ui(paused)
            sp = self._styled_playing
            if sp is not None and sp >= 0:
                self._style_row(sp, sp)
        with tolerated():
            self._mini_frac = float(pm.audioProgress)
            self._mini_fill_update()
        if not self.seeking:
            self.mini_bar.setProgress(int(float(pm.audioProgress) * 1000))
            self.mini_cur.setText(_fmt_time(pm.audioProgressSec))
            self.mini_dur.setText(_fmt_time(pm.getDuration()))
        self._update_locate_visibility()

    def _theme_same(self):
        try:
            return (self._theme("key_windowBackgroundWhiteBlackText", _argb(255, 33, 33, 33)) == self.c_text
          and self._theme("key_windowBackgroundWhiteGrayText2", _argb(255, 138, 138, 138)) == self.c_sub
          and self._wanted_colors() == (self.c_accent, self.c_player_progress))
        except Exception:
            return False

    def reopen(self):
        old_keys = list(self.keys)
        self.p._editor = self
        self._closing = False
        if self.sel_mode:
            self._set_sel_mode(False)
        self._load()
        if self.tab != "queue":
            self._set_tab("queue")
        try:
            self._set_h(self.h_min)
        except Exception:
            self.cur_h = self.h_min
        self.win_start = self.win_end = 0
        self.queue_lazy_ready = False
        if self.keys != old_keys or not self.rows:
            self._refresh()
        else:
            self._choose_initial_loaded_range(self._playing_pos())
            self._on_track_changed()
            self._update_title()
        self._mini_state = None
        self._mini_last = None
        self._like_sig = None
        self._cover_key = None
        win = self.dialog.getWindow()
        self.dialog.show()
        with tolerated():
            win = self.dialog.getWindow()
            win.setLayout(self._sheet_w(), self.h_max)
            win.setGravity(80)
        self.mini_run = self.Run(self._mini_tick)
        self._mini_update()
        self.handler.postDelayed(self.mini_run, 500)
        self.handler.postDelayed(self.Run(self._scroll_to_playing), 90)
        self.p._update_schedule()

    def _on_dismiss(self, *_):
        self.drag = None
        self.ticking = False
        self.queue_data_token += 1
        self.queue_load_pending = False
        if getattr(self.p, "_editor", None) is self:
            self.p._editor = None
        with tolerated():
            if not self.tabmode and bool(self.p.get_setting("keep_sheet_alive", True)):
                self.p._kept_editor = self
        self._lyr_running = False
        for r in (self.tick_run, getattr(self, "mini_run", None), getattr(self, "lyr_run", None),
       getattr(self, "undo_action_run", None), getattr(self, "undo_expire_run", None)):
            if r is not None:
                with tolerated():
                    self.handler.removeCallbacks(r)
        with tolerated():
            self._hide_undo()

    def _sel_menu(self):
        n = len(self.sel)
        all_on = n >= len(self.items)
        hero = [(strings("play_next"), lambda: self._sel_move("next"), False),
       (strings("move_to_end"), lambda: self._sel_move("end"), False),
       (strings("add_to"), lambda: self.p._lib_add_to_sheet(
       self.act, lambda cb: cb(self._sel_items()), strings("selection"), strings("n_selected", n),
       end_of_queue=False), False, ("msg_add",)),
       (strings("remove"), self._sel_remove, True)]
        self.p._selection_sheet(
       self.act, strings("n_selected", n), "", hero,
       None if all_on else (strings("select_all"), "", False, self._sel_all),
       self._sel_forward, self._sel_music,
       done=(strings("clear_selection"), "", False, lambda: self._set_sel_mode(False)),
       download=self._sel_download, count=n,
       items=self._sel_items, cancel=self._sel_cancel)

    def _open_menu(self):
        from ..sheets import _ActionSheet
        if self.tab == "lyrics":
            self._lyr_menu()
            return
        if self.sel_mode:
            self._sel_menu()
            return
        lock_queue = bool(self.p.get_setting("lock_queue", False))
        quick = [
       (strings("add_to"), self._menu_add_current_queue, False, ("msg_add",)),
       (strings("select_all"), self._menu_select_all, False),
       (strings("clear_queue"), self._menu_clear, True, ("filled_clear", "msg_close")),
       ]
        opts = [
       (strings("sort_tracks"), strings("sort_by_title_artist_duration_or"), False, self._queue_sort_menu),
       (strings("lock_queue"), strings("prevents_queue_regeneration_when_track_played"), False,
       self._menu_lock_queue, strings("state_on") if lock_queue else strings("state_off"),
       lambda: bool(self.p.get_setting("lock_queue", False))),
       None,
       self.p._share_playlist_opt(
       self._queue_detail_name(),
       lambda cb: cb([m for m in self.items if m is not None])),
       (strings("set_as_profile_playlist"), strings("use_the_queue_as_your_profile"), False,
       self._menu_profile_playlist),
       None,
       (strings("open_telegrams_player"), strings("the_built_in_full_player"), False, self._menu_tg_player),
       (strings("open_music_settings"), strings("configure_music"), False, self.p._open_plugin_settings),
       ]
        n = len(self.items)
        _ActionSheet(self.p, self.act).show_sheet(
       strings("queue"), self._lib_tracks_meta(n, self._lib_message_minutes(self.items)), opts, quick)

    def _prompt_text(self, title, initial, hint, on_save):
        act, dp, LP = self.act, self.dp, self.LP
        LL = jclass("android.widget.LinearLayout")
        ET = jclass("android.widget.EditText")
        Dialog = jclass("android.app.Dialog")
        GD = jclass("android.graphics.drawable.GradientDrawable")
        CD = jclass("android.graphics.drawable.ColorDrawable")
        dlg = Dialog(act)
        dlg.requestWindowFeature(1)
        root = LL(act)
        root.setOrientation(1)
        bg = GD()
        bg.setColor(self.c_bg)
        bg.setCornerRadius(float(dp(18)))
        root.setBackground(bg)
        root.setPadding(dp(20), dp(18), dp(20), dp(8))
        root.addView(self._text(title, 18, self.c_text, bold=True), LP(-1, -2))
        et = ET(act)
        et.setText(initial or "")
        et.setHint(hint)
        et.setSingleLine(True)
        et.setTextColor(self.c_text)
        et.setHintTextColor(self.c_sub)
        lp = LP(-1, -2)
        lp.setMargins(0, dp(10), 0, dp(6))
        root.addView(et, lp)
        row = LL(act)
        row.setOrientation(0)
        row.setGravity(21)
        def done():
            text = str(et.getText()).strip()[:60]
            with tolerated():
                dlg.dismiss()
            on_save(text)
        for label, fn, bold in ((strings("cancel"), lambda: dlg.dismiss(), False), (strings("save"), done, True)):
            b = self._text(label, 15, self.c_accent if bold else self.c_sub, bold=True, gravity=17)
            b.setPadding(dp(16), dp(12), dp(16), dp(12))
            b.setOnClickListener(self.Click(lambda v, f=fn: f()))
            row.addView(b, LP(-2, -2))
        root.addView(row, LP(-1, -2))
        dlg.setContentView(root)
        dlg.setCanceledOnTouchOutside(True)
        win = dlg.getWindow()
        if win is not None:
            win.setBackgroundDrawable(CD(0))
            win.setLayout(int(act.getResources().getDisplayMetrics().widthPixels * 0.9), -2)
            win.setGravity(17)
            with tolerated():
                win.setSoftInputMode(16 | 4)
        dlg.show()
        with tolerated():
            et.requestFocus()
            et.selectAll()

    def _menu_add_current_queue(self):
        items = [m for m in self.items if m is not None]
        if not items:
            self.p._bulletin(strings("queue_is_empty"), error=True)
            return
        self.p._lib_add_to_sheet(
       self.act, lambda cb: cb(list(items)),
       default_name=self.p._origin_display(),
       subtitle=self._lib_tracks_meta(len(items), self._lib_message_minutes(items)),
       end_of_queue=False)

    def _menu_tg_player(self):
        self._after_close(self.p._open_tg_player)

    def _menu_profile_playlist(self):
        items = [m for m in self.items if m is not None]
        if not items:
            self.p._bulletin(strings("queue_is_empty"), error=True)
            return
        self.p._profile_playlist_sheet(self.act, strings("queue"), lambda cb: cb(list(items)), len(items))

    def _build_active(self):
        b = getattr(self.p, "_queue_build_state", None)
        return b is not None and b.get("token") == getattr(self.p, "_queue_build_token", None)

    def _set_progressive_items(self, state, full=True):
        with tolerated():
            if self.drag is not None:
                return
            now = time.monotonic()
            gap = now - getattr(self, "_prog_t", 0.0)
            if gap < 0.35:
                if not getattr(self, "_prog_pend", False):
                    self._prog_pend = True
                    def _later(st=state, fu=full):
                        self._prog_pend = False
                        self._set_progressive_items(st, fu)
                    self.handler.postDelayed(self.Run(_later), int((0.35 - gap) * 1000) + 20)
                return
            self._prog_t = now
            vis = state.get("visible") or []
            vkeys = state.get("vkeys") or []
            items, keys = [], []
            for idx, m in enumerate(vis):
                if m is None:
                    continue
                k = vkeys[idx] if idx < len(vkeys) else None
                items.append(m)
                keys.append(k if k is not None else self._key(m))
            mc = self.p._get_mc()
            playing = None
            with tolerated():
                playing = mc.getPlayingMessageObject() if mc is not None else None
            pl = self.p._get_playlist(mc) if mc is not None else None
            self.items, self.keys = items, keys
            self._rebuild_key_index()
            self.ghost = False
            self.reversed = bool(state.get("rev", False))
            self.playing_key = self._key(playing) if playing is not None else state.get("first_key")
            self.pl_size = int(pl.size()) if pl is not None else len(items)
            self.queue_lazy_ready = True
            self.win_start = self.win_end = 0
            self._refresh(reset_loaded_range=True)

    def _progressive_flush(self, state):
        try:
            if state is None or self.ghost:
                return True
            pend = state.get("pending")
            if not pend:
                return True
            batches = list(pend)
            del pend[:]
            mc = self.p._get_mc()
            pl = self.p._get_playlist(mc) if mc is not None else None
            present = set(self.keys)
            shifted = created = False
            for where, pairs in batches:
                fm, fk = [], []
                for m, k in pairs:
                    if k is None:
                        k = self._key(m)
                    if k is None or k in present:
                        continue
                    present.add(k)
                    fm.append(m)
                    fk.append(k)
                if not fm:
                    continue
                if where == "end":
                    p = len(self.keys)
                elif where == "front":
                    p = 0
                else:
                    try:
                        p = self.keys.index(state.get("before_key") or state.get("first_key"))
                    except ValueError:
                        p = 0
                n = len(fm)
                self.items[p:p] = fm
                self.keys[p:p] = fk
                if not self.rows:
                    continue
                if p <= self.win_start:
                    self.win_start += n
                    self.win_end += n
                    self._shift_queue_rows(n)
                    shifted = True
                elif p < self.win_end:
                    self._shift_queue_rows(n, from_index=p)
                    self.win_end += n
                    self._rebuild_key_index()
                    pi = self._playing_pos()
                    at = p - self.win_start
                    for j in range(n):
                        row = self._make_row(p + j, self.items[p + j], pi)
                        self.container.addView(row, at + j, self.LP(-1, self.H))
                        self.rows.insert(at + j, row)
                    shifted = created = True
            self._rebuild_key_index()
            prev_playing = self.playing_key
            playing = None
            with tolerated():
                playing = mc.getPlayingMessageObject() if mc is not None else None
            if playing is not None:
                self.playing_key = self._key(playing)
            if self.playing_key != prev_playing:
                pi = self._playing_pos()
                for i in list(self.row_refs.keys()):
                    self._style_row(i, pi)
                self._styled_playing = pi
            if shifted:
                self.queue_data_token += 1
                self.queue_load_pending = False
            if pl is not None:
                self.pl_size = int(pl.size())
                if self.pl_size != len(self.items) and self.drag is None:
                    self._reload()
                    self.handler.postDelayed(self.Run(self._scroll_to_playing), 70)
                    return False
            if not self.rows and self.items:
                self.win_start = self.win_end = 0
                self._refresh(reset_loaded_range=True)
                return True
            self.queue_lazy_ready = True
            self._update_title()
            if created:
                self.handler.postDelayed(self.Run(self._load_visible_covers), 40)
            self.handler.postDelayed(self.Run(self._maybe_load_queue_rows), 60)
            return True
        except Exception:
            return True

    def _on_handle_row(self, box, row, v, e):
        with tolerated():
            if int(e.getActionMasked()) == 0 and self.drag is None:
                st = getattr(self.p, "_queue_build_state", None)
                if st is not None and not self._progressive_flush(st):
                    return False
        return self._on_handle(box[0] - self.win_start, row, v, e)

    def _shift_queue_rows(self, delta, from_index=None):
        refs = {}
        for i, R in self.row_refs.items():
            ni = int(i)
            if from_index is None or ni >= int(from_index):
                ni += int(delta)
            refs[ni] = R
            box = R.get("idx_box")
            if box:
                box[0] = ni
        self.row_refs = refs

    def _append_tail(self):
        try:
            mc = self.p._get_mc()
            pl = self.p._get_playlist(mc) if mc is not None else None
            if pl is None or self.ghost or self.drag is not None or not self.items or not self.rows:
                return self._reload()
            shuffle_on, rev = self.p._read_order()
            if bool(rev and not shuffle_on) != bool(self.reversed):
                return self._reload()
            raw = [pl.get(i) for i in range(int(pl.size()))]
            new_items = raw if self.reversed else raw[::-1]
            n0 = len(self.items)
            new_keys = [self._key(m) for m in new_items]
            if len(new_items) <= n0 or new_keys[:n0] != list(self.keys):
                return self._reload()
            self.items.extend(new_items[n0:])
            self.keys.extend(new_keys[n0:])
            self._rebuild_key_index()
            self.pl_size = int(pl.size())
            if self.win_end >= n0:
                pi = self._playing_pos()
                for i in range(n0, len(self.items)):
                    row = self._make_row(i, self.items[i], pi)
                    self.container.addView(row, self.LP(-1, self.H))
                    self.rows.append(row)
                self.win_end = len(self.items)
            self.queue_data_token += 1
            self.queue_load_pending = False
            self.queue_lazy_ready = True
            self._update_title()
            self.handler.postDelayed(self.Run(self._load_visible_covers), 40)
            self.handler.postDelayed(self.Run(self._maybe_load_queue_rows), 60)
        except Exception:
            self._reload()

    def _ghost_changed(self, inserted):
        if not inserted:
            self._ghost_render()
            return
        if getattr(self, "_ghost_pend", False):
            return
        self._ghost_pend = True
        def run():
            self._ghost_pend = False
            with tolerated():
                if not self.dialog.isShowing() or self.drag is not None:
                    return
                sy = int(self.scroll.getScrollY())
                self._reload()
                self.handler.postDelayed(self.Run(lambda: self.scroll.scrollTo(0, sy)), 40)
        self.handler.postDelayed(self.Run(run), 400)

    def _ghost_render(self):
        box = getattr(self, "ghost_box", None)
        if box is None:
            return
        with tolerated():
            box.removeAllViews()
        if self.ghost or self.tab != "queue" or not self.items:
            return
        gl = self.p._ghost_list()
        if not gl:
            return
        LL = _cls("android.widget.LinearLayout")
        PB = _cls("android.widget.ProgressBar")
        shown = gl[:200]
        for k, t, st in shown:
            row = LL(self.act)
            row.setOrientation(0)
            row.setGravity(16)
            row.setPadding(self.dp(16), 0, self.dp(16), 0)
            lead = _cls("android.widget.FrameLayout")(self.act)
            if st == "failed":
                lead.addView(self._glyph_icon(("msg_retry", "ic_refresh", "msg_reset"), self.c_accent, pad=10, size=22, bold=True),
                             _cls("android.widget.FrameLayout$LayoutParams")(-1, -1))
            else:
                pb = PB(self.act)
                with tolerated():
                    pb.setIndeterminateTintList(_cls("android.content.res.ColorStateList").valueOf(self.c_sub))
                pb.setPadding(self.dp(10), self.dp(10), self.dp(10), self.dp(10))
                lead.addView(pb, _cls("android.widget.FrameLayout$LayoutParams")(-1, -1))
            row.addView(lead, self.LP(self.dp(44), self.dp(44)))
            col = LL(self.act)
            col.setOrientation(1)
            col.setPadding(self.dp(12), 0, 0, 0)
            col.addView(self._text((t or {}).get("t") or strings("audio"), 15, self.c_text, single=True), self.LP(-2, -2))
            col.addView(self._text(strings("couldnt_load_tap_to_retry") if st == "failed" else strings("loading_song"),
                                   12, self.c_accent if st == "failed" else self.c_sub, single=True), self.LP(-2, -2))
            col.setAlpha(0.8)
            row.addView(col, self.LP(-2, -2))
            if st == "failed":
                row.setOnClickListener(self.Click(lambda v, kk=k: (self.p._resolver.retry([kk]), self._ghost_render())))
            else:
                row.setOnClickListener(self.Click(lambda v: self.p._bulletin(strings("still_loading_this_song"))))
            box.addView(row, self.LP(-1, self.H))
        extra = len(gl) - len(shown)
        if extra > 0:
            box.addView(self._text(strings("loading_n", extra).strip(" ·"), 13, self.c_sub, gravity=17), self.LP(-1, self.H))

    def _reload(self):
        self.win_start = self.win_end = 0
        self.queue_lazy_ready = False
        if self._load() or self.tabmode:
            self._refresh()
        else:
            self.dialog.dismiss()

    def _menu_clear(self):
        from ..sheets import _ActionSheet
        if bool(self.p.get_setting("lock_queue", False)):
            def clear_locked():
                removed, kept = self.p._clear_queue()
                if removed:
                    self.p._bulletin(strings("cleared_n_tracks", removed)
                + (strings("kept_the_playing_one") if kept else ""))
                self._reload()
            _ActionSheet(self.p, self.act).show_sheet(
          strings("clear_locked_queue"), strings("the_current_track_will_keep_playing"),
          [(strings("clear_queue"), strings("remove_the_other_queued_tracks"), True, clear_locked)])
            return
        removed, kept = self.p._clear_queue()
        if removed:
            self.p._bulletin(strings("cleared_n_tracks", removed)
          + (strings("kept_the_playing_one") if kept else ""))
        self._reload()

    def _queue_sort_menu(self):
        n = len(self.items)
        def apply(mode, desc):
            if mode == "shuffle":
                self._menu_shuffle()
                return
            snap = self.p._sort_queue(mode, bool(desc))
            if snap is None:
                self.p._bulletin(strings("nothing_to_sort"), error=True)
                return
            self._reload()
            self._start_undo(snap, text=strings("list_sorted"), done_text=strings("sort_undone"))
        self._lib_sort_sheet(
       strings("sort_queue"), self._lib_tracks_meta(n, self._lib_message_minutes(self.items)),
       [("title", strings("title"), strings("track_title")),
       ("artist", strings("artist"), strings("artist_name")),
       ("duration", strings("duration"), strings("track_length")),
       ("shuffle", strings("shuffle"), strings("random_order"))],
       apply,
       extra=[(strings("reverse_order"), strings("reverse_the_current_track_order"), False, self._menu_reverse)])

    def _menu_reverse(self):
        snap = self.p._reverse_queue()
        if snap is None:
            self.p._bulletin(strings("nothing_to_reverse"), error=True)
            return
        self._reload()
        self._start_undo(snap, text=strings("queue_reversed"), done_text=strings("reverse_undone"))

    def _menu_shuffle(self):
        snap = self.p._shuffle_queue()
        if snap is None:
            self.p._bulletin(strings("nothing_to_shuffle"), error=True)
            return
        self._reload()
        self._start_undo(snap, text=strings("queue_shuffled"), done_text=strings("shuffle_undone"))


    def _menu_lock_queue(self):
        on = not bool(self.p.get_setting("lock_queue", False))
        self.p.set_setting("lock_queue", on)

    UNDO_SECONDS = 5

    def _start_undo(self, snap, text=strings("queue_shuffled"), restore=None, done_text=strings("shuffle_undone")):
        self._hide_undo()
        self.undo_restore = restore
        self.undo_done_text = done_text
        self.undo_snap = snap
        self.undo_token += 1
        token = self.undo_token
        def undo_action():
            if token == self.undo_token and self.undo_snap is snap:
                self._undo()
        def expire_action():
            if token == self.undo_token and self.undo_snap is snap:
                self._hide_undo(hide_bulletin=False)
        self.undo_action_run = self.Run(undo_action)
        self.undo_expire_run = self.Run(expire_action)
        try:
            fragment = get_last_fragment()
            factory_cls = find_class("org.telegram.ui.Components.BulletinFactory")
            factory = factory_cls.of(fragment)
            bulletin = factory.createUndoBulletin(
          text, self.undo_action_run, self.undo_expire_run)
            self.undo_bulletin = bulletin
            bulletin.show()
        except Exception:
            try:
                fragment = get_last_fragment()
                factory_cls = find_class("org.telegram.ui.Components.BulletinFactory")
                factory = factory_cls.of(fragment)
                bulletin_cls = find_class("org.telegram.ui.Components.Bulletin")
                duration = int(getattr(bulletin_cls, "DURATION_PROLONG", self.UNDO_SECONDS * 1000))
                bulletin = factory.createSimpleBulletin(
             0, text, strings("undo"), duration, False, self.undo_action_run)
                self.undo_bulletin = bulletin
                bulletin.show()
                self.handler.postDelayed(self.undo_expire_run, self.UNDO_SECONDS * 1000)
            except Exception:
                self.p._bulletin(text + strings("undo_unavailable_in_this_telegram_build"), error=True)
                self.handler.postDelayed(self.undo_expire_run, self.UNDO_SECONDS * 1000)

    def _hide_undo(self, hide_bulletin=True):
        self.undo_snap = None
        self.undo_token += 1
        for callback in (getattr(self, "undo_action_run", None),
       getattr(self, "undo_expire_run", None)):
            if callback is not None:
                with tolerated():
                    self.handler.removeCallbacks(callback)
        bulletin = getattr(self, "undo_bulletin", None)
        self.undo_bulletin = None
        self.undo_action_run = None
        self.undo_expire_run = None
        if hide_bulletin and bulletin is not None:
            with tolerated():
                bulletin.hide()

    def _undo(self):
        snap = self.undo_snap
        self._hide_undo()
        if snap is None:
            return
        restore = getattr(self, "undo_restore", None)
        try:
            ok = restore() if restore else self.p._restore_queue(snap)
        except Exception:
            ok = False
        done_text = getattr(self, "undo_done_text", strings("shuffle_undone"))
        if ok:
            try:
                BulletinHelper.show_success(done_text, get_last_fragment())
            except Exception:
                self.p._bulletin(done_text)
        else:
            self.p._bulletin(strings("queue_changed_cant_undo"), error=True)
        if not restore:
            self._reload()

    def _lib_undo_list(self, field, snap, text, done_text=None):
        def restore():
            d = self.p._lib_data()
            d[field] = list(snap[0])
            if field == "playlists":
                d["last"] = snap[1]
                if len(snap) > 2:
                    if snap[2] is None:
                        d.pop("pl_sort", None)
                    else:
                        d["pl_sort"] = snap[2]
            self.p._lib_save()
            with tolerated():
                self.p._request_library_refresh()
            with tolerated():
                self._lib_render()
            return True
        self._start_undo(snap, text, restore, done_text or strings("restored"))

    def _remove(self, m):
        if self._key(m) == self.playing_key:
            self.p._bulletin(strings("cant_remove_the_track_that_is"), error=True)
            return
        mc = self.p._get_mc()
        pl = self.p._get_playlist(mc) if mc is not None else None
        if pl is None:
            return
        y = int(self.scroll.getScrollY())
        ok = self.p._playlist_remove_by_id(mc, pl, m.getId(), m.getDialogId())
        self.p._resync_current(mc, pl)
        try:
            a = self.keys.index(self._key(m))
        except ValueError:
            a = -1
        if not ok or a < 0:
            self._reload()
            return
        self.items.pop(a)
        self.keys.pop(a)
        self.pl_size = int(pl.size())
        if a < self.win_end:
            self.win_end -= 1
        if not self.items:
            self.dialog.dismiss()
            return
        self._refresh(False, scroll_to=y)

    def _start_drag(self, idx, row, v, raw) -> bool:
        if self.drag is not None or self.queue_load_pending or len(self.rows) < 2:
            return False
        self.drag = {
       "idx": idx, "row": row, "start_raw": raw, "raw": raw,
       "start_scroll": int(self.scroll.getScrollY()),
       "target": idx, "speed": 0,
       }
        row.setTranslationZ(float(self.dp(8)))
        a = idx + self.win_start
        self.drag["group"] = False
        if self.sel_mode and len(self.sel) > 1 and a < len(self.items) \
       and self._key(self.items[a]) in self.sel:
            self.drag["group"] = True
            for j, r in enumerate(self.rows):
                if j != idx and self._key(self.items[self.win_start + j]) in self.sel:
                    r.setAlpha(0.45)
            R = self.row_refs.get(a)
            if R:
                R["t1"].setText(strings("n_tracks", len(self.sel)))
                R["t2"].setVisibility(8)
        with tolerated():
            v.getParent().requestDisallowInterceptTouchEvent(True)
            v.performHapticFeedback(0)
        return True

    def _on_handle(self, idx, row, v, e):
        a = int(e.getActionMasked())
        if a == 0:
            return bool(self._start_drag(idx, row, v, float(e.getRawY())))
        if self.drag is None:
            return False
        if a == 2:
            self.drag["raw"] = float(e.getRawY())
            self._update_drag()
            return True
        if a in (1, 3):
            self._finish(cancel=(a == 3))
            return True
        return False

    def _update_drag(self):
        d = self.drag
        if d is None:
            return
        H = self.H
        n = len(self.rows)
        idx = d["idx"]
        dy = (d["raw"] - d["start_raw"]) + (self.scroll.getScrollY() - d["start_scroll"])
        dy = max(-idx * H, min((n - 1 - idx) * H, dy))
        d["row"].setTranslationY(float(dy))
        target = int((idx * H + dy) / H + 0.5)
        target = max(0, min(n - 1, target))
        if target != d["target"]:
            d["target"] = target
            for j, r in enumerate(self.rows):
                if j == idx:
                    continue
                if idx < j <= target:
                    ty = -H
                elif target <= j < idx:
                    ty = H
                else:
                    ty = 0
                r.animate().translationY(float(ty)).setDuration(120).start()
        loc = jarray(jint)(2)
        self.scroll.getLocationOnScreen(loc)
        top = int(loc[1]) + int(self.scroll.getPaddingTop())
        bottom = int(loc[1]) + int(self.scroll.getHeight()) - int(self.scroll.getPaddingBottom())
        edge = self.dp(56)
        speed = 0
        if d["raw"] < top + edge:
            speed = -self.dp(8)
        elif d["raw"] > bottom - edge:
            speed = self.dp(8)
        d["speed"] = speed
        if speed != 0 and not self.ticking:
            self.ticking = True
            self.handler.postDelayed(self.tick_run, 16)

    def _auto_tick(self):
        d = self.drag
        if d is None or d.get("speed", 0) == 0:
            self.ticking = False
            return
        self.scroll.scrollBy(0, int(d["speed"]))
        self._update_drag()
        self.handler.postDelayed(self.tick_run, 16)

    def _finish(self, cancel=False):
        d = self.drag
        self.drag = None
        self.ticking = False
        with tolerated():
            self.handler.removeCallbacks(self.tick_run)
        if d is None:
            return
        with tolerated():
            d["row"].setTranslationZ(0.0)
        idx, tgt = d["idx"], d["target"]
        y = int(self.scroll.getScrollY())
        if cancel or tgt == idx:
            self._refresh(False, scroll_to=y)
            return
        a, b = idx + self.win_start, tgt + self.win_start
        if d.get("group"):
            sel_items = [m for m in self.items if self._key(m) in self.sel]
            L2 = self.items[:]
            L2.insert(b, L2.pop(a))
            k = sum(1 for m in L2[:b] if self._key(m) not in self.sel)
            rest = [m for m in self.items if self._key(m) not in self.sel]
            new_items = rest[:k] + sel_items + rest[k:]
            if self._commit(new_items):
                self.items = new_items
                self.keys = [self._key(m) for m in new_items]
                self._rebuild_key_index()
            else:
                self._load()
            self._refresh(False, scroll_to=y)
            return
        new_items = self.items[:]
        new_items.insert(b, new_items.pop(a))
        if self._commit(new_items):
            self.items = new_items
            self.keys.insert(b, self.keys.pop(a))
            self._rebuild_key_index()
        else:
            self._load()
        self._refresh(False, scroll_to=y)
