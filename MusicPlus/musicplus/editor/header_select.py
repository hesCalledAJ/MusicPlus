import json
import re
import threading
from ..compat import find_class, jarray, jclass, run_on_ui_thread
from elyx import strings
from ..helpers import _LIB_DYN, _argb, _http_stream, _http_text, _profile_music_icons, _rd_index
from ..android import _cls, _layoutchg_proxy, _mix, _seek_proxy
from ..safe import tolerated


class _QueueEditorHeaderSelect:
    def _activity_refresh(self):
        with tolerated():
            self.activity_status_box.setVisibility(8)

    def _update_title(self):
        self._update_offline_icon()
        with tolerated():
            self.main_header.setVisibility(8 if self.tab == "library" and self.lib_state[0] != "home" else 0)
        self._lib_progress_refresh()
        if self.tab != "queue":
            self.title_overline.setVisibility(8)
            self.title.setText(strings(dict(self.TABS).get(self.tab, "queue")))
            self._update_hdr_decor(False)
        elif self.sel_mode:
            self.title_overline.setVisibility(8)
            self.title.setText(strings("n_selected", len(self.sel)))
            self._update_hdr_decor(False)
        else:
            count = len([m for m in self.items if m is not None])
            build = getattr(self.p, "_queue_build_state", None)
            if build is not None and build.get("token") == getattr(self.p, "_queue_build_token", None):
                with tolerated():
                    count = max(count, int(build.get("total", count)))
            with tolerated():
                count = max(count, int(getattr(self.p, "_queue_hydration_expected", 0) or 0),
             int(getattr(self.p, "_queue_expected_count", 0) or 0))
            open_total = bool(getattr(self.p, "_queue_hydration_open", False)) and not self.ghost
            if not count:
                self.title_overline.setVisibility(8)
                self.title.setText(strings("queue"))
                self._update_hdr_decor(False)
                return
            self.title_overline.setVisibility(0)
            self.title_overline.setText(strings("n_n_n_tracks_from", "", count, '+' if open_total else ''))
            queue_name = self._queue_detail_name()
            self.title.setText(queue_name)
            self._update_hdr_decor(True)

    _CHAT_KIND_KEYS = {"Topic": "kind_topic", "Group": "kind_group", "Channel": "kind_channel", "Forum": "kind_forum",
    "Saved Messages": "saved_messages", "Bot": "kind_bot", "Private chat": "kind_private_chat"}

    _TYPE_ICONS = {
    "Channel": ("filter_channels", "msg_channel", "menu_channel"),
    "Group": ("filter_group", "msg_groups", "menu_groups"),
    "Forum": ("filter_group", "msg_discussion", "msg_groups"),
    "Topic": ("filter_group", "msg_discussion", "msg_groups"),
    "Bot": ("filter_bots", "msg_bot", "menu_bot"),
    "Saved Messages": ("filter_private", "msg_saved", "menu_saved"),
    "Private chat": ("filter_private", "msg_contacts", "menu_contacts"),
    }

    def _queue_detail_name(self):
        p = self.p
        name, sc = p._origin_display(), p._queue_scope_key
        ck = p._origin_chat_key(sc)
        album = isinstance(sc, (tuple, list)) and sc[:1] == ("artist",) and len(sc) > 2 and sc[2] is not None
        if ":" in name and (album or (ck and ck[1] > 0)):
            return name.split(":", 1)[1].strip() or name
        return name

    def _hdr_source(self):
        p = self.p
        with tolerated():
            p._profile_scope_sync()
        scope = getattr(p, "_queue_scope_key", None)
        if not isinstance(scope, (tuple, list)) or not scope:
            return None
        head = scope[0]
        prof = ("filled_track_add",) + tuple(_profile_music_icons())
        try:
            if head == "playlist" and len(scope) >= 2 and scope[1] == "profile":
                acc = int(p._chat_account(None, None) or 0)
                return int(p._me(acc)), acc, prof
            if head in ("playlist", "library") and len(scope) >= 2:
                nm = ""
                if head == "playlist":
                    pl = p._lib_pl(scope[1])
                    nm = str(pl.get("name", "")) if pl else ""
                else:
                    nm = str(scope[1])
                if nm.strip().lower() == "liked songs":
                    return None, 0, ("filter_love", "msg_fave", "msg_like")
                if nm.strip().lower() == "downloaded songs" or (head == "playlist" and scope[1] == "downloaded"):
                    return None, 0, _LIB_DYN["downloaded"]
            if head in ("profile_music", "friend") and len(scope) >= 2:
                uid = int(scope[1])
                acc = 0
                fr = self._lib_friend(uid)
                if fr is not None:
                    acc = int(fr.get("a", 0) or 0)
                return uid, acc, prof
            if head == "artist" and len(scope) >= 2:
                if len(scope) >= 3 and scope[2] is not None:
                    ck = getattr(p, "_queue_cover_key", None)
                    if ck is None:
                        first = next((m for m in self.items if m is not None), None)
                        ck = self._key(first) if first is not None else None
                    return ("album", str(scope[1]), ck), 0, ()
                return ("artist", str(scope[1])), 0, ()
            ck = p._origin_chat_key(scope)
            if not ck or not ck[0]:
                return None
            did, topic = ck[0], ck[1]
            acc = int(p._chat_account(None, None) or 0)
            kind = self._lib_chat_kind({"d": did, "t": topic}, acc)
            icons = self._TYPE_ICONS.get(kind, self._TYPE_ICONS["Group"])
            return (("topic", did, topic) if topic else did), acc, icons
        except Exception:
            return None

    def _update_hdr_decor(self, show):
        with tolerated():
            src = self._hdr_source() if show else None
            if src is None:
                self.hdr_avatar_box.setVisibility(8)
                self.hdr_type.setVisibility(8)
                self._hdr_key = None
                return
            did, acc, icons = src
            key = (did, acc, tuple(icons))
            if key == self._hdr_key:
                return
            self._hdr_key = key
            self.hdr_avatar_box.removeAllViews()
            sz = int(self.hdr_avatar_box.getLayoutParams().width)
            self.hdr_artist_views = {}
            if isinstance(did, tuple) and did and did[0] == "artist":
                self._hdr_artist_avatar(did[1])
            elif isinstance(did, tuple) and did and did[0] == "album":
                self._hdr_album_cover(did[2])
            elif isinstance(did, tuple) and did and did[0] == "topic":
                self._hdr_topic_icon(did[1], did[2], acc)
            else:
                av = find_class("org.telegram.ui.Components.BackupImageView")(self.act)
                av.setRoundRadius(sz // 2)
                if did is not None and self._lib_set_chat_avatar(av, did, acc):
                    self.hdr_avatar_box.addView(av, _cls("android.widget.FrameLayout$LayoutParams")(-1, -1))
                    self.hdr_avatar_box.setVisibility(0)
                else:
                    self.hdr_avatar_box.setVisibility(8)
            rid = self._res(*icons) if icons else 0
            if rid:
                self.hdr_type.setImageResource(int(rid))
                self.hdr_type.setColorFilter(self.c_sub)
                self.hdr_type.setVisibility(0)
            else:
                self.hdr_type.setVisibility(8)

    def _hdr_put(self, view):
        self.hdr_avatar_box.addView(view, _cls("android.widget.FrameLayout$LayoutParams")(-1, -1))
        self.hdr_avatar_box.setVisibility(0)

    def _hdr_artist_avatar(self, key):
        try:
            name = self.p._origin_title(self.p._queue_name, self.p._queue_scope_key).split(":", 1)[0].strip()
            photo = self._artist_avatar(key, self.dp(19), name, views=self.hdr_artist_views)
            with tolerated():
                photo.getChildAt(0).setTextSize(2, 9.0)
            self._hdr_put(photo)
        except Exception:
            self.hdr_avatar_box.setVisibility(8)
            self._hdr_key = None

    def _hdr_album_cover(self, cover_key):
        try:
            m = self.p._msg_cache.get(tuple(cover_key)) if cover_key else None
            if m is None:
                m = next((x for x in self.items if x is not None), None)
            sc = self.p._queue_scope_key
            self._hdr_put(self._album_lead(self._artist_entry(sc[1]), sc[2], m, None, 4, 9))
        except Exception:
            self.hdr_avatar_box.setVisibility(8)
            self._hdr_key = None

    def _hdr_topic_icon(self, did, tid, acc):
        icon = self._lib_topic_icon(did, tid, acc)
        if icon is not None:
            self._hdr_put(icon)
            return
        self._hdr_key = None
        av = find_class("org.telegram.ui.Components.BackupImageView")(self.act)
        av.setRoundRadius(int(self.hdr_avatar_box.getLayoutParams().width) // 2)
        if self._lib_set_chat_avatar(av, did, acc):
            self._hdr_put(av)
        else:
            self.hdr_avatar_box.setVisibility(8)

    def _open_queue_source(self):
        if self.tab != "queue" or self.sel_mode:
            return
        with tolerated():
            p = self.p
            scope = getattr(p, "_queue_scope_key", None)
            name = p._origin_title(p._queue_name, scope).strip()
            data = p._lib_data()
            def open_chat(did, topic):
                saved = next((c for c in data.get("chats", [])
             if int(c.get("d", 0)) == did and int(c.get("t", 0)) == topic), None)
                whole = None if saved or not topic else next(
             (c for c in data.get("chats", [])
             if int(c.get("d", 0)) == did and int(c.get("t", 0)) == 0), None)
                if saved:
                    self._set_tab("library")
                    self._lib_go("chat", (did, topic))
                elif whole:
                    self._set_tab("library")
                    self._lib_go("chat", (did, 0), select=topic)
                else:
                    self.dialog.dismiss()
                    self.handler.postDelayed(self.Run(lambda: p._open_chat_scope(did, topic)), 100)
            def open_playlist(pid):
                self._set_tab("library")
                self._lib_go("pl", pid)
            def open_artist(key):
                a = next((x for x in self._lib_artist_data().get("list", [])
             if str(x.get("k", "")).casefold() == str(key).casefold()), None)
                ak = a["k"] if a is not None else self._lib_ensure_artist(name.split(":", 1)[0] or str(key))
                if not ak:
                    return
                album = scope[2] if len(scope) >= 3 else None
                if getattr(self, "lib_search_active", False):
                    self._set_library_search(False, clear=True, rerender=False)
                self._set_tab("library")
                self._lib_go("artist", ak, select=album)
            ck = p._origin_chat_key(scope)
            if ck and ck[0]:
                open_chat(ck[0], ck[1])
                return
            head = scope[0] if isinstance(scope, (tuple, list)) and scope else None
            if head == "artist" and len(scope) >= 2:
                open_artist(scope[1])
                return
            if head == "playlist" and len(scope) >= 2:
                open_playlist(scope[1])
                return
            if head == "library" and len(scope) >= 2:
                pl = next((x for x in data.get("playlists", [])
             if x.get("id") == scope[1] or x.get("name") == name), None)
                if pl:
                    open_playlist(pl.get("id"))
                    return
                chat = next((c for c in data.get("chats", []) if c.get("n") == name), None)
                if chat:
                    open_chat(int(chat["d"]), int(chat["t"]))
                    return
            if name:
                pl = next((x for x in data.get("playlists", []) if x.get("name") == name), None)
                if pl:
                    open_playlist(pl.get("id"))
                    return
            mc = p._get_mc()
            cur = mc.getPlayingMessageObject() if mc is not None else None
            did = int(cur.getDialogId()) if cur is not None else 0
            if did:
                open_chat(did, 0)
            elif isinstance(scope, (tuple, list)) and scope and scope[0] == "library":
                self._set_tab("library")
                self._lib_go("home")

    def _apply_sel(self, R):
        on = self.sel_mode and self._key(R["m"]) in self.sel
        R["check"].setVisibility(0 if on else 8)
        R["row"].setBackground(self._group_bg(self.c_sel if on else self.c_item,
       R.get("first", False), R.get("last", False),
       inset=(0, 1, 0, 1)))
        R["row"].setPadding(self.dp(self.ROW_PAD_START), 0, self.dp(4), 0)
        vis = 4 if self.sel_mode else 0
        R["more"].setVisibility(vis)

    def _set_sel_mode(self, on):
        self.sel_mode = bool(on)
        if not on:
            self.sel = set()
        with tolerated():
            self._lib_sync_back_cb()
        for R in list(self.row_refs.values()):
            self._apply_sel(R)
        with tolerated():
            self._update_title()

    def _exit_sel(self):
        self._set_sel_mode(False)

    def _header_close(self):
        if self.sel_mode:
            self._exit_sel()
        else:
            self.dialog.dismiss()

    def _enter_sel(self, m):
        self.sel = {self._key(m)}
        self._set_sel_mode(True)

    def _toggle_sel(self, m):
        k = self._key(m)
        if k in self.sel:
            self.sel.discard(k)
        else:
            self.sel.add(k)
        if not self.sel:
            self._set_sel_mode(False)
            return
        for R in list(self.row_refs.values()):
            if self._key(R["m"]) == k:
                self._apply_sel(R)
        self._update_title()

    def _row_click(self, m):
        if self.sel_mode:
            self._toggle_sel(m)
        elif self._key(m) == self.playing_key:
            self._mini_toggle()
        else:
            self._play(m)

    def _row_long(self, m, v=None):
        with tolerated():
            if v is not None:
                v.performHapticFeedback(0)
        if self.ghost:
            return True
        if self.sel_mode:
            self._toggle_sel(m)
        else:
            self._enter_sel(m)
        return True

    def _sel_cancel(self):
        self.p._cancel_downloads(self._sel_items())

    def _sel_items(self):
        return [m for m in self.items if self._key(m) in self.sel]

    def _sel_all(self):
        keys = {self._key(m) for m in self.items}
        self.sel = set() if self.sel >= keys else keys
        if not self.sel:
            self._set_sel_mode(False)
            return
        for R in list(self.row_refs.values()):
            self._apply_sel(R)
        self._update_title()

    def _sel_remove(self):
        items = self._sel_items()
        mc = self.p._get_mc()
        pl = self.p._get_playlist(mc) if mc is not None else None
        if not items or pl is None:
            return
        removed = skipped = 0
        for m in items:
            if self._key(m) == self.playing_key:
                skipped += 1
                continue
            if self.p._playlist_remove_by_id(mc, pl, m.getId(), m.getDialogId()):
                removed += 1
        self.p._resync_current(mc, pl)
        msg = strings("removed_n_tracks", removed)
        if skipped:
            msg += strings("kept_the_playing_one")
        self.p._bulletin(msg, error=not removed)
        self._set_sel_mode(False)
        self._reload()

    def _sel_move(self, where):
        sel = [m for m in self._sel_items() if self._key(m) != self.playing_key]
        if not sel:
            self.p._bulletin(strings("nothing_to_move"), error=True)
            return
        skeys = {self._key(m) for m in sel}
        rest = [m for m in self.items if self._key(m) not in skeys]
        if where == "end":
            new = rest + sel
        else:
            pp = next((i for i, m in enumerate(rest) if self._key(m) == self.playing_key), -1)
            new = rest[:pp + 1] + sel + rest[pp + 1:]
        if self._commit(new):
            with tolerated():
                if self.p._read_order()[0]:
                    mc = self.p._get_mc()
                    pl = self.p._get_playlist(mc) if mc is not None else None
                    if pl is not None:
                        self.p._shuffle_place(mc, pl, sel, where == "next")
            self.p._bulletin((strings("n_tracks", len(sel)) + " ")
          + (strings("play_next").lower() if where == "next" else strings("moved_to_the_end")))
        self._set_sel_mode(False)
        self._reload()

    def _sel_forward(self):
        items = self._sel_items()
        if len(items) > 100:
            self.p._bulletin(strings("forward_up_to_100_tracks_at"), error=True)
            return
        if items:
            self._after_close(lambda: self.p._pick_forward(items))

    def _sel_download(self):
        items = self._sel_items()
        if len(items) > 100:
            self.p._bulletin(strings("download_up_to_100_tracks_at"), error=True)
            return
        if items:
            self.p._download_tracks(items)

    def _menu_select_all(self):
        self.sel_mode = True
        self.sel = {self._key(m) for m in self.items}
        for R in list(self.row_refs.values()):
            self._apply_sel(R)
        with tolerated():
            self._update_title()
        self._sel_menu()

    def _sel_music(self):
        items = self._sel_items()
        if not items:
            return
        if len(items) > 100:
            self.p._bulletin(strings("save_up_to_100_tracks_at"), error=True)
            return
        self._set_sel_mode(False)
        self.p._save_to_music(items)

    def _after_close(self, fn):
        with tolerated():
            self.dialog.dismiss()
        self.handler.postDelayed(self.Run(fn), 150)

    def _track_menu(self, m, queue_row=False):
        if queue_row:
            self.p._show_queue_track_menu(m, editor=self)
            return
        extras = [
       (strings("open_telegrams_player"), strings("the_built_in_full_player"), False, self._menu_tg_player),
       (strings("open_music_settings"), strings("configure_music"), False, self.p._open_plugin_settings),
       ]
        self.p._track_sheet(self.act, m, [self.p._hero_add_to(self.act, m)], extras, editor=self)

    def _sleep_menu(self):
        from ..sheets import _ActionSheet
        p = self.p
        st = p.sleep_status()
        quick = [(strings("n_min", n), (lambda mm=n: p.sleep_set_minutes(mm)), False, None)
       for n in (5, 15, 30, 45)]
        quick += [(strings("1_hour"), lambda: p.sleep_set_minutes(60), False, None),
       (strings("end_of_track"), p.sleep_set_eot, False, None)]
        opts = []
        if st:
            opts.append((strings("turn_off_timer"), "", True, p.sleep_cancel))
        _ActionSheet(p, self.act).show_sheet(
       strings("sleep_timer"), st or strings("pause_playback_automatically"), opts, quick)

    def _offline_label(self, v=None):
        v = self.p._offline_mode() if v is None else v
        return (strings("state_off"), strings("state_on"), strings("auto"))[v]

    def _offline_menu(self):
        from ..sheets import _ActionSheet
        p = self.p
        cur = p._offline_mode()
        def pick(v):
            p._offline_set(v)
            ed = getattr(p, "_editor", None)
            if ed is not None:
                with tolerated():
                    ed._update_offline_icon()
                    pi = ed._playing_pos()
                    for i in list(ed.row_refs):
                        ed._style_row(i, pi)
            with tolerated():
                self._refresh()
        quick = [(self._offline_label(v), (lambda x=v: pick(x)), False, None, cur == v) for v in (0, 1, 2)]
        _ActionSheet(p, self.act).show_sheet(
       strings("offline_mode"), strings("offline_mode_modes_sub"), [], quick)

    def _crossfade_menu(self):
        from ..sheets import _ActionSheet
        p = self.p
        xf = getattr(p, "_xf", None)
        if xf is None:
            p._bulletin(strings("crossfade_is_unavailable"), error=True)
            return
        cur = xf.sec()
        quick = [(strings("state_off") if s == 0 else f"{s} s", (lambda v=s: xf.set_sec(v)), False, None, cur == s)
       for s in (0, 3, 6, 10)]
        opts = [
       (strings("fade_on_skip"), strings("short_blend_when_you_change_tracks"), False,
       lambda: xf.flip("crossfade_skip", True),
       strings("state_on") if xf.flag("crossfade_skip", True) else strings("state_off"),
       lambda: xf.flag("crossfade_skip", True)),
       ]
        _ActionSheet(p, self.act).show_sheet(
       strings("crossfade"), strings("blend_the_end_of_a_track"), opts, quick)

    def _mini_menu(self):
        _, pm = self._mini_playing()
        if pm is not None:
            self.p._show_queue_track_menu(pm, editor=self)
            return
        g = self._ghost_track()
        if g is None:
            self.p._bulletin(strings("nothing_is_playing"), error=True)
            return
        self.p._track_sheet(self.act, g, [self.p._hero_add_to(
       self.act, g, False, strings("add_this_track_to_a_playlist"))], editor=self)

    def _row_action(self, fn, m):
        try:
            ok = bool(fn(m))
        except Exception:
            ok = False
        if not ok:
            self.p._bulletin(strings("couldnt_do_that"), error=True)
        self._reload()

    def _style_row(self, i, pi):
        R = self.row_refs.get(i)
        if not R:
            return
        play_iv, t1, info, lead = R["play"], R["t1"], R["info"], R["lead"]
        downloaded = R["state"] == 2
        if self._tf is None:
            T = _cls("android.graphics.Typeface")
            self._tf = (T.DEFAULT_BOLD, T.DEFAULT)
        playing = (i == pi)
        paused = bool(getattr(self, "_paused", True))
        row_pp = R.get("play_pp")
        if row_pp is not None:
            try:
                row_pp.setPause(bool(playing and not paused), True)
            except Exception:
                ic = getattr(self, "_ic_pause", 0) if (playing and not paused) else getattr(self, "_ic_play", 0)
                if ic:
                    play_iv.setImageResource(int(ic))
        else:
            ic = getattr(self, "_ic_pause", 0) if (playing and not paused) else getattr(self, "_ic_play", 0)
            if ic:
                play_iv.setImageResource(int(ic))
        t1.setTypeface(self._tf[0] if playing else self._tf[1])
        if R["state"] == 3 or (not downloaded and self.p._offline_active()):
            a = 0.4
        else:
            a = 1.0
        info.setAlpha(a)
        lead.setAlpha(a)

    def _on_track_changed(self):
        new = self._playing_pos()
        if new >= 0 and not (self.win_start <= new < self.win_end):
            self.queue_lazy_ready = False
            self._refresh()
            self._snap_to_playing_predraw()
            self.handler.postDelayed(self.Run(self._scroll_to_playing), 70)
            return
        for i in list(self.row_refs.keys()):
            self._style_row(i, new)
        self._styled_playing = new

    def _play(self, m):
        mc = self.p._get_mc()
        if getattr(self.p, "_closed", None) is not None:
            with tolerated():
                self.p._rs_reopen_closed(play=False)
        try:
            self.p._allow_remote = True
            try:
                mc.playMessage(m)
            finally:
                self.p._allow_remote = False
            self.p._sync_order_to(mc, m)
            self.handler.postDelayed(self.Run(lambda: self.p._sync_order_to(mc, m)), 200)
            self.playing_key = self._key(m)
            self._on_track_changed()
            self._nudge_update()
        except Exception:
            self.p._bulletin(strings("could_not_play_that_track"), error=True)

    def _res(self, *names):
        with tolerated():
            r = self.act.getResources()
            pkg = self.act.getPackageName()
            for n in names:
                i = int(r.getIdentifier(n, "drawable", pkg))
                if i:
                    return i
        idx = _rd_index()
        for n in names:
            if n in idx:
                return idx[n]
        return 0

    def _drag_handle(self, description=strings("drag_to_reorder")):
        FL = _cls("android.widget.FrameLayout")
        FLP = _cls("android.widget.FrameLayout$LayoutParams")
        handle = FL(self.act)
        handle.setMinimumWidth(self.dp(36))
        handle.setMinimumHeight(self.dp(44))
        glyph = self._text("⠿", 21, self.c_sub, gravity=17)
        with tolerated():
            glyph.setIncludeFontPadding(False)
        handle.addView(glyph, FLP(-1, -1, 17))
        handle.setContentDescription(description)
        handle.setClickable(True)
        handle.setFocusable(True)
        return handle

    def _glyph_icon(self, names, tint, pad=9, size=24, bold=False):
        iv = _cls("android.widget.ImageView")(self.act)
        iv.setImageResource(int(self._res(*names)))
        iv.setColorFilter(tint)
        iv.setPadding(self.dp(pad), self.dp(pad), self.dp(pad), self.dp(pad))
        return iv

    def _icon(self, names, fallback, tint, fn=None, pad=10):
        iv = _cls("android.widget.ImageView")(self.act)
        iv.setImageResource(int(self._res(*names) or fallback))
        iv.setColorFilter(tint)
        iv.setPadding(self.dp(pad), self.dp(pad), self.dp(pad), self.dp(pad))
        if fn is not None:
            iv.setOnClickListener(self.Click(lambda v: fn()))
        return iv

    def _centered_bar(self, left, center, right, reserve_dp, side_dp=8, align_left=False, right_reserve_dp=None):
        FL = _cls("android.widget.FrameLayout")
        FLP = _cls("android.widget.FrameLayout$LayoutParams")
        bar = FL(self.act)
        res = self.dp(reserve_dp)
        if center is not None:
            if align_left:
                lp = FLP(-1, -2, 8388627)
                lp.setMargins(res, 0, self.dp(right_reserve_dp if right_reserve_dp is not None else reserve_dp), 0)
            else:
                lp = FLP(-1, -2, 17)
                lp.setMargins(res, 0, self.dp(right_reserve_dp) if right_reserve_dp is not None else res, 0)
            bar.addView(center, lp)
        if left is not None:
            lp = FLP(-2, -2, 8388627)
            lp.setMargins(self.dp(side_dp), 0, 0, 0)
            bar.addView(left, lp)
        if right is not None:
            lp = FLP(-2, -2, 8388629)
            lp.setMargins(0, 0, self.dp(self.BAR_END_DP), 0)
            bar.addView(right, lp)
        bar.setPadding(0, 0, 0, self.dp(2))
        return bar

    def _like_res(self):
        ids = getattr(self, "_like_res_ids", False)
        if ids is False:
            ids = (int(self._res("media_like")), int(self._res("media_like_active")))
            self._like_res_ids = ids
        return ids

    def _liked_badge(self, m):
        ids = self._like_res()
        iv = _cls("android.widget.ImageView")(self.act)
        iv.setImageResource(ids[1])
        iv.setColorFilter(self.c_accent)
        pd = self.dp(3)
        iv.setPadding(pd, pd, pd, pd)
        with tolerated():
            iv.setContentDescription(strings("liked"))
            iv.setVisibility(0 if self.p._is_track_liked(m) else 8)
        return iv

    def _refresh_liked_icons(self):
        with tolerated():
            self._like_sig = None
            _mc, _pm = self._mini_playing()
            self._update_mini_like(_pm if _pm is not None else self._ghost_track())
        keys = self.p._liked_keys()
        def upd(iv, m):
            if iv is None or m is None:
                return
            with tolerated():
                iv.setVisibility(0 if self._key(m) in keys else 8)
        for refs in list(getattr(self, "lib_track_rows", {}).values()):
            dl = refs.get("dl")
            upd(refs.get("liked"), dl.get("m") if dl else None)
        for R in list(getattr(self, "row_refs", {}).values()):
            upd(R.get("liked"), R.get("m"))

    def _update_offline_icon(self):
        try:
            vis = 0 if self.p._offline_active() else 8
        except Exception:
            return
        on = vis == 0
        if getattr(self, "_offline_last", None) != on:
            self._offline_last = on
            for refs in list(getattr(self, "lib_track_rows", {}).values()):
                R = refs.get("dl")
                if R:
                    with tolerated():
                        self._lib_dim_offline(R)

    def _header_btn(self, names, fn):
        return self._icon(names, 0, self.c_text, fn, pad=12)

    def _build_mini(self, root):
        act = self.act
        LL = _cls("android.widget.LinearLayout")
        FL = _cls("android.widget.FrameLayout")
        FLP = _cls("android.widget.FrameLayout$LayoutParams")
        IV = _cls("android.widget.ImageView")
        SeekBar = _cls("android.widget.SeekBar")
        View = _cls("android.view.View")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        CSL = _cls("android.content.res.ColorStateList")
        Dr = _cls("android.R$drawable")
        LP = self.LP
        self.seeking = False
        self._mini_last = None
        self._like_sig = None
        self._mini_state = None
        self._rep_state = None
        self._SC = find_class("org.telegram.messenger.SharedConfig")
        self._ic_play = int(self._res("ic_action_play", "ic_play") or Dr.ic_media_play)
        self._ic_pause = int(self._res("ic_action_pause", "ic_pause") or Dr.ic_media_pause)
        box = LL(act)
        box.setOrientation(1)
        box.setPadding(self.dp(16), self.dp(12), self.dp(16), self.dp(6))
        card = GD()
        card.setColor(self.c_player_bg)
        card.setCornerRadius(float(self.dp(22)))
        self.mini_fill = None
        try:
            fill = GD()
            fill.setColor(_mix(self.c_player_bg, self.c_player_progress, 0.32))
            fill.setCornerRadius(float(self.dp(22)))
            clip = _cls("android.graphics.drawable.ClipDrawable")(fill, 8388611, 1)
            clip.setLevel(0)
            layers = _cls("android.graphics.drawable.LayerDrawable")(
          jarray(_cls("android.graphics.drawable.Drawable"))([card, clip]))
            box.setBackground(layers)
            self.mini_fill = clip
        except Exception:
            box.setBackground(card)
        top = LL(act)
        top.setOrientation(0)
        top.setGravity(16)
        cov = FL(act)
        self.mini_cov = cov
        cbg = GD()
        cbg.setColor(self.c_player_bg)
        cbg.setCornerRadius(float(self.dp(12)))
        cov.setBackground(cbg)
        with tolerated():
            cov.setClipToOutline(True)
        self.mini_glyph = self._glyph_icon(("files_music", "msg_filled_data_music"), self.c_player_sub, pad=26, size=30)
        cov.addView(self.mini_glyph, FLP(-1, -1))
        try:
            self.cover = find_class("org.telegram.ui.Components.BackupImageView")(act)
            self.cover.setRoundRadius(self.dp(12))
            self.cover_biv = True
        except Exception:
            self.cover = IV(act)
            self.cover.setScaleType(_cls("android.widget.ImageView$ScaleType").CENTER_CROP)
            self.cover_biv = False
        cov.addView(self.cover, FLP(-1, -1))
        cover_click = self.Click(lambda v: self._show_cover_large())
        cov.setOnClickListener(cover_click)
        self.cover.setOnClickListener(cover_click)
        top.addView(cov, LP(self.dp(92), self.dp(92)))
        col = LL(act)
        col.setOrientation(1)
        col.setPadding(self.dp(14), 0, 0, 0)
        col.setClipToPadding(False)
        self.mini_top = top
        self.mini_title = self._text(strings("nothing_is_playing"), 18, self.c_player_text, bold=True, single=True)
        self.mini_sub = self._text("", 14, self.c_player_button, single=True)
        self._mini_pin_lines(1.0)
        self.mini_sub.setContentDescription(strings("open_artist_in_library"))
        self.mini_sub.setOnClickListener(self.Click(lambda v: self._open_mini_artist()))
        head = LL(act)
        head.setOrientation(0)
        head.setGravity(16)
        tcol = LL(act)
        tcol.setOrientation(1)
        tcol.addView(self.mini_title, LP(-1, self.dp(22)))
        self.mini_tcol = tcol
        self._mini_ts = None
        for _tv in (self.mini_title, self.mini_sub):
            _tv.setPivotX(0.0)
            _tv.setPivotY(0.0)
        tcol.addOnLayoutChangeListener(_layoutchg_proxy()(self._mini_fit_text))
        author_lp = LP(-2, -2)
        author_lp.setMargins(0, self.dp(2), 0, 0)
        author_lp.gravity = 8388611
        tcol.addView(self.mini_sub, author_lp)
        head.addView(tcol, LP(0, -2, 1.0))
        self.mini_locate = self._icon(
       ("msg_current_location",),
       int(getattr(Dr, "ic_menu_mylocation", Dr.ic_menu_search)),
       self.c_player_button, self._locate_current, pad=8)
        self.mini_locate.setContentDescription(strings("locate_current_track_in_queue"))
        self.mini_locate.setVisibility(8)
        head.addView(self.mini_locate, LP(self.dp(40), self.dp(40)))
        self.mini_cprev = self._skip_btn(False, self._mini_prev)
        self.mini_cprev.setPadding(self.dp(7), self.dp(7), self.dp(7), self.dp(7))
        self.mini_cprev.setContentDescription(strings("previous_track"))
        self.mini_cprev.setVisibility(8)
        head.addView(self.mini_cprev, LP(self.dp(34), self.dp(34)))
        self.mini_cplay = IV(act)
        cpbg = GD()
        cpbg.setShape(1)
        cpbg.setColor(self.c_player_progress)
        self.mini_cplay.setBackground(cpbg)
        self.mini_cpp = None
        try:
            cpp = find_class("org.telegram.ui.Components.PlayPauseDrawable")(28)
            cpp.setColor(-1)
            self.mini_cplay.setImageDrawable(cpp)
            with tolerated():
                cpp.setParent(self.mini_cplay)
            self.mini_cpp = cpp
        except Exception:
            self.mini_cplay.setImageResource(self._ic_play)
            self.mini_cplay.setColorFilter(-1)
        self.mini_cplay.setPadding(self.dp(9), self.dp(9), self.dp(9), self.dp(9))
        self.mini_cplay.setOnClickListener(self.Click(lambda v: self._mini_toggle()))
        self.mini_cplay.setVisibility(8)
        cplay_lp = LP(self.dp(38), self.dp(38))
        cplay_lp.setMargins(self.dp(4), 0, self.dp(2), 0)
        head.addView(self.mini_cplay, cplay_lp)
        self.mini_cnext = self._skip_btn(True, self._mini_next)
        self.mini_cnext.setPadding(self.dp(7), self.dp(7), self.dp(7), self.dp(7))
        self.mini_cnext.setContentDescription(strings("next_track"))
        self.mini_cnext.setVisibility(8)
        head.addView(self.mini_cnext, LP(self.dp(34), self.dp(34)))
        self._like_ids = (int(self._res("media_like") or 0), int(self._res("media_like_active") or 0))
        self.mini_like_btn = _cls("android.widget.ImageView")(act)
        self.mini_like_btn.setPadding(self.dp(7), self.dp(7), self.dp(7), self.dp(7))
        self.mini_like_btn.setContentDescription(strings("add_to_liked_songs"))
        self.mini_like_btn.setOnClickListener(self.Click(lambda v: self._mini_toggle_like()))
        head.addView(self.mini_like_btn, LP(self.dp(40), self.dp(40)))
        with tolerated():
            self.mini_like_btn.setImageResource(self._like_ids[0])
            self.mini_like_btn.setColorFilter(int(self.c_player_button))
        self.mini_head = head
        col.addView(head, LP(-1, -2))
        self.mini_bar = SeekBar(act)
        self.mini_bar.setMax(1000)
        self.mini_bar.setPadding(0, 0, 0, 0)
        self.mini_bar.setMinimumHeight(self.dp(24))
        try:
            LayerDrawable = _cls("android.graphics.drawable.LayerDrawable")
            ClipDrawable = _cls("android.graphics.drawable.ClipDrawable")
            GradientDrawable = _cls("android.graphics.drawable.GradientDrawable")
            Gravity = _cls("android.view.Gravity")
            bg_track = GradientDrawable()
            bg_track.setShape(0)
            bg_track.setColor(self.c_player_progress_bg)
            bg_track.setCornerRadius(float(self.dp(3)))
            progress_shape = GradientDrawable()
            progress_shape.setShape(0)
            progress_shape.setColor(self.c_player_progress)
            progress_shape.setCornerRadius(float(self.dp(3)))
            progress_clip = ClipDrawable(progress_shape, Gravity.LEFT, 1)
            layers = LayerDrawable(jarray(_cls("android.graphics.drawable.Drawable"))([bg_track, progress_clip]))
            layers.setId(0, 0x01020000)
            layers.setId(1, 0x0102000d)
            try:
                for li in (0, 1):
                    layers.setLayerHeight(li, self.dp(4))
                    layers.setLayerGravity(li, 0x17)
            except Exception:
                layers.setLayerInset(0, 0, self.dp(10), 0, self.dp(10))
                layers.setLayerInset(1, 0, self.dp(10), 0, self.dp(10))
            self.mini_bar.setProgressDrawable(layers)
            thumb = GradientDrawable()
            thumb.setShape(1)
            thumb.setColor(self.c_player_progress)
            thumb.setSize(self.dp(10), self.dp(10))
            thumb.setStroke(self.dp(1), self.c_bg)
            self.mini_bar.setThumb(thumb)
            self.mini_bar.setThumbOffset(0)
            tint = CSL.valueOf(self.c_player_progress)
            self.mini_bar.setProgressTintList(tint)
            self.mini_bar.setThumbTintList(tint)
        except Exception:
            with tolerated():
                tint = CSL.valueOf(self.c_player_progress)
                self.mini_bar.setProgressTintList(tint)
                self.mini_bar.setThumbTintList(tint)
        self.mini_bar.setOnSeekBarChangeListener(_seek_proxy()(self._on_seek))
        self.mini_bar.setOnTouchListener(self._hold(lambda v, e: False))
        seek_lp = LP(-1, self.dp(24))
        seek_lp.setMargins(0, self.dp(8), 0, 0)
        col.addView(self.mini_bar, seek_lp)
        self.mini_spacer = View(act)
        col.addView(self.mini_spacer, LP(-1, 0))
        times = LL(act)
        times.setOrientation(0)
        times.setGravity(16)
        times.setPadding(0, 0, 0, 0)
        self.mini_cur = self._text("0:00", 12, self.c_player_sub)
        self.mini_dur = self._text("0:00", 12, self.c_player_sub, gravity=5)
        times.addView(self.mini_cur, LP(0, -2, 1.0))
        times.addView(self.mini_dur, LP(0, -2, 1.0))
        col.addView(times, LP(-1, -2))
        self.mini_times = times

        self.mini_col = col
        col.setMinimumHeight(self.dp(92))
        top.addView(col, LP(0, -2, 1.0))
        box.addView(top, LP(-1, -2))
        FLc = _cls("android.widget.FrameLayout")
        FLPc = _cls("android.widget.FrameLayout$LayoutParams")
        ctl = FLc(act)
        ctl.setPadding(0, self.dp(6), 0, 0)
        ctl.setClipChildren(False)
        ctl.setClipToPadding(False)
        box.setClipChildren(False)
        top.setClipChildren(False)
        def grp(g):
            l = LL(act)
            l.setOrientation(0)
            l.setGravity(16)
            l.setClipChildren(False)
            ctl.addView(l, FLPc(-2, self.dp(60), g))
            return l
        left, mid, right = grp(8388611), grp(17), grp(8388613)
        tgt = [left]
        def cell(view, w, h, weight=0.0, gap=0):
            c = LL(act)
            c.setGravity(17)
            c.setClipChildren(False)
            c.addView(view, LP(w, h))
            params = LP(w, self.dp(60))
            if gap:
                params.setMargins(self.dp(gap), 0, self.dp(gap), 0)
            tgt[0].addView(c, params)
            return c
        self.mini_pill = LL(act)
        self.mini_pill.setOrientation(0)
        self.mini_pill.setGravity(17)
        self.mini_pill.setContentDescription(strings("playback_settings"))
        self.mini_pill.setOnClickListener(self.Click(lambda v: self._open_playback_sheet()))
        cell(self.mini_pill, -2, self.dp(36), gap=10)
        tgt[0] = mid
        xprev = self._skip_btn(False, self._mini_prev)
        prev_cell = cell(xprev, self.dp(48), self.dp(48))
        self.mini_play = IV(act)
        pbg = GD()
        pbg.setShape(1)
        pbg.setColor(self.c_player_progress)
        self.mini_play.setBackground(pbg)
        self.mini_pp = None
        try:
            pp = find_class("org.telegram.ui.Components.PlayPauseDrawable")(28)
            pp.setColor(-1)
            self.mini_play.setImageDrawable(pp)
            with tolerated():
                pp.setParent(self.mini_play)
            self.mini_pp = pp
        except Exception:
            self.mini_play.setImageResource(self._ic_play)
            self.mini_play.setColorFilter(-1)
        self.mini_play.setPadding(self.dp(14), self.dp(14), self.dp(14), self.dp(14))
        self.mini_play.setOnClickListener(self.Click(lambda v: self._mini_toggle()))
        play_cell = cell(self.mini_play, self.dp(56), self.dp(56), gap=6)
        xnext = self._skip_btn(True, self._mini_next)
        next_cell = cell(xnext, self.dp(48), self.dp(48))
        self._fly = [(self.mini_cplay, self.mini_play, play_cell, mid),
       (self.mini_cnext, xnext, next_cell, mid),
       (self.mini_cprev, xprev, prev_cell, mid)]
        tgt[0] = right
        self.mini_ccol = self._icon(("msg_go_down",), int(Dr.arrow_down_float), self.c_player_button,
       lambda: self._mini_apply(True), pad=10)
        self.mini_ccol.setContentDescription(strings("collapse_player"))
        cell(self.mini_ccol, self.dp(40), self.dp(48))
        cell(self._header_btn(("ic_ab_other", "msg_more"), self._mini_menu),
       self.dp(48), self.dp(48))
        ctl_lp = LP(-1, -2)
        ctl_lp.setMargins(-self.dp(6), 0, -self.dp(6), 0)
        box.addView(ctl, ctl_lp)
        self.mini_ctl = ctl
        blp = LP(-1, -2)
        blp.setMargins(self.dp(10), self.dp(8), self.dp(10), 0)
        root.addView(box, blp)
        self.mini_box = box
        box.setOnTouchListener(self._hold(self._mini_gesture()))
        self._mini_e = 1.0
        self._mini_anim = None
        try:
            saved = bool(self.p.get_setting("mini_compact", False))
        except Exception:
            saved = False
        if saved:
            self._mini_apply(True, animate=False, save=False)
        else:
            with tolerated():
                self.handler.postDelayed(self.Run(self._mini_capture), 500)

    def _mini_gesture(self):
        st = {"x": 0.0, "y": 0.0, "moved": False, "done": False}
        slop = float(int(jclass("android.view.ViewConfiguration").get(self.act).getScaledTouchSlop()))
        def on_touch(v, e):
            a = int(e.getActionMasked())
            if a == 0:
                st["x"], st["y"] = float(e.getRawX()), float(e.getRawY())
                st["moved"] = st["done"] = False
                with tolerated():
                    v.getParent().requestDisallowInterceptTouchEvent(True)
                return True
            if a == 2:
                dx = float(e.getRawX()) - st["x"]
                dy = float(e.getRawY()) - st["y"]
                if abs(dx) > slop or abs(dy) > slop:
                    st["moved"] = True
                if not st["done"] and abs(dx) > slop * 4 and abs(dx) > abs(dy) * 1.5:
                    st["done"] = True
                    if dx < 0:
                        self._mini_next()
                    else:
                        self._mini_prev()
                    return True
                if not st["done"] and abs(dy) > slop * 2 and abs(dy) > abs(dx):
                    st["done"] = True
                    compact = bool(getattr(self, "_mini_hid", False))
                    if dy < 0 and compact:
                        self._mini_apply(False)
                    elif dy > 0 and not compact:
                        self._mini_apply(True)
                return True
            if a == 1:
                if not st["moved"] and not st["done"]:
                    self._mini_apply(not bool(getattr(self, "_mini_hid", False)))
                return True
            return a == 3
        return on_touch

    def _show_cover_large(self):
        from ..editor import _QueueEditor
        _, pm = self._mini_playing()
        if pm is None:
            return
        with tolerated():
            Dialog = _cls("android.app.Dialog")
            FL = _cls("android.widget.FrameLayout")
            FLP = _cls("android.widget.FrameLayout$LayoutParams")
            LL = _cls("android.widget.LinearLayout")
            TextView = _cls("android.widget.TextView")
            IV = _cls("android.widget.ImageView")
            GD = _cls("android.graphics.drawable.GradientDrawable")
            CD = _cls("android.graphics.drawable.ColorDrawable")
            dm = self.act.getResources().getDisplayMetrics()
            dlg = Dialog(self.act)
            dlg.requestWindowFeature(1)
            root = FL(self.act)
            root.setBackground(CD(_argb(238, 0, 0, 0)))
            try:
                art = find_class("org.telegram.ui.Components.BackupImageView")(self.act)
                art.setRoundRadius(self.dp(18))
                is_biv = True
            except Exception:
                art = IV(self.act)
                art.setScaleType(_cls("android.widget.ImageView$ScaleType").FIT_CENTER)
                is_biv = False
            def _mini_cover_bitmap():
                with tolerated():
                    receiver = self.cover.getImageReceiver()
                    for method in ("getBitmapSafe", "getBitmap", "getBitmapDrawable"):
                        with tolerated():
                            image = self._as_bitmap(getattr(receiver, method)())
                            if image is not None:
                                return image
                with tolerated():
                    image = self._as_bitmap(self.cover.getDrawable())
                    if image is not None:
                        return image
                try:
                    used = getattr(self, "_bmp_used", None)
                    return self._as_bitmap(used[0]) if used is not None else None
                except Exception:
                    return None
            def load_embedded():
                with tolerated():
                    mc, _ = self._mini_playing()
                    image = self._as_bitmap(self.p._info_cover(mc, pm))
                    if image is not None:
                        art.setImageBitmap(image)
                        return True
                with tolerated():
                    doc = pm.getDocument()
                    if doc is not None:
                        size = self._best_thumb(doc, hq=True)
                        if size is not None:
                            IL = find_class("org.telegram.messenger.ImageLocation")
                            loc = IL.getForDocument(size, doc)
                            if loc is not None:
                                art.setImage(loc, "1280_1280",
                         _cls("android.graphics.drawable.ColorDrawable")(0), pm)
                                return True
                image = _mini_cover_bitmap()
                if image is not None:
                    with tolerated():
                        art.setImageBitmap(image)
                        return True
                with tolerated():
                    if not is_biv:
                        art.setImageDrawable(None)
                return False
            load_embedded()
            side_dp = max(180, min(int(dm.widthPixels / self.density) - 40,
          int(dm.heightPixels / self.density * 0.64)))
            content = LL(self.act)
            content.setOrientation(1)
            content.setGravity(17)
            art_lp = self.LP(self.dp(side_dp), self.dp(side_dp))
            content.addView(art, art_lp)
            cs = {"sel": 0, "url": None, "row": None,
          "lookup_started": False, "loading_url": None}
            def show_source(i):
                if i == 0:
                    load_embedded()
                    return
                url = cs["url"]
                if not url:
                    if not cs["lookup_started"]:
                        cs["lookup_started"] = True
                        threading.Thread(target=find_itunes_url, daemon=True).start()
                    return
                big = self.p.__dict__.setdefault("_cover_big", {})
                if url in big:
                    with tolerated():
                        art.setImageBitmap(big[url])
                    return
                if cs["loading_url"] == url:
                    return
                cs["loading_url"] = url
                def fetch():
                    try:
                        BF = _cls("android.graphics.BitmapFactory")
                        stream = _http_stream(url)
                        try:
                            image = BF.decodeStream(stream)
                        finally:
                            stream.close()
                        if image is None:
                            raise RuntimeError("iTunes returned an unreadable image")
                        big[url] = image
                        while len(big) > 2:
                            big.pop(next(iter(big)), None)
                        def apply():
                            if cs["sel"] == 1 and cs["url"] == url:
                                art.setImageBitmap(image)
                        run_on_ui_thread(apply)
                    except Exception:
                        cs["loading_url"] = None
                        run_on_ui_thread(lambda: self._toast(strings("couldnt_load_the_itunes_cover"), True))
                threading.Thread(target=fetch, daemon=True).start()
            def pick_source(i):
                cs["sel"] = i
                render_source_row()
                show_source(i)
            def render_source_row():
                at = 1
                if cs["row"] is not None:
                    at = content.indexOfChild(cs["row"])
                    if at < 0:
                        at = 1
                    content.removeView(cs["row"])
                cs["row"] = self._chip_row(("cover_src",), [{"title": strings("embedded"), "pad_l": 14},
             {"title": "iTunes", "pad_l": 14}],
             cs["sel"], pick_source, parent=content,
             row_width_dp="wrap", margins_dp=(0, 14, 0, 0),
             index=at)
            def find_itunes_url():
                try:
                    author = (_QueueEditor._author_of(pm) or "").strip()
                    title = _QueueEditor._title_of(pm)
                    t = self._album_norm(title, author)
                    a = self._artist_entry(author)
                    album = (a.get("al") or {}).get(t)
                    url = ((a.get("am") or {}).get(album) or {}).get("art") if album else None
                    if not url and author and title:
                        import urllib.parse
                        res = json.loads(_http_text(
                   "https://itunes.apple.com/search?media=music&entity=song&limit=10&term=" +
                   urllib.parse.quote(f"{author} {title}"))).get("results") or []
                        nn = lambda x: re.sub(r"[\W_]+", "", str(x).casefold())
                        first = re.split(r"\s*(?:,|&|/|;)\s*", author)[0]
                        hit = next((r for r in res
                   if self._album_norm(r.get("trackName"), author) == t
                   and nn(first) in nn(r.get("artistName", ""))
                   and r.get("artworkUrl100")), None)
                        url = hit["artworkUrl100"] if hit else None
                    if url:
                        url = re.sub(r"\d+x\d+bb", "1200x1200bb", url)
                        def ready():
                            with tolerated():
                                if dlg.isShowing():
                                    cs["url"] = url
                                    cs["lookup_started"] = False
                                    render_source_row()
                                    if cs["sel"] == 1:
                                        show_source(1)
                        run_on_ui_thread(ready)
                    else:
                        def not_found():
                            cs["lookup_started"] = False
                            with tolerated():
                                if dlg.isShowing() and cs["sel"] == 1:
                                    self._toast(strings("couldnt_find_an_itunes_cover"), True)
                        run_on_ui_thread(not_found)
                except Exception:
                    cs["lookup_started"] = False
                    run_on_ui_thread(lambda: self._toast(strings("couldnt_find_an_itunes_cover"), True))
            render_source_row()
            save_btn = LL(self.act)
            save_btn.setOrientation(0)
            save_btn.setGravity(17)
            save_btn.setPadding(self.dp(18), self.dp(12), self.dp(18), self.dp(12))
            save_bg = GD()
            save_bg.setShape(0)
            save_bg.setColor(_mix(self.c_item, self.c_accent, 0.18))
            save_bg.setCornerRadius(float(self.dp(24)))
            save_btn.setBackground(save_bg)
            save_icon = IV(self.act)
            icon_id = self._res("msg_gallery", "msg_save_to_gallery", "msg_save_gallery", "msg_download")
            if icon_id:
                save_icon.setImageResource(int(icon_id))
                save_icon.setColorFilter(self.c_text)
            else:
                save_icon.setImageDrawable(None)
            save_btn.addView(save_icon, self.LP(self.dp(22), self.dp(22)))
            label = TextView(self.act)
            label.setText(strings("save_to_gallery"))
            label.setTextColor(self.c_text)
            label.setTextSize(14)
            label.setGravity(51)
            label.setPadding(self.dp(9), 0, 0, 0)
            save_btn.addView(label, self.LP(-2, -2))
            save_btn.setContentDescription(strings("save_album_cover_to_gallery"))
            save_btn.setClickable(True)
            save_btn.setFocusable(True)
            btn_lp = self.LP(-2, -2)
            btn_lp.setMargins(0, self.dp(18), 0, 0)
            content.addView(save_btn, btn_lp)
            root.addView(content, FLP(-1, -2, 17))
            close = self.Click(lambda v: dlg.dismiss())
            root.setOnClickListener(close)
            art.setOnClickListener(close)
            save_btn.setOnClickListener(self.Click(lambda v: self._save_cover_gallery(art, pm)))
            label.setOnClickListener(self.Click(lambda v: self._save_cover_gallery(art, pm)))
            save_icon.setOnClickListener(self.Click(lambda v: self._save_cover_gallery(art, pm)))
            dlg.setContentView(root)
            dlg.setCanceledOnTouchOutside(True)
            dlg.show()
            win = dlg.getWindow()
            if win is not None:
                win.setBackgroundDrawable(CD(0))
                win.setLayout(-1, -1)
                win.setGravity(17)

    @staticmethod
    def _as_bitmap(value):
        if value is None:
            return None
        for _ in range(3):
            try:
                if str(value.getClass().getName()) == "android.graphics.Bitmap":
                    return value
            except Exception:
                return None
            nxt = None
            try:
                nxt = value.getBitmap()
            except Exception:
                try:
                    nxt = value.bitmap
                except Exception:
                    try:
                        nxt = value.drawable.getBitmap()
                    except Exception:
                        nxt = None
            if nxt is None:
                return None
            value = nxt
        return None
