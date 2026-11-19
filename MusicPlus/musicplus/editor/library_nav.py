import json
import threading
from ..compat import (
 find_class,
 jarray,
 jclass,
 jint,
 run_on_ui_thread,
 set_private_field,
)
from elyx import strings
from ..helpers import _pln
from ..helpers import _LIB_DYN, _argb
from ..android import _PIN_ICONS, _backcb_proxy, _cls, _mix, _viewlong_proxy, _wide_px
from ..glass import _PillRow
from ..stores import _IndexedTrackView
from ..safe import tolerated


class _QueueEditorLibraryNav:
    def _lib_can_back(self):
        if self._lib_selecting() or getattr(self, "sel_mode", False):
            return True
        return self.tab == "library" and self.lib_state != ("home", None)

    def _lib_selecting(self):
        return bool(self.lib_sel_mode) and self.tab == "library"

    def _lib_back_or(self, fallback):
        if self._lib_selecting():
            self._lib_reset_selection(self.lib_sel_context)
        else:
            fallback()

    def _lib_back(self):
        if not self._lib_can_back():
            return False
        if self._lib_selecting():
            self._lib_reset_selection(self.lib_sel_context)
        elif getattr(self, "sel_mode", False):
            self._exit_sel()
        else:
            self._lib_go("home")
        return True

    def _lib_on_key(self, code, event):
        if code != 4 or not self._lib_can_back():
            return False
        if int(event.getAction()) == 1:
            self._lib_back()
        return True

    def _lib_sync_back_cb(self):
        dlg = self.dialog
        if self.tabmode or not hasattr(dlg, "getOnBackInvokedDispatcher"):
            return
        want = self._lib_can_back()
        cb = getattr(self, "_back_cb", None)
        try:
            disp = dlg.getOnBackInvokedDispatcher()
            if want and cb is None:
                cb = self._back_cb = _backcb_proxy()(self._lib_back)
                disp.registerOnBackInvokedCallback(1, cb)
            elif not want and cb is not None:
                disp.unregisterOnBackInvokedCallback(cb)
                self._back_cb = None
        except Exception:
            self._back_cb = None

    def _lib_pinned_artists(self):
        try:
            raw = self.p.get_setting("pinned_artists", "[]")
            values = json.loads(raw) if isinstance(raw, str) else raw
            return [str(x) for x in values or []]
        except Exception:
            return []

    def _lib_toggle_pin_artist(self, key, name=None):
        pinned = self._lib_pinned_artists()
        was = key in pinned
        if was:
            pinned.remove(key)
        else:
            pinned.append(key)
        self.p.set_setting("pinned_artists", json.dumps(pinned))
        self._lib_render()

    def _update_library_search_button(self):
        with tolerated():
            if hasattr(self, "hdr_search"):
                self.hdr_search.setContentDescription(
             strings("close_library_search") if self.lib_search_active else strings("search_library"))

    def _set_library_search(self, active, clear=False, focus=False, rerender=True):
        self.lib_search_active = bool(active)
        if clear:
            self._lib_search_suppress = True
            self._lib_search_generation += 1
            self._lib_search_pending_query = ""
            self.lib_search_query = ""
            with tolerated():
                self.lib_search_input.setText("")
            self._lib_search_suppress = False
        with tolerated():
            self.lib_search_bar.setVisibility(0 if self.lib_search_active else 8)
        self._update_library_search_button()
        if self.lib_search_active and focus:
            with tolerated():
                self.lib_search_input.requestFocus()
                self.handler.postDelayed(self.Run(lambda: self._show_library_search_keyboard()), 100)
        elif not self.lib_search_active:
            self._hide_library_search_keyboard()
        if rerender:
            self._lib_render()

    def _show_library_search_keyboard(self):
        with tolerated():
            imm = self.act.getSystemService("input_method")
            imm.showSoftInput(self.lib_search_input, 0)

    def _hide_library_search_keyboard(self):
        with tolerated():
            imm = self.act.getSystemService("input_method")
            imm.hideSoftInputFromWindow(self.lib_search_input.getWindowToken(), 0)

    def _toggle_library_search(self):
        if not self.lib_search_active:
            self._set_library_search(True, focus=True)
        else:
            self._set_library_search(False, clear=True)

    def _lib_go(self, kind, ref=None, select=None):
        if kind == "chat" and ref is not None:
            sel = self.__dict__.setdefault("lib_topic_sel", {})
            sel.pop(tuple(ref), None)
            if select:
                sel[tuple(ref)] = select
        if kind == "artist" and ref is not None:
            sel = self.__dict__.setdefault("lib_album_sel", {})
            sel.pop(str(ref), None)
            if select is not None:
                sel[str(ref)] = select
        prev = self.lib_state
        if prev and prev[0] == "pl" and prev != (kind, ref):
            self.__dict__.get("_pl_ghosts", {}).pop(prev[1], None)
        self.lib_state = (kind, ref)
        self.lib_confirm = None
        self.lib_resolved.clear()
        self.lib_track_loader = None
        self._lib_reset_selection(None)
        self._lib_render()
        with tolerated():
            self.lib_sv.scrollTo(0, 0)
        if (kind, ref) != self.__dict__.get("_lib_nav_last"):
            self._lib_nav_last = (kind, ref)
            self._lib_nav_anim(back=(kind == "home"))

    def _lib_nav_anim(self, back=False):
        try:
            root = self.lib_page_root
            if self.tab != "library" or self._tab_anim is not None or self._tab_post is not None:
                return
            w = int(root.getWidth()) or int(self.stage.getWidth())
            if w <= 0:
                return
            root.animate().cancel()
            root.setTranslationX(float(-w * 0.18 if back else w * 0.22))
            root.setAlpha(0.0)
            root.animate().translationX(0.0).alpha(1.0).setDuration(260) \
          .setInterpolator(_cls("android.view.animation.DecelerateInterpolator")(2.0)) \
          .withLayer().start()
        except Exception:
            with tolerated():
                self.lib_page_root.setTranslationX(0.0)
                self.lib_page_root.setAlpha(1.0)

    def _lib_render(self):
        self._lib_rtok = self.__dict__.get("_lib_rtok", 0) + 1
        with tolerated():
            self.p._lib_sync_names()
        self.lib_loaded = True
        self.lib_queue_cache_ready = False
        self.lib_box.removeAllViews()
        with tolerated():
            self.lib_fab_host.animate().cancel()
            self.lib_fab_host.setTranslationY(0.0)
            self.lib_fab_host.setAlpha(1.0)
            self._lib_fab_shown = True
            self._lib_fab_last_y = 0
            self.lib_fab_host.removeAllViews()
            self.lib_fab_host.setVisibility(8)
            self.lib_root.setPadding(0, self.dp(2), 0, self.dp(14))
        with tolerated():
            self.lib_detail_header_host.removeAllViews()
            is_detail = self.lib_state[0] != "home"
            self.lib_detail_header_host.setVisibility(0 if is_detail else 8)
            self.main_header.setVisibility(8 if is_detail and self.tab == "library" else 0)
        self.lib_covers = []
        if len(self.__dict__.get("_lib_cvc", ())) > 120:
            self._lib_cvc.clear()
        self._lib_cvu = set()
        self.lib_artist_views = {}
        self.lib_reorder_rows = {"playlists": [], "chats": [], "friends": []}
        self.lib_track_rows = {}
        self.lib_track_reorder_rows = []
        self.lib_track_loader = None
        self.lib_empty_progress_text = None
        self.lib_empty_progress_label = None
        kind, ref = self.lib_state
        try:
            if kind == "pl":
                self._lib_playlist_view(ref)
            elif kind == "chat":
                self._lib_chat_view(ref)
            elif kind == "friend":
                self._lib_friend_view(ref)
            elif kind == "artist":
                self._lib_artist_view(ref)
            elif kind == "home" and self.lib_search_active and self.lib_search_query.strip():
                self._lib_search_results()
            else:
                self._lib_home()
        except Exception:
            self._lib_hint(strings("library_couldnt_load"))
        self._lib_sync_back_cb()
        try:
            self._lib_sig_done = self._lib_sig()
        except Exception:
            self._lib_sig_done = None
        with tolerated():
            self._lib_dsig_done = self._lib_data_sig()
        if not self.__dict__.get("_lib_pre"):
            self.handler.postDelayed(self.Run(self._lib_load_covers), 60)
            self.handler.postDelayed(self.Run(self._lib_maybe_load_more), 80)

    def _lib_data_sig(self):
        return (self.lib_state, bool(self.lib_search_active), str(self.lib_search_query),
                hash(self.p.get_setting("library_v1", "") or ""))

    def _lib_sig(self):
        return (self.lib_state, bool(self.lib_search_active), str(self.lib_search_query),
       hash(self.p.get_setting("library_v1", "") or ""), len(self.p._msg_cache),
       self._lib_cvsig())

    def _lib_fab_scroll(self):
        host = getattr(self, "lib_fab_host", None)
        if host is None or int(host.getVisibility()) != 0:
            return
        if _wide_px(self.act, 600):
            self._lib_fab_set(True)
            return
        sy = int(self.lib_sv.getScrollY())
        last = getattr(self, "_lib_fab_last_y", sy)
        self._lib_fab_last_y = sy
        dy = sy - last
        if abs(dy) < self.dp(4) and sy > 0:
            return
        if sy <= 0:
            self._lib_fab_set(True)
        elif dy > 0:
            self._lib_fab_set(False)
        elif dy < 0:
            self._lib_fab_set(True)

    def _lib_fab_set(self, show):
        host = self.lib_fab_host
        if getattr(self, "_lib_fab_shown", True) == show:
            return
        self._lib_fab_shown = show
        with tolerated():
            dist = float(int(host.getHeight()) + self.dp(16) + self.dp(8))
            host.animate().cancel()
            host.animate().translationY(0.0 if show else dist).alpha(1.0 if show else 0.0) \
          .setDuration(220).start()

    def _lib_on_scroll(self):
        self._mini_follow(self.lib_sv)
        with tolerated():
            self._lib_fab_scroll()
        self._lib_load_covers()
        self._lib_maybe_load_more()

    def _lib_load_covers(self):
        with tolerated():
            sy = int(self.lib_sv.getScrollY())
            h = int(self.lib_sv.getHeight()) or self.dp(520)
            top, bot = sy - self.H * 2, sy + h + self.H * 2
            hq = bool(self.p.get_setting("hq_thumbs", True))
            d = self.COVER_DP * 2 if hq else self.COVER_DP
            flt = f"{d}_{d}"
            covers = self.lib_covers
            lo, hi = 0, len(covers)
            while lo < hi:
                mid = (lo + hi) // 2
                row = covers[mid].get("row")
                y0 = int(row.getTop()) if row is not None else 0
                if y0 + self.H < top:
                    lo = mid + 1
                else:
                    hi = mid
            i = max(0, lo - 2)
            while i < len(covers):
                c = covers[i]
                row = c.get("row")
                y0 = int(row.getTop()) if row is not None else 0
                if y0 > bot:
                    break
                if not c["done"] and y0 + self.H >= top:
                    c["done"] = True
                    ok = bool(self._load_cover(c["art"], c["m"], 0, flt, hq))
                    if ok:
                        c["chk"], c["chk_n"] = True, 0
                        self._lib_cover_check_later(1200)
                    else:
                        ok = self._lib_embedded(c)
                        if ok is False and not c.get("emb_known"):
                            c["tries"] = c.get("tries", 0) + 1
                            if c["tries"] < 3:
                                c["done"] = False
                                self._lib_cover_check_later(3000)
                    if c.get("scrim") is not None:
                        c["scrim"].setVisibility(0 if ok else 8)
                    if ok and c.get("glyph") is not None:
                        c["glyph"].setVisibility(8)
                i += 1

    def _lib_embedded(self, c):
        m = c.get("m")
        if m is None:
            return False
        k = self.p._msg_key(m)
        if k is None:
            return False
        bmp = self.p._emb_get(k)
        if bmp:
            c["art"].setImageBitmap(bmp)
            return True
        if bmp is False:
            c["emb_known"] = True
            return False
        if self.p._emb_fetch(m, lambda: self._lib_apply_embedded(k)):
            return None
        return False

    def _lib_apply_embedded(self, k):
        bmp = self.p._emb_get(k)
        if not bmp:
            return
        for c in list(self.lib_covers):
            with tolerated():
                m = c.get("m")
                if c.get("art") is not None and m is not None and self.p._msg_key(m) == k:
                    c["art"].setImageBitmap(bmp)
                    c["chk"] = False
                    if c.get("glyph") is not None:
                        c["glyph"].setVisibility(8)
                    if c.get("scrim") is not None:
                        c["scrim"].setVisibility(0)

    def _lib_cover_check_later(self, delay):
        if getattr(self, "_lib_cov_retry", False):
            return
        self._lib_cov_retry = True

        def run():
            self._lib_cov_retry = False
            with tolerated():
                if self.dialog.isShowing():
                    self._lib_verify_covers()
        self.handler.postDelayed(self.Run(run), delay)

    def _lib_verify_covers(self):
        again = False
        for c in list(self.lib_covers):
            if not c.get("chk"):
                continue
            with tolerated():
                if c["art"].getImageReceiver().getBitmap() is not None:
                    c["chk"] = False
                    continue
            c["chk_n"] = c.get("chk_n", 0) + 1
            ok = self._lib_embedded(c)
            if ok:
                c["chk"] = False
                if c.get("glyph") is not None:
                    c["glyph"].setVisibility(8)
                if c.get("scrim") is not None:
                    c["scrim"].setVisibility(0)
            elif ok is False or c["chk_n"] >= 5:
                c["chk"] = False
            else:
                again = True
        if again:
            self._lib_cover_check_later(1200)

    def _lib_known(self, tracks, refresh=False):
        if refresh or not getattr(self, "lib_queue_cache_ready", False):
            self.p._lib_cache_queue()
            self.lib_queue_cache_ready = True
        return [self.p._msg_cache.get((int(t["i"]), int(t["d"]))) for t in tracks]

    def _lib_label(self, left, right="", action=None, action_description=strings("sort"), extra=None):
        LL = jclass("android.widget.LinearLayout")
        row = LL(self.act)
        row.setOrientation(0)
        row.setGravity(16)
        row.setMinimumHeight(self.dp(48))
        row.setPadding(self.dp(self.ROW_PAD_START), self.dp(14), self.dp(6), self.dp(2))
        row.addView(self._text(left, 15, self.c_accent, bold=True, single=True), self.LP(0, -2, 1.0))
        for ent in list(extra or []) + ([(strings("sort"), action, action_description)] if action else []):
            text, cb, desc = ent[0], ent[1], ent[2]
            long_cb = ent[3] if len(ent) > 3 else None
            button = self._text(text, 14, self.c_accent, bold=True, single=True, gravity=17)
            button.setPadding(self.dp(10), 0, self.dp(10), 0)
            button.setContentDescription(desc)
            button.setOnClickListener(self.Click(lambda v, f=cb: f()))
            if long_cb is not None:
                button.setOnLongClickListener(_viewlong_proxy()(lambda v, f=long_cb: (f(), True)[1]))
            row.addView(button, self.LP(-2, self.dp(32)))
        self.lib_box.addView(row, self.LP(-1, -2))

    def _lib_hint(self, text):
        tv = self._text(text, 13, self.c_sub)
        tv.setPadding(self.dp(self.ROW_PAD_START), self.dp(6), self.dp(16), self.dp(10))
        self.lib_box.addView(tv, self.LP(-1, -2))

    def _lib_detail_header(self, title, meta, back_cb, menu_cb,
    avatar_did=None, avatar_acc=0, avatar_view=None, sync_pid=None, sync_action=None):
        LL = jclass("android.widget.LinearLayout")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        row = LL(self.act)
        row.setOrientation(0)
        row.setGravity(16)
        row.setPadding(self.dp(10), self.dp(10), self.dp(10), self.dp(8))
        back = self._glyph_icon(("ic_ab_back", "msg_back", "msg_back_arrow"), self.c_text, pad=8, size=24, bold=True)
        back_bg = GD()
        back_bg.setShape(1)
        back_bg.setColor(_mix(self.c_bg, self.c_sub, 0.13))
        back.setBackground(back_bg)
        back.setContentDescription(strings("back_to_library"))
        back.setOnClickListener(self.Click(lambda v: self._lib_back_or(back_cb)))
        row.addView(back, self.LP(self.dp(40), self.dp(40)))
        if avatar_view is not None or avatar_did is not None:
            avatar = (avatar_view if avatar_view is not None else
          self._lib_avatar_tile(avatar_did, avatar_acc, self.dp(36)))
            avatar_lp = self.LP(self.dp(36), self.dp(36))
            avatar_lp.setMargins(self.dp(10), 0, 0, 0)
            row.addView(avatar, avatar_lp)
        title_col = LL(self.act)
        title_col.setOrientation(1)
        title_col.setGravity(16)
        title_col.setPadding(self.dp(12 if avatar_did is None else 10), 0, self.dp(6), 0)
        title_view = self._text(title, 19, self.c_text, bold=True, single=True)
        title_col.addView(title_view, self.LP(-1, -2))
        st = None
        if meta:
            st = self._text(meta, 13, self.c_sub, single=True)
            st.setPadding(0, self.dp(3), 0, 0)
            title_col.addView(st, self.LP(-1, -2))
        self.lib_detail_title = title_view
        self.lib_detail_meta = st
        self.lib_detail_base_title = title
        self.lib_detail_base_meta = meta
        row.addView(title_col, self.LP(0, -2, 1.0))
        if sync_pid is not None or sync_action is not None:
            try:
                sync_btn = self._lib_sync_btn(sync_pid, sync_action)
                sync_lp = self.LP(self.dp(40), self.dp(40))
                sync_lp.setMargins(0, 0, self.dp(8), 0)
                row.addView(sync_btn, sync_lp)
            except Exception:
                import traceback
                with tolerated():
                    self.p._pp_log("SYNC BUTTON FAILED: " + " | ".join(traceback.format_exc().strip().split("\n")[-3:]))
        more = self._glyph_icon(("ic_ab_other", "msg_more", "ic_more_vert"), self.c_text, pad=8, size=22, bold=True)
        more_bg = GD()
        more_bg.setShape(1)
        more_bg.setColor(_mix(self.c_bg, self.c_sub, 0.13))
        more.setBackground(more_bg)
        more.setContentDescription(strings("more_options"))
        more.setOnClickListener(self.Click(
       lambda v: self._lib_selection_menu() if self.lib_sel_mode else menu_cb()))
        row.addView(more, self.LP(self.dp(40), self.dp(40)))
        try:
            self.lib_detail_header_host.removeAllViews()
            self.lib_detail_header_host.addView(row, self.LP(-1, -2))
            self.lib_detail_header_host.setVisibility(0)
            if self.tab == "library":
                self.main_header.setVisibility(8)
        except Exception:
            self.lib_box.addView(row, self.LP(-1, -2))

    def _sync_pct_set(self, pct):
        self._sync_pct_last = int(pct)
        tv = self.__dict__.get("_sync_pct_tv")
        if tv is not None:
            with tolerated():
                tv.setText("%d%%" % int(pct))

    def _lib_sync_btn(self, pid, action=None):
        p = self.p
        GD = _cls("android.graphics.drawable.GradientDrawable")
        root = jclass("android.widget.FrameLayout")(self.act)
        bg = GD()
        bg.setShape(1)
        bg.setColor(_mix(self.c_bg, self.c_sub, 0.13))
        root.setBackground(bg)
        root.setContentDescription("Sync")
        btn = (root, root, None, self)
        if action is not None:
            tap_fn, busy_fn = action
        elif pid == "profile":
            def busy_fn():
                return bool(p.__dict__.get("_pp_btn_busy") or p._pp_busy or p._pp_pull_busy)
            def tap_fn():
                p._pp_log("manual sync tapped")
                p._pp_loader_show()
                def done():
                    if not p._pp_busy and not p.__dict__.get("_pp_timer"):
                        p._pp_loader_hide()
                p._pp_pull(True, done, 20.0, True)
            p._pp_btn = btn
        else:
            def busy_fn():
                return bool(p.__dict__.get("_dl_busy") or p.__dict__.get("_dl_deep_busy"))
            def tap_fn():
                def done(n):
                    p._dl_deeped = True
                    p._bulletin(strings("couldnt_read_telegrams_storage_index") if n < 0 else
                                strings("added_n_downloaded_tracks", n) if n else
                                strings("no_new_downloaded_tracks_found"), error=n < 0)
                    if self.lib_state == ("pl", pid):
                        self._lib_render()
                p._dl_scan(lambda: p._dl_deep(done))
        def live():
            with tolerated():
                return bool(busy_fn())
            return False
        state = {"busy": live()}
        p._pp_btn_fill(btn, state["busy"], None)
        def tap():
            if live():
                return
            self._sync_pct_last = None
            state["busy"] = True
            with tolerated():
                p._pp_btn_fill(btn, True)
            tap_fn()
        root.setOnClickListener(self.Click(lambda v: tap()))
        def tick():
            with tolerated():
                if not bool(root.isAttachedToWindow()):
                    return
                now = live()
                if now != state["busy"]:
                    state["busy"] = now
                    if not now:
                        self._sync_pct_last = None
                    p._pp_btn_fill(btn, now, None)
                self.handler.postDelayed(self.Run(tick), 600)
        self.handler.postDelayed(self.Run(tick), 600)
        return root

    def _make_fab(self, host, label, names, cb, primary):
        LL = jclass("android.widget.LinearLayout")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        size = 56 if primary else 44
        fab = LL(self.act)
        fab.setGravity(17)
        shape = GD()
        shape.setShape(1)
        shape.setColor(self.c_accent if primary else _mix(self.c_bg, self.c_accent, 0.22))
        fab.setBackground(shape)
        tint = -1 if primary else self.c_accent
        icon = self._glyph_icon(names, tint, pad=0, size=26 if primary else 20, bold=True)
        fab.addView(icon, self.LP(self.dp(28 if primary else 22), self.dp(28 if primary else 22)))
        fab.setContentDescription(label)
        fab.setOnClickListener(self.Click(lambda v: cb()))
        lp = self.LP(self.dp(size), self.dp(size))
        lp.setMargins(0, 0, 0, self.dp(12 if not primary else 0))
        if not primary:
            lp.setMargins(self.dp(6), 0, self.dp(6), self.dp(12))
        host.addView(fab, lp)
        return fab

    def _add_play_shuffle_fabs(self, host, play_cb, shuffle_cb):
        def play_clicked():
            with tolerated():
                sh, rv = self.p._read_order()
                if sh or rv:
                    self.p._disable_shuffle()
            play_cb()
        self._make_fab(host, strings("shuffle"), ("player_new_shuffle", "player_shuffle", "msg_shuffle"),
       shuffle_cb, False)
        self._make_fab(host, strings("play"), ("ic_action_play", "msg_round_play_m", "ic_play"),
       play_clicked, True)

    def _lib_detail_actions_fab(self, play_cb, shuffle_cb):
        host = self.lib_fab_host
        host.removeAllViews()
        self._add_play_shuffle_fabs(host, play_cb, shuffle_cb)
        host.setVisibility(0)
        with tolerated():
            self.lib_root.setPadding(0, self.dp(2), 0, self.dp(150))

    def _lib_detail_actions(self, play_cb, shuffle_cb):
        return self._lib_detail_actions_fab(play_cb, shuffle_cb)

    def _lib_apply_filter_meta(self, shown):
        label = getattr(self, "lib_filter_label", None)
        if not label:
            return
        with tolerated():
            minutes = self._lib_message_minutes(shown) if len(shown) < 128 else 0
            meta = f"{label} · " + self._lib_tracks_meta(len(shown), minutes)
            self.lib_detail_base_meta = meta
            if getattr(self, "lib_detail_meta", None) is not None and not self.lib_sel_mode:
                self.lib_detail_meta.setText(meta)

    def _lib_tracks_meta(self, n, mins):
        span = ""
        if mins:
            span = (f" · {mins // 60} h" + ((" " + strings("n_min", mins % 60)) if mins % 60 else "")) if mins >= 60 \
          else (" · " + strings("n_min", mins))
        return strings("n_tracks", n) + span

    def _lib_message_minutes(self, messages):
        fast = getattr(messages, "minutes", None)
        if fast is not None:
            return fast
        with tolerated():
            rows = getattr(messages, "rows", None)
            if rows is not None and len(rows) == len(messages):
                total = sum(max(0, int(row.get("s", 0) or 0)) for row in rows)
                return max(1, int(round(total / 60.0))) if total else 0
        total = 0
        for message in messages or []:
            with tolerated():
                total += max(0, int(message.getDuration()))
        return max(1, int(round(total / 60.0))) if total else 0

    def _lib_store_counts(self, entry, msgs):
        with tolerated():
            n = len(msgs)
            m = self._lib_message_minutes(msgs)
            if entry.get("cn") != n or entry.get("cm") != m:
                entry["cn"], entry["cm"] = n, m
                self.p._lib_save()

    def _lib_store_counts_async(self, entry, msgs, key=None):
        try:
            n = int(len(msgs))
        except Exception:
            return
        if entry is None or n < 128:
            self._lib_store_counts(entry, msgs)
            return
        key = key if key is not None else ("entry", id(entry))
        jobs = self.__dict__.setdefault("_lib_count_jobs", {})
        lock = self.__dict__.setdefault("_lib_count_jobs_lock", threading.RLock())
        signature = (id(msgs), n)
        with lock:
            if jobs.get(key) == signature:
                return
            jobs[key] = signature
        with tolerated():
            entry["cn"] = n
        def work():
            try:
                minutes = self._lib_message_minutes(msgs)
            except Exception:
                minutes = int(entry.get("cm", 0) or 0)
            with lock:
                if jobs.get(key) != signature:
                    return
                with tolerated():
                    entry["cn"], entry["cm"] = n, int(minutes or 0)
                jobs.pop(key, None)
            with tolerated():
                self.p._lib_save()
            def finish_ui():
                with tolerated():
                    current_chat_key = (key[1] if isinstance(key, tuple) and len(key) > 1
                and key[0] == "chat" else None)
                    if self.tab == "library" and self.lib_state == ("chat", current_chat_key):
                        current_jobs = self.__dict__.get("_lib_count_jobs", {})
                        if key not in current_jobs and entry.get("cn") == n and entry.get("cm") == int(minutes or 0):
                            if self.lib_detail_meta is not None:
                                self.lib_detail_meta.setText(self._lib_tracks_meta(n, int(minutes or 0)))
            try:
                run_on_ui_thread(finish_ui)
            except Exception:
                finish_ui()
        threading.Thread(target=work, daemon=True, name="smq-library-counts").start()

    def _lib_cached_meta(self, entry):
        if entry is not None and entry.get("cn") is not None:
            return self._lib_tracks_meta(int(entry["cn"]), int(entry.get("cm", 0) or 0))
        return None

    _LIB_TTL = 300

    def _lib_add_row(self, row, first):
        lp = self.LP(-1, -2)
        lp.setMargins(0, 0 if first else self.dp(2), 0, 0)
        self.lib_box.addView(row, lp)

    def _lib_set_chat_avatar(self, view, dialog_id, account=0, size=None, ok=None, note=True, big=0):
        try:
            if big:
                self.__dict__.setdefault("_av_big", {})[id(view)] = int(big)
            Long = jclass("java.lang.Long")
            MC = find_class("org.telegram.messenger.MessagesController").getInstance(int(account))
            did = int(dialog_id)
            obj = MC.getChat(Long.valueOf(-did)) if did < 0 else MC.getUser(Long.valueOf(did))
            if obj is None:
                if note:
                    self._av_note(view, did, int(account), ok)
                return False
            Avatar = find_class("org.telegram.ui.Components.AvatarDrawable")
            drawable = Avatar()
            try:
                drawable.setInfo(int(account), obj)
            except Exception:
                drawable.setInfo(obj)
            with tolerated():
                view.getImageReceiver().setCurrentAccount(int(account))
            view.setForUserOrChat(obj, drawable)
            if big:
                with tolerated():
                    IL = find_class("org.telegram.messenger.ImageLocation")
                    loc = IL.getForUserOrChat(obj, int(IL.TYPE_BIG))
                    if loc is not None:
                        px = max(64, min(int(big), 640))
                        view.setImage(loc, f"{px}_{px}", drawable, obj)
            if note and self._av_empty(obj):
                self._av_note(view, did, int(account), ok)
            if size and did < 0 and bool(getattr(obj, "forum", False)):
                view.setRoundRadius(int(size * 0.3))
            return True
        except Exception:
            return False

    def _av_empty(self, obj):
        try:
            ph = getattr(obj, "photo", None)
            return ph is None or "Empty" in str(ph.getClass().getName())
        except Exception:
            return True

    def _av_note(self, view, did, acc, ok):
        with tolerated():
            if (acc, did) in self.__dict__.setdefault("_av_tried", set()):
                return
            self.__dict__.setdefault("_av_pend", []).append((view, did, acc, ok))
            if not self.__dict__.get("_av_sched"):
                self._av_sched = True
                self.handler.postDelayed(self.Run(self._av_flush), 700)

    def _av_flush(self):
        self._av_sched = False
        pend, self._av_pend = self._av_pend, []
        Long = jclass("java.lang.Long")
        CM = find_class("org.telegram.tgnet.ConnectionsManager")
        seen = set()
        for _v, did, acc, _o in pend:
            k = (acc, did)
            if k in self._av_tried or k in seen:
                continue
            seen.add(k)
            self._av_tried.add(k)
            with tolerated():
                MCt = find_class("org.telegram.messenger.MessagesController").getInstance(acc)
                guid = int(CM.generateClassGuid())
                if did < 0:
                    MCt.loadFullChat(-did, guid, True)
                else:
                    u = MCt.getUser(Long.valueOf(did))
                    if u is None:
                        u = find_class("org.telegram.messenger.MessagesStorage").getInstance(acc).getUserSync(did)
                    if u is not None:
                        MCt.loadFullUser(u, guid, True)
        self.__dict__.setdefault("_av_all", []).extend(pend)
        self._av_q = self.__dict__.get("_av_q", []) + [k for k in seen]
        if not self.__dict__.get("_av_busy"):
            self._av_busy = True
            self._av_next()
        for d in (2500, 6000):
            self.handler.postDelayed(self.Run(lambda: self._av_reapply(pend)), d)

    def _av_next(self):
        if not self._av_q:
            self._av_busy = False
            allp, self._av_all = self._av_all, []
            self._av_reapply(allp)
            self.handler.postDelayed(self.Run(lambda: self._av_reapply(allp)), 2000)
            return
        acc, did = self._av_q.pop(0)
        fr = None
        with tolerated():
            b = jclass("android.os.Bundle")()
            if did < 0:
                b.putLong("chat_id", -did)
            else:
                b.putLong("user_id", did)
            fr = find_class("org.telegram.ui.ChatActivity")(b)
            with tolerated():
                set_private_field(fr, "currentAccount", acc)
            fr.onFragmentCreate()
        def end():
            with tolerated():
                if fr is not None:
                    fr.onFragmentDestroy()
            self._av_next()
        self.handler.postDelayed(self.Run(end), 2500)

    def _av_reapply(self, pend):
        for view, did, acc, ok in pend:
            with tolerated():
                if self._lib_set_chat_avatar(view, did, acc, None, None, False,
             self.__dict__.get("_av_big", {}).get(id(view), 0)) and ok:
                    ok()

    def _lib_avatar_tile(self, dialog_id, account=0, size=None, big=False):
        FL = _cls("android.widget.FrameLayout")
        FLP = _cls("android.widget.FrameLayout$LayoutParams")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        size = int(size or self.dp(self.COVER_DP))
        tile = FL(self.act)
        squircle = self._lib_is_forum(dialog_id, account)
        radius = float(size) * (0.3 if squircle else 0.5)
        bg = GD()
        bg.setShape(0 if squircle else 1)
        bg.setColor(_mix(self.c_item, self.c_accent, 0.2))
        bg.setCornerRadius(radius)
        tile.setBackground(bg)
        glyph = self._glyph_icon(("msg_groups", "msg_discussion", "msg_channel"), self.c_accent, pad=max(6, int(size / max(self.density, 1.0) * 0.28)), size=18)
        tile.addView(glyph, FLP(-1, -1))
        with tolerated():
            avatar = find_class("org.telegram.ui.Components.BackupImageView")(self.act)
            avatar.setRoundRadius(int(radius))
            tile.addView(avatar, FLP(-1, -1))
            if self._lib_set_chat_avatar(avatar, dialog_id, account, size, lambda: glyph.setVisibility(8),
          True, int(size) if big else 0):
                glyph.setVisibility(8)
        return tile

    def _lib_chat_kind(self, c, account=0):
        if int(c.get("t", 0) or 0):
            return "Topic"
        with tolerated():
            did = int(c["d"])
            Long = jclass("java.lang.Long")
            MC = find_class("org.telegram.messenger.MessagesController").getInstance(int(account))
            if did < 0:
                chat = MC.getChat(Long.valueOf(-did))
                if chat is None:
                    return "Group"
                if bool(getattr(chat, "broadcast", False)):
                    return "Channel"
                if bool(getattr(chat, "forum", False)):
                    return "Forum"
                return "Group"
            with tolerated():
                me = int(find_class("org.telegram.messenger.UserConfig").getInstance(int(account)).getClientUserId())
                if me == did:
                    return "Saved Messages"
            user = MC.getUser(Long.valueOf(did))
            if user is not None and bool(getattr(user, "bot", False)):
                return "Bot"
        return "Private chat"

    def _lib_is_forum(self, dialog_id, account=0):
        try:
            did = int(dialog_id)
            if did >= 0:
                return False
            Long = jclass("java.lang.Long")
            MC = find_class("org.telegram.messenger.MessagesController").getInstance(int(account))
            chat = MC.getChat(Long.valueOf(-did))
            return chat is not None and bool(getattr(chat, "forum", False))
        except Exception:
            return False

    def _lib_title_type_icon(self, tv, icons, parent=None, start=False):
        with tolerated():
            rid = self._res(*icons)
            if not rid:
                return
            d = self.act.getResources().getDrawable(int(rid)).mutate()
            s = self.dp(16)
            d.setBounds(0, 0, s, s)
            d.setTint(self.c_accent if start else self.c_sub)
            tv.setCompoundDrawables(d if start else None, None, None if start else d, None)
            tv.setCompoundDrawablePadding(self.dp(6))
            if parent is not None:
                def cap():
                    with tolerated():
                        w = int(parent.getWidth()) - int(parent.getPaddingLeft()) - int(parent.getPaddingRight())
                        if w > 0:
                            tv.setMaxWidth(int(w * 0.9))
                parent.post(self.Run(cap))

    def _chip_row(self, rowkey, chips, sel_idx, on_pick, parent=None, row_width_dp=None,
    margins_dp=None, index=-1):
        HSV = _cls("android.widget.HorizontalScrollView")
        LL = _cls("android.widget.LinearLayout")
        FL = _cls("android.widget.FrameLayout")
        FLP = _cls("android.widget.FrameLayout$LayoutParams")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        sv = HSV(self.act)
        sv.setHorizontalScrollBarEnabled(False)
        sv.setOverScrollMode(2)
        box = GD()
        box.setColor(self.c_item)
        box.setCornerRadius(float(self.dp(19)))
        sv.setBackground(box)
        with tolerated():
            sv.setClipToOutline(True)
        content = FL(self.act)
        pill = jclass("android.view.View")(self.act)
        pg = GD()
        pg.setColor(self.c_sel)
        pg.setCornerRadius(float(self.dp(16)))
        pill.setBackground(pg)
        pill.setVisibility(4)
        plp = FLP(0, -1)
        plp.setMargins(0, self.dp(3), 0, self.dp(3))
        content.addView(pill, plp)
        inner = LL(self.act)
        inner.setOrientation(0)
        inner.setGravity(16)
        inner.setPadding(self.dp(3), self.dp(3), self.dp(3), self.dp(3))
        cells, labels = [], []
        for i, ch in enumerate(chips):
            cell = LL(self.act)
            cell.setOrientation(0)
            cell.setGravity(17)
            cell.setPadding(self.dp(ch.get("pad_l", 12)), 0, self.dp(14), 0)
            lead = ch.get("lead")
            if lead is not None and callable(lead) and not hasattr(lead, "getClass"):
                lead = lead(sv)
            if lead is not None:
                llp = self.LP(*ch.get("lead_size", (self.dp(18), self.dp(18))))
                llp.setMargins(0, 0, self.dp(ch.get("lead_gap", 6)), 0)
                cell.addView(lead, llp)
            tv = self._text(ch["title"], 13, self.c_accent if i == sel_idx else self.c_sub,
          bold=True, gravity=17, single=True)
            if ch.get("max_w"):
                with tolerated():
                    tv.setMaxWidth(self.dp(ch["max_w"]))
            cell.addView(tv, self.LP(-2, -2))
            cell.setOnClickListener(self.Click(lambda v, ii=i: pick(ii)))
            lp = self.LP(-2, -1)
            if i:
                lp.setMargins(self.dp(2), 0, 0, 0)
            inner.addView(cell, lp)
            cells.append(cell)
            labels.append(tv)
        content.addView(inner, FLP(-2, -1))
        sv.addView(content, FLP(-2, -1))
        pr = _PillRow(self, pill, cells, labels)
        memo = self.__dict__.setdefault("_chip_prev", {})
        def pick(i):
            if i == sel_idx:
                return
            if pr.x is not None:
                memo[rowkey] = (pr.x, pr.w, int(sv.getScrollX()))
            on_pick(i)
        row_lp = self.LP(-2 if row_width_dp == "wrap" else (self.dp(row_width_dp) if row_width_dp else -1),
       self.dp(38))
        m = margins_dp or (10, 2, 10, 8)
        row_lp.setMargins(self.dp(m[0]), self.dp(m[1]), self.dp(m[2]), self.dp(m[3]))
        (parent if parent is not None else self.lib_box).addView(sv, index, row_lp)
        prev = memo.pop(rowkey, None)
        def settle():
            with tolerated():
                tx = max(0, int(cells[sel_idx].getLeft()) - self.dp(40))
                if prev is not None:
                    sv.scrollTo(int(prev[2]), 0)
                    sv.smoothScrollTo(tx, 0)
                else:
                    sv.scrollTo(tx, 0)
        pr.set(sel_idx, prev=(prev[0], prev[1]) if prev else None, then=settle)
        return sv

    def _album_cover_view(self, m, size_dp=24, radius_dp=5, glyph_sp=11, row=None):
        FL = _cls("android.widget.FrameLayout")
        FLP = _cls("android.widget.FrameLayout$LayoutParams")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        cover = FL(self.act)
        cbg = GD()
        cbg.setColor(_mix(self.c_item, self.c_sub, 0.15))
        cbg.setCornerRadius(float(self.dp(radius_dp)))
        cover.setBackground(cbg)
        with tolerated():
            cover.setClipToOutline(True)
        glyph = self._glyph_icon(("files_music", "msg_filled_data_music", "msg_music", "msg_media"), self.c_sub, pad=max(2, int(glyph_sp * 0.3)), size=glyph_sp)
        cover.addView(glyph, FLP(-1, -1))
        art = find_class("org.telegram.ui.Components.BackupImageView")(self.act)
        art.setRoundRadius(self.dp(radius_dp))
        cover.addView(art, FLP(-1, -1))
        if row is not None:
            self.lib_covers.append({"art": art, "m": m, "scrim": None, "glyph": glyph,
          "row": row, "done": False})
        elif m is not None:
            with tolerated():
                hq = bool(self.p.get_setting("hq_thumbs", True))
                d = self.COVER_DP * 2 if hq else self.COVER_DP
                if self._load_cover(art, m, 0, f"{d}_{d}", hq):
                    glyph.setVisibility(8)
        return cover

    def _artist_entry(self, key, name=None):
        a = next((x for x in self._lib_artist_data().get("list", [])
       if str(x.get("k", "")).casefold() == str(key).casefold()), None)
        return a if a is not None else {"k": str(key).casefold(), "n": name or str(key)}

    def _artist_avatar(self, key, size, name=None, views=None):
        a = self._artist_entry(key, name)
        photo = self._lib_artist_photo(a, size, views)
        if a["k"] not in self.p.__dict__.get("_artist_bmp", {}):
            self._lib_artist_images([a])
        return photo

    def _lib_topic_obj(self, did, tid, acc):
        with tolerated():
            MC = find_class("org.telegram.messenger.MessagesController").getInstance(int(acc))
            tc = MC.getTopicsController()
            topic = tc.findTopic(-int(did), int(tid))
            if topic is not None:
                return topic
            lst = tc.getTopics(-int(did))
            if lst is not None:
                for i in range(int(lst.size())):
                    t = lst.get(i)
                    if int(t.id) == int(tid):
                        return t
        return None

    def _lib_topics_request(self, key, did, acc):
        done = self.__dict__.setdefault("lib_topics_requested", set())
        if int(did) in done:
            return
        done.add(int(did))
        try:
            MC = find_class("org.telegram.messenger.MessagesController").getInstance(int(acc))
            MC.getTopicsController().loadTopics(-int(did))
        except Exception:
            return
        self.handler.postDelayed(self.Run(
       lambda: self._lib_render() if self.lib_state == ("chat", tuple(key)) else None), 1500)

    def _lib_topic_icon(self, did, tid, acc):
        FL = _cls("android.widget.FrameLayout")
        FLP = _cls("android.widget.FrameLayout$LayoutParams")
        try:
            FU = find_class("org.telegram.ui.Components.Forum.ForumUtilities")
            BIV = find_class("org.telegram.ui.Components.BackupImageView")
            if FU is None or BIV is None:
                return None
        except Exception:
            return None
        topic = self._lib_topic_obj(did, tid, acc)
        biv = BIV(self.act)
        tries = []
        if int(tid) == 1:
            tries.append(lambda: biv.setImageDrawable(
          FU.createGeneralTopicDrawable(self.act, 1.0, self.c_sub, False)))
        if topic is not None:
            tries += [
          lambda: FU.setTopicIcon(biv, topic, False, True, None),
          lambda: FU.setTopicIcon(biv, topic, False, False, None),
          lambda: FU.setTopicIcon(biv, topic, False, None),
          lambda: FU.setTopicIcon(biv, topic, False),
          lambda: FU.setTopicIcon(biv, topic),
          lambda: biv.setImageDrawable(FU.createTopicDrawable(topic, False)),
          lambda: biv.setImageDrawable(
          FU.createTopicDrawable(str(topic.title), int(topic.icon_color), False)),
          ]
        for attempt in tries:
            with tolerated():
                attempt()
                box = FL(self.act)
                box.addView(biv, FLP(-1, -1))
                return box
        return None

    def _lib_topic_tabs(self, key, msgs, acc):
        p = self.p
        key = tuple(key)
        did = int(key[0])
        n = len(msgs)
        groups_cache = self.__dict__.setdefault("_lib_topic_groups", {})
        pending = self.__dict__.setdefault("_lib_topic_groups_pending", {})
        cached = groups_cache.get(key)
        signature = (id(msgs), n)
        groups = cached[2] if cached is not None and cached[:2] == signature else None
        def group_indices():
            out = {}
            for i in range(n):
                try:
                    m = msgs[i]
                    if m is None:
                        continue
                    tid = int(p._get_message_topic_id(m, True) or 1) or 1
                    out.setdefault(tid, []).append(i)
                except Exception:
                    continue
            return out
        if groups is None and n >= 128:
            if pending.get(key) != signature:
                pending[key] = signature
                status_key = ("topic_group", key, id(msgs))
                p._activity_status(status_key, strings("organizing_forum_tracks"))
                def work():
                    try:
                        built = group_indices()
                    except Exception:
                        built = {}
                    def finish():
                        try:
                            current = p._chat_track_cache.get(key)
                            if current is msgs and self.lib_streams.get(key) is None:
                                groups_cache[key] = (id(msgs), n, built)
                                if self.tab == "library" and self.lib_state == ("chat", key):
                                    self._lib_render()
                        finally:
                            if pending.get(key) == signature:
                                pending.pop(key, None)
                            p._activity_status(status_key, None)
                    try:
                        run_on_ui_thread(finish)
                    except Exception:
                        finish()
                threading.Thread(target=work, daemon=True,
             name="smq-forum-topic-groups").start()
            return msgs
        if groups is None:
            groups = group_indices()
            groups_cache[key] = (id(msgs), n, groups)
        if not groups:
            return msgs
        rank = {}
        with tolerated():
            MC = find_class("org.telegram.messenger.MessagesController").getInstance(int(acc))
            lst = MC.getTopicsController().getTopics(-did)
            if lst is not None:
                for i in range(int(lst.size())):
                    rank[int(lst.get(i).id)] = i
        order = [0] + sorted(groups, key=lambda t: (t not in rank, rank.get(t, 0), t != 1, t))
        if any(self._lib_topic_obj(did, t, acc) is None for t in order[1:]):
            self._lib_topics_request(key, did, acc)
        sel_map = self.__dict__.setdefault("lib_topic_sel", {})
        sel = sel_map.get(tuple(key), 0)
        if sel != 0 and sel not in groups:
            sel = 0
            sel_map[tuple(key)] = sel
        def pick(i):
            sel_map[tuple(key)] = order[i]
            self._lib_render()
        chips = [{"title": strings("all") if tid == 0 else p._topic_label(did, tid, acc),
       "lead": (self._lib_topic_icon(did, tid, acc) if tid else None)}
       for tid in order]
        self._chip_row(("topic",) + tuple(key), chips, order.index(sel), pick)
        if sel != 0:
            self.lib_filter_label = p._topic_label(did, sel, acc)
        return msgs if sel == 0 else _IndexedTrackView(msgs, groups[sel])

    def _lib_chat_account(self, chat, messages=None):
        for message in messages or []:
            with tolerated():
                return int(message.currentAccount)
        try:
            return int(chat.get("a", 0))
        except Exception:
            return 0

    def _lib_reorder_shift(self, group, item_id, row, state, apply):
        entries = self.lib_reorder_rows.get(group, [])
        rows = [r for r, _ in entries]
        ids = [i for _, i in entries]
        if item_id not in ids:
            return None
        src = ids.index(item_id)
        h = int(row.getHeight())
        step = float(h + self.dp(2))
        center = float(row.getTop()) + h / 2.0 + float(row.getTranslationY())
        target = sum(1 for j, r in enumerate(rows)
       if j != src and float(r.getTop()) + int(r.getHeight()) / 2.0 < center)
        if not apply:
            return target
        applied = state.setdefault("ty", {})
        for j, r in enumerate(rows):
            if j == src:
                continue
            ty = 0.0
            if src < target and src < j <= target:
                ty = -step
            elif target < src and target <= j < src:
                ty = step
            if applied.get(j) != ty:
                applied[j] = ty
                try:
                    r.animate().translationY(float(ty)).setDuration(130).start()
                except Exception:
                    r.setTranslationY(float(ty))
        return target

    def _lib_reorder_touch(self, group, item_id, row, state, event, grid=False):
        action = int(event.getActionMasked())
        if action == 0:
            state["start_y"] = float(event.getRawY())
            state["start_x"] = float(event.getRawX())
            with tolerated():
                row.getParent().requestDisallowInterceptTouchEvent(True)
                row.performHapticFeedback(0)
                row.setTranslationZ(float(self.dp(6)))
            return True
        if state.get("start_y") is None:
            return False
        if action == 2:
            raw_x = float(event.getRawX())
            raw_y = float(event.getRawY())
            if grid:
                row.setTranslationX(raw_x - state["start_x"])
            row.setTranslationY(raw_y - state["start_y"])
            if not grid:
                self._lib_reorder_shift(group, item_id, row, state, True)
            return True
        if action in (1, 3):
            raw_x = float(event.getRawX())
            raw_y = float(event.getRawY())
            list_target = None
            if not grid:
                try:
                    list_target = self._lib_reorder_shift(group, item_id, row, state, False)
                except Exception:
                    list_target = None
                for other_row, _oid in self.lib_reorder_rows.get(group, []):
                    with tolerated():
                        other_row.animate().cancel()
                        other_row.setTranslationY(0.0)
                state["ty"] = {}
            with tolerated():
                row.setTranslationX(0.0)
                row.setTranslationY(0.0)
                row.setTranslationZ(0.0)
            state["start_y"] = None
            state["start_x"] = None
            if action == 3:
                return True
            entries = [(rr, rid) for rr, rid in self.lib_reorder_rows.get(group, [])
          if rid != item_id]
            if not entries:
                return True
            positions = []
            for other_row, other_id in entries:
                loc = jarray(jint)(2)
                other_row.getLocationOnScreen(loc)
                x0, y0 = int(loc[0]), int(loc[1])
                width, height = int(other_row.getWidth()), int(other_row.getHeight())
                positions.append((other_row, other_id, x0 + width / 2.0,
             y0 + height / 2.0, max(1, height)))
            if grid:
                def before(entry):
                    _row, _id, cx, cy, height = entry
                    row_band = max(float(self.dp(20)), height * 0.42)
                    if cy < raw_y - row_band:
                        return True
                    if cy > raw_y + row_band:
                        return False
                    return cx < raw_x
                target = sum(1 for entry in positions if before(entry))
            elif list_target is not None:
                target = list_target
            else:
                target = sum(1 for entry in positions if raw_y > entry[3])
            if group == "pinned_artists":
                shown_keys = [rid for _rr, rid in self.lib_reorder_rows.get(group, []) if rid != item_id]
                shown_keys.insert(max(0, min(len(shown_keys), target)), item_id)
                pinned = self._lib_pinned_artists()
                self.p.set_setting("pinned_artists", json.dumps(shown_keys + [k for k in pinned if k not in shown_keys]))
                self._lib_render()
                return True
            data = self.p._lib_data().get(group, [])
            source = next((i for i, item in enumerate(data)
          if (item.get("id") if group == "playlists" else
          int(item.get("d", item.get("id", 0)) or 0) if group == "friends" else
          (int(item.get("d", 0)), int(item.get("t", 0)))) == item_id), None)
            if source is None:
                return True
            item = data.pop(source)
            target = max(0, min(len(data), target))
            data.insert(target, item)
            self.p._lib_save()
            self._lib_render()
            return True
        return True

    def _lib_cvsig(self):
        return (bool(self.p.get_setting("hq_thumbs", True)), self.c_item, self.c_sub, self.c_accent)

    def _lib_cv_cache(self, key, row, build):
        c = self.__dict__.setdefault("_lib_cvc", {})
        used = self.__dict__.setdefault("_lib_cvu", set())
        if key is None or key in used:
            return build()
        used.add(key)
        e = c.get(key)
        if e is not None:
            v = e[0]
            with tolerated():
                par = v.getParent()
                if par is not None:
                    par.removeView(v)
                for x in e[1]:
                    x["row"] = row
                    self.lib_covers.append(x)
                return v
        n = len(self.lib_covers)
        v = build()
        c[key] = (v, self.lib_covers[n:])
        return v

    def _tile_icon_names(self, glyph):
        if isinstance(glyph, (tuple, list)):
            return tuple(glyph)
        return ("msg_media", "msg_music")

    def _lib_tile(self, row, cd, glyph, cover_ms, action_icon):
        cv = [m for m in (cover_ms or []) if m is not None]
        key = None
        if cv and action_icon is None:
            ks = tuple(self.p._msg_key(m) for m in cv)
            if None not in ks:
                key = ("t", ks, cd, glyph, self._lib_cvsig())
        return self._lib_cv_cache(key, row, lambda: self._lib_tile_b(row, cd, glyph, cover_ms, action_icon))

    def _lib_tile_b(self, row, cd, glyph, cover_ms, action_icon):
        LL = jclass("android.widget.LinearLayout")
        FL = _cls("android.widget.FrameLayout")
        FLP = _cls("android.widget.FrameLayout$LayoutParams")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        covers = [m for m in (cover_ms or []) if m is not None]
        mosaic = action_icon is None and len(covers) >= 4
        tile = FL(self.act)
        bg = GD()
        bg.setColor(self.c_item if mosaic else _mix(self.c_item, self.c_accent, 0.2))
        bg.setCornerRadius(float(self.dp(12)))
        tile.setBackground(bg)
        with tolerated():
            tile.setClipToOutline(True)
        BIV = find_class("org.telegram.ui.Components.BackupImageView")
        if action_icon is not None:
            tile.addView(self._glyph_icon(action_icon, self.c_accent,
                         pad=max(11, int(cd / max(self.density, 1.0) * 0.26)), size=22, bold=True), FLP(-1, -1))
            return tile
        if mosaic:
            gap = max(1, self.dp(1) // 2)
            grid = LL(self.act)
            grid.setOrientation(1)
            for r in range(2):
                line = LL(self.act)
                line.setOrientation(0)
                for c in range(2):
                    cell = FL(self.act)
                    cell.setBackgroundColor(_mix(self.c_item, self.c_sub, 0.10))
                    with tolerated():
                        art = BIV(self.act)
                        cell.addView(art, FLP(-1, -1))
                        self.lib_covers.append({"art": art, "m": covers[r * 2 + c], "scrim": None,
                   "glyph": None, "row": row, "done": False})
                    lp = self.LP(0, -1, 1.0)
                    lp.setMargins(gap, gap, gap, gap)
                    line.addView(cell, lp)
                grid.addView(line, self.LP(-1, 0, 1.0))
            tile.addView(grid, FLP(-1, -1))
            return tile
        gl = self._glyph_icon(self._tile_icon_names(glyph), self.c_accent, pad=int(max(6, int(cd / max(self.density, 1.0)) * 0.28)), size=18)
        tile.addView(gl, FLP(-1, -1))
        if covers:
            with tolerated():
                art = BIV(self.act)
                art.setRoundRadius(self.dp(12))
                tile.addView(art, FLP(-1, -1))
                self.lib_covers.append({"art": art, "m": covers[0], "scrim": None, "glyph": gl,
             "row": row, "done": False})
        return tile

    def _lib_row(self, title, sub, cb, first, last, glyph=("files_music", "msg_filled_data_music", "msg_music", "msg_media"), cover_m=None,
    avatar_did=None, avatar_acc=0, reorder_type=None, reorder_id=None,
    cover_ms=None, action_icon=None, description=None, tile_fn=None,
    pin=None, top_margin_dp=0, type_icons=None, long_cb=None, icon_start=False):
        LL = jclass("android.widget.LinearLayout")
        action = action_icon is not None
        row = LL(self.act)
        row.setOrientation(0)
        row.setGravity(16)
        row.setMinimumHeight(self.H)
        row.setPadding(self.dp(self.ROW_PAD_START), 0,
       self.dp(4 if (reorder_type or pin) else 14), 0)
        row.setBackground(self._group_bg(self.c_item, first, last))
        cd = self.dp(self.COVER_DP)
        if tile_fn is not None:
            tile = tile_fn(cd)
        elif avatar_did is not None:
            tile = self._lib_avatar_tile(avatar_did, avatar_acc, cd)
        else:
            tile = self._lib_tile(row, cd, glyph, cover_ms or ([cover_m] if cover_m is not None else None),
          action_icon)
        row.addView(tile, self.LP(cd, cd))
        info = LL(self.act)
        info.setOrientation(1)
        info.setGravity(16)
        info.setPadding(self.dp(12), 0, self.dp(4), 0)
        title_tv = self._text(title, 16, self.c_accent if action else self.c_text, single=True)
        if type_icons:
            self._lib_title_type_icon(title_tv, type_icons, info, icon_start)
        info.addView(title_tv, self.LP(-2 if type_icons else -1, -2))
        if sub:
            info.addView(self._text(sub, 14, self.c_sub if action else self.c_accent, single=True),
          self.LP(-1, -2))
        row.addView(info, self.LP(0, -1, 1.0))
        if reorder_type and reorder_id is not None:
            handle = self._drag_handle(strings("drag_to_reorder"))
            row.addView(handle, self.LP(self.dp(40), -1))
            self.lib_reorder_rows.setdefault(reorder_type, []).append((row, reorder_id))
            state = {"start_y": None, "start_x": None}
            handle.setOnTouchListener(self._hold_drag(
          lambda v, e, group=reorder_type, item_id=reorder_id, rr=row, st=state:
          self._lib_reorder_touch(group, item_id, rr, st, e, grid=False)))
        if pin:
            pinned, pin_cb = pin
            pin_iv = self._glyph_icon(_PIN_ICONS, self.c_accent if pinned else self.c_sub,
          pad=10, size=18)
            pin_iv.setAlpha(1.0 if pinned else 0.6)
            pin_iv.setContentDescription(strings("unpin_artist") if pinned else strings("pin_artist"))
            pin_iv.setOnClickListener(self.Click(lambda v: pin_cb()))
            row.addView(pin_iv, self.LP(self.dp(40), -1))
        row.setContentDescription(description or str(title))
        def select_row(v):
            if self.lib_state == ("home", None) and self.lib_search_active and self.lib_search_query.strip():
                self._toggle_library_search()
            cb()
        row.setOnClickListener(self.Click(select_row))
        if long_cb is not None:
            self._lib_hold_bind(row, long_cb)
        if top_margin_dp:
            row_lp = self.LP(-1, -2)
            row_lp.setMargins(0, self.dp(top_margin_dp), 0, 0)
            self.lib_box.addView(row, row_lp)
        else:
            self._lib_add_row(row, first)

    def _lib_prefetch_covers(self, playlists):
        p = self.p
        if getattr(self, "lib_cover_busy", False):
            return
        tried = p.__dict__.setdefault("_lib_cover_tried", set())
        wanted = []
        for pl in playlists:
            tracks = (pl.get("tracks") or [])[:12]
            if not tracks or self._lib_playlist_cover_messages(tracks):
                continue
            for tr in tracks[:8]:
                k = (int(tr["i"]), int(tr["d"]))
                if k in p._msg_cache or k in p._msg_missing or k in tried:
                    continue
                wanted.append(tr)
        if not wanted:
            return
        tried.update((int(tr["i"]), int(tr["d"])) for tr in wanted)
        self.lib_cover_busy = True
        def finish():
            self.lib_cover_busy = False
            with tolerated():
                if self.lib_state == ("home", None) and self.dialog.isShowing():
                    self._lib_render()
        p._resolver.request_tracks(wanted, silent=True, on_done=finish)

    def _lib_playlist_entry_row(self, pl, first, last, _unused=None):
        tracks = pl.get("tracks", [])
        self._lib_row(_pln(pl["name"]), self._lib_tracks_meta(len(tracks), self.p._lib_minutes(tracks)),
       (lambda pid=pl["id"]: self._lib_go("pl", pid)),
       first, last,
       cover_ms=None if self._lib_pl_icon(pl) else self._lib_playlist_cover_messages(tracks),
       tile_fn=(lambda cd, ic=self._lib_pl_icon(pl): self._lib_tile_b(None, cd, None, None, ic)) if self._lib_pl_icon(pl) else None,
       reorder_type="playlists", reorder_id=pl["id"],
       long_cb=lambda pid=pl["id"]: self._lib_playlist_menu(pid),
       description=(strings("playlist") + ": ") + _pln(pl["name"]))

    def _lib_song_lead(self, cd, with_art=True):
        FL = _cls("android.widget.FrameLayout")
        FLP = _cls("android.widget.FrameLayout$LayoutParams")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        lead = FL(self.act)
        circle = GD()
        circle.setShape(1)
        circle.setColor(self.c_accent)
        lead.setBackground(circle)
        art = None
        if with_art:
            with tolerated():
                art = find_class("org.telegram.ui.Components.BackupImageView")(self.act)
                art.setRoundRadius(cd // 2)
                lead.addView(art, FLP(-1, -1))
        return lead, art

    def _lib_pl_icon(self, pl):
        if pl.get("id") == "profile":
            from ..helpers import _profile_music_icons
            return ("filled_track_add",) + tuple(_profile_music_icons())
        if pl.get("id") in _LIB_DYN:
            return _LIB_DYN[pl["id"]]
        return ("media_like_active",) if str(pl.get("name", "")).strip().lower() == "liked songs" else None

    def _lib_cover_now(self, art, m, glyph=None, size_dp=None):
        hq = bool(self.p.get_setting("hq_thumbs", True))
        d = int(size_dp or self.COVER_DP) * (2 if hq else 1)
        c = {"art": art, "m": m, "scrim": None, "glyph": glyph, "row": None, "done": True}
        ok = False
        with tolerated():
            ok = bool(self._load_cover(art, m, 0, f"{d}_{d}", hq))
        if not ok:
            self.lib_covers.append(c)
            with tolerated():
                ok = bool(self._lib_embedded(c))
        if ok and glyph is not None:
            glyph.setVisibility(8)
        return ok

    def _track_row_base(self, m, first, last, title, author, background=True,
    author_color=None, always_author=False):
        LL = _cls("android.widget.LinearLayout")
        FLP = _cls("android.widget.FrameLayout$LayoutParams")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        View = _cls("android.view.View")
        LP = self.LP
        cd = self.dp(self.COVER_DP)
        row = LL(self.act)
        row.setOrientation(0)
        row.setGravity(16)
        row.setMinimumHeight(self.H)
        row.setPadding(self.dp(self.ROW_PAD_START), 0, self.dp(4), 0)
        if background:
            row.setBackground(self._group_bg(self.c_item, first, last))
        lead, art = self._lib_song_lead(cd, m is not None)
        scrim = None
        if m is not None:
            scrim = View(self.act)
            scrim_bg = GD()
            scrim_bg.setShape(1)
            scrim_bg.setColor(_argb(90, 0, 0, 0))
            scrim.setBackground(scrim_bg)
            scrim.setVisibility(8)
            lead.addView(scrim, FLP(-1, -1))
        row.addView(lead, LP(cd, cd))
        info = LL(self.act)
        info.setOrientation(1)
        info.setGravity(16)
        info.setPadding(self.dp(12), 0, self.dp(4), 0)
        title_view = self._text(title, 16, self.c_text, single=True)
        info.addView(title_view, LP(-1, -2))
        author_view = self._text(author or "", 14,
       self.c_accent if author_color is None else author_color,
       single=True)
        if author or always_author:
            info.addView(author_view, LP(-1, -2))
        row.addView(info, LP(0, -1, 1.0))
        liked_iv = None
        if m is not None:
            liked_iv = self._liked_badge(m)
            row.addView(liked_iv, LP(self.dp(22), self.dp(22)))
        return {
       "liked": liked_iv,
       "row": row,
       "lead": lead,
       "art": art,
       "scrim": scrim,
       "info": info,
       "title": title_view,
       "author": author_view,
       "FLP": FLP,
       }

    def _track_play_icon(self, lead, m, fallback=False):
        IV = _cls("android.widget.ImageView")
        FLP = _cls("android.widget.FrameLayout$LayoutParams")
        play_iv = IV(self.act)
        play_pp = None
        try:
            drawable = find_class("org.telegram.ui.Components.PlayPauseDrawable")(22)
            drawable.setColor(-1)
            play_iv.setImageDrawable(drawable)
            with tolerated():
                drawable.setParent(play_iv)
            play_pp = drawable
            now = self._key(m) == self.playing_key
            drawable.setPause(bool(now and not getattr(self, "_paused", True)), False)
        except Exception:
            if fallback:
                with tolerated():
                    dr_play = _cls("android.R$drawable")
                    fallback_play = int(getattr(self, "_ic_play",
                getattr(dr_play, "ic_media_play", 0)) or 0)
                    if fallback_play:
                        play_iv.setImageResource(fallback_play)
                    play_iv.setColorFilter(-1)
        pp = self.dp(11)
        play_iv.setPadding(pp, pp, pp, pp)
        lead.addView(play_iv, FLP(-1, -1))
        return play_iv, play_pp

    def _track_overlays(self, lead, pad=10, size=22):
        FL = _cls("android.widget.FrameLayout")
        FLP = _cls("android.widget.FrameLayout$LayoutParams")
        IV = _cls("android.widget.ImageView")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        chk = FL(self.act)
        cg = GD()
        cg.setShape(1)
        cg.setColor(self.c_accent)
        chk.setBackground(cg)
        chk.addView(self._glyph_icon(("msg_check_s", "checkbig"), -1,
       pad=pad, size=size, bold=True), FLP(-1, -1))
        chk.setVisibility(8)
        lead.addView(chk, FLP(-1, -1))
        badge = FL(self.act)
        badge_bg = GD()
        badge_bg.setShape(1)
        badge_bg.setColor(self.c_accent)
        badge_bg.setStroke(self.dp(2), self.c_bg)
        badge.setBackground(badge_bg)
        arrow = IV(self.act)
        arrow.setImageResource(int(self._res("media_download", "msg_download")))
        arrow.setColorFilter(-1)
        arrow.setPadding(self.dp(3), self.dp(3), self.dp(3), self.dp(3))
        badge.addView(arrow, FLP(-1, -1))
        spin = _cls("android.widget.ProgressBar")(self.act)
        with tolerated():
            spin.setIndeterminateTintList(_cls("android.content.res.ColorStateList").valueOf(-1))
        spin.setPadding(self.dp(3), self.dp(3), self.dp(3), self.dp(3))
        spin.setVisibility(8)
        badge.addView(spin, FLP(-1, -1))
        badge.setVisibility(8)
        lead.addView(badge, FLP(self.dp(18), self.dp(18), 85))
        return {"check": chk, "badge": badge, "arrow": arrow, "spin": spin}
