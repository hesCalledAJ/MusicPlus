from .compat import dynamic_proxy, find_class, jarray, jclass, jfloat
from elyx import strings
from .helpers import _profile_music_icons
from .android import (
 _PIN_ICONS,
 _UNPIN_ICONS,
 _cls,
 _mix,
 _seek_proxy,
 _viewlong_proxy,
 _wide_px,
)
from .glass import _attach_sheet_drag
from .editor import _QueueEditor
from .safe import tolerated


class _ActionSheet(_QueueEditor):
    SLEEP_ICONS = ("msg_stories_timer",)
    _DEL = ("msg_delete",)
    _LABEL_ICONS = (
    ("share as playlist", ("msg_filled_shareout", "msg_shareout", "msg_share")),
    ("play this track next", ("msg_add",)),
    ("replace the queue", ("menu_browser_refresh", "msg_retry", "msg_repeat")),
    ("open plugin settings", ("msg_settings", "ic_ab_settings", "msg2_settings")),
    ("open telegram's player", ("msg_music", "ic_player", "msg_openin")),
    ("open music + settings", ("msg_settings", "ic_ab_settings", "msg2_settings")),
    ("open music + queue", ("msg_list", "msg_reorder")),
    ("open queue", ("msg_list", "msg_reorder")),
    ("unpin artist", _UNPIN_ICONS),
    ("pin artist", _PIN_ICONS),
    ("add as friend", ("filled_profile_member_24", "msg_add")),
    ("add chat to library", ("msg_folders", "msg_add")),
    ("add topic to library", ("msg_discussion", "msg_groups")),
    ("close and unlock", ("msg_close",)),
    ("open music +", ("msg_media", "msg_list")),
    ("sort tracks", ("iv_ordered_list",)),
    ("sort", ("msg2_sort", "msg_sortby", "msg_filter")),
    ("open smart queue manager", ("msg_reorder", "msg_list")),
    ("crossfade", ("msg_blur_linear",)),
    ("sleep", SLEEP_ICONS),
    ("turn off timer", ("msg_close",)),
    ("clear selection", ("msg_close",)),
    ("select", ("msg_select", "msg_check_s", "checkbig")),
    ("shuffle", ("player_new_shuffle",)),
    ("reverse", ("player_new_order", "player_reverse")),
    ("download", ("msg_download", "menu_download_24")),
    ("offline", ("menu_download_off_24", "msg_download")),
    ("lock queue", ("msg2_lock", "msg_lock", "msg_secret", "msg_privacy")),
    ("clear queue", _DEL),
    ("remove", _DEL),
    ("exclude", ("filled_clear", "msg_close")),
    ("play next", ("ic_action_next", "msg_arrowright")),
    ("add next", ("ic_action_next", "msg_arrowright")),
    ("new playlist", ("msg_add",)),
    ("add to queue", ("msg_add",)),
    ("add to end", ("msg_add",)),
    ("play at end", ("msg_add",)),
    ("move up", ("msg_go_up",)),
    ("move down", ("msg_go_down",)),
    ("move to end", ("filled_reply_settings", "msg_go_down")),
    ("add to bottom", ("msg_add",)),
    ("play", ("ic_action_play", "msg_round_play_m")),
    ("forward", ("msg_forward",)),
    ("save to music", ("msg_download", "msg_saved")),
    ("save", ("msg_saved", "msg_download")),
    ("show in chat", ("msg_viewintopic", "msg_view_file")),
    ("rename", ("msg_edit", "msg_edt")),
    ("hold for full rescan", ("msg_retry", "msg_refresh", "ic_ab_refresh", "msg_rotate")),
    ("rescan", ("msg_retry", "msg_refresh", "ic_ab_refresh", "msg_rotate")),
    ("remove from library", _DEL),
    ("view artist", ("summary_arrow", "msg_profile", "msg_user", "msg_music")),
    ("search for artist", ("msg_usersearch", "msg_search", "ic_ab_search")),
    ("delete playlist", _DEL),
    )
    _LABEL_STRKEYS = {
    "add_as_friend": "add as friend",
    "add_chat_to_library": "add chat to library",
    "add_to_end": "add to end",
    "add_to_queue_failed": "add to queue",
    "add_topic_to_library": "add topic to library",
    "clear_queue": "clear queue",
    "clear_selection": "clear selection",
    "close_and_unlock_queue": "close and unlock",
    "crossfade": "crossfade",
    "crossfade_is_unavailable": "crossfade",
    "delete_playlist": "delete playlist",
    "new_playlist": "new playlist",
    "download": "download",
    "download_and_save_this_track": "download",
    "download_the_selected_tracks": "download",
    "download_this_track": "download",
    "download_up_to_100_tracks_at": "download",
    "downloaded_songs": "download",
    "downloading_backup": "download",
    "downloading_n_tracks": "download",
    "downloading_n_tracks_will_save_to": "download",
    "downloads_tracks_before_saving": "download",
    "exclude_from_queue": "exclude",
    "excluded_artists": "exclude",
    "excluded_artists_n": "exclude",
    "excluded_n_tracks_n": "exclude",
    "excluded_n_tracks_of_this_n": "exclude",
    "forward": "forward",
    "forward_selected_tracks_to_a_chat": "forward",
    "forward_this_track_to_a_chat": "forward",
    "forward_up_to_100_tracks_at": "forward",
    "lock_queue": "lock queue",
    "lock_queue_behavior": "lock queue",
    "lock_queue_is_enabled": "lock queue",
    "move_to_end": "move to end",
    "offline_cache_cleared_n_mb": "offline",
    "offline_library_cache": "offline",
    "offline_mode": "offline",
    "offline_mode_no_downloaded_tracks_to": "offline",
    "offline_mode_no_more_downloaded_tracks": "offline",
    "open_music": "open music +",
    "open_music_settings": "open music + settings",
    "open_music_to_view_this_artist": "open music +",
    "open_telegrams_player": "open telegram's player",
    "pin_artist": "pin artist",
    "play": "play",
    "play_a_track_from_any_chat": "play",
    "play_next": "play next",
    "play_next_failed": "play next",
    "play_this_track_next": "play this track next",
    "playback": "play",
    "playback_queue": "play",
    "playback_settings": "play",
    "playback_stopped_start_a_track_first": "play",
    "player_not_available": "play",
    "playing_next": "play",
    "playlist": "play",
    "playlist_n_n_tracks": "play",
    "playlist_name": "play",
    "playlist_reversed": "play",
    "playlist_shuffled": "play",
    "playlists": "play",
    "remove": "remove",
    "remove_from_library": "remove",
    "remove_from_liked_songs": "remove",
    "remove_from_the_top_of_artists": "remove",
    "remove_the_other_queued_tracks": "remove",
    "removed_from_library_change_this_later": "remove",
    "removed_n": "remove",
    "removed_n_2": "remove",
    "removed_n_tracks": "remove",
    "removed_the_unavailable_track": "remove",
    "rename_playlist": "rename",
    "replace_the_queue": "replace the queue",
    "rescan": "rescan",
    "rescan_this_chat": "rescan",
    "rescanning": "rescan",
    "rescanning_chat_n_new_tracks_found": "rescan",
    "reverse": "reverse",
    "reverse_order": "reverse",
    "reverse_the_current_track_order": "reverse",
    "reverse_undone": "reverse",
    "save": "save",
    "save_album_cover_to_gallery": "save",
    "save_as_playlist": "save",
    "save_this_users_profile_music_to": "save",
    "save_to_gallery": "save",
    "save_to_music": "save to music",
    "save_up_to_100_tracks_at": "save",
    "saved_cover_to_gallery": "save",
    "saved_messages": "save",
    "saved_n_n_tracks": "save",
    "saved_n_to_library_friends": "save",
    "saved_n_tracks_n_failed": "save",
    "saved_n_tracks_to_music": "save",
    "saved_playlists": "save",
    "saved_to_music": "save",
    "saves_a_backup_file_to_your": "save",
    "saves_each_library_chats_tracks_on": "save",
    "saves_the_previous_queue_as_a": "save",
    "search_for_artist": "search for artist",
    "search_for_artist_in_telegram_music": "search for artist",
    "select": "select",
    "select_all": "select",
    "select_at_least_one_track": "select",
    "select_tracks": "select",
    "select_up_to_100_tracks": "select",
    "selection": "select",
    "share_as_playlist": "share as playlist",
    "show_in_chat": "show in chat",
    "shuffle": "shuffle",
    "shuffle_is_on_order_applies_once": "shuffle",
    "shuffle_undone": "shuffle",
    "shuffled": "shuffle",
    "sleep_timer": "sleep",
    "sleep_timer_pausing_after_this_track": "sleep",
    "sleep_timer_playback_paused": "sleep",
    "sort": "sort",
    "sort_artists": "sort",
    "sort_by_title_artist_duration_or": "sort",
    "sort_playlist": "sort",
    "sort_playlists": "sort",
    "sort_queue": "sort",
    "sort_tracks": "sort tracks",
    "sort_undone": "sort",
    "list_sorted": "sort",
    "turn_off_timer": "turn off timer",
    "unpin_artist": "unpin artist",
    "view_artist": "view artist",
    }
    _loc_label_cache = None
    def _loc_label_map(self):
        c = _ActionSheet._loc_label_cache
        if c is None:
            c = []
            icons = dict(self._LABEL_ICONS)
            for sk, en_key in self._LABEL_STRKEYS.items():
                try:
                    loc = str(strings(sk)).lower().split("{")[0].strip()
                except Exception:
                    continue
                if len(loc) >= 2:
                    c.append((loc, icons[en_key]))
            c.sort(key=lambda t: -len(t[0]))
            _ActionSheet._loc_label_cache = c
        return c
    def _label_names(self, label):
        l = (str(label)).lower()
        if l.startswith(("set as profile playlist", "add to profile playlist")):
            return ("filled_track_add",) + tuple(_profile_music_icons())
        for key, names in self._LABEL_ICONS:
            if l.startswith(key):
                return names
        if l.startswith(self._loc_profile_prefixes()):
            return ("filled_track_add",) + tuple(_profile_music_icons())
        for loc, names in self._loc_label_map():
            if l.startswith(loc):
                return names
        return None
    def _loc_profile_prefixes(self):
        out = []
        for sk in ("set_as_profile_playlist", "add_to_profile_playlist"):
            with tolerated():
                out.append(str(strings(sk)).lower())
        return tuple(out) or ("\0",)
    @staticmethod
    def _fx(v, a):
        if a == 0:
            v.setAlpha(0.6)
        elif a in (1, 3):
            v.setAlpha(1.0)
        return False
    def _press_fx(self, v):
        v.setOnTouchListener(self.Touch(lambda vv, e: self._fx(vv, int(e.getActionMasked()))))
    def _toggle_click(self, cb, sw, getter):
        def _c(v):
            with tolerated():
                cb()
            with tolerated():
                sw.setChecked(bool(getter()) if getter is not None else not bool(sw.isChecked()))
        return self.Click(_c)
    def _opt_tile(self, pl, cd):
        icon = self._lib_pl_icon(pl)
        self.lib_covers = []
        tile = self._lib_tile_b(None, cd, ("files_music", "msg_filled_data_music", "msg_music", "msg_media"),
                                None if icon else self._lib_playlist_cover_messages(pl.get("tracks")), icon)
        for c in self.lib_covers:
            c["done"] = True
            if self._load_cover(c["art"], c["m"], 0, "184_184", False) and c.get("glyph") is not None:
                c["glyph"].setVisibility(8)
        return tile

    def _lead_cover(self, m):
        cd = self.dp(48)
        lead, art = self._lib_song_lead(cd, m is not None)
        glyph = self._glyph_icon(("files_music", "msg_filled_data_music", "msg_music", "msg_media"), -1, pad=12, size=24)
        lead.addView(glyph, _cls("android.widget.FrameLayout$LayoutParams")(-1, -1))
        if m is not None and art is not None:
            self.lib_covers = []
            self._lib_cover_now(art, m, glyph, 48)
        return lead

    def show_sheet(self, title, subtitle, options, quick=None, artist_search=None,
    header_action=None, order_toggle=None, artist_view=None, artist_message=None,
    like_message=None, lead=None):
        if artist_view:
            with tolerated():
                ed = getattr(self.p, "_editor", None)
                if ed is not None and ed._lib_on_artist_page(artist_view):
                    artist_view = None
        act = self.act
        dm = act.getResources().getDisplayMetrics()
        wpx = _wide_px(act, 600)
        cols = 1
        LL = jclass("android.widget.LinearLayout")
        SV = jclass("android.widget.ScrollView")
        View = jclass("android.view.View")
        Dialog = jclass("android.app.Dialog")
        GD = jclass("android.graphics.drawable.GradientDrawable")
        CD = jclass("android.graphics.drawable.ColorDrawable")
        LP = self.LP
        red = self.c_red
        dp = self.dp
        dlg = Dialog(act)
        dlg.requestWindowFeature(1)
        root = LL(act)
        root.setOrientation(1)
        bg = GD()
        bg.setColor(self.c_bg)
        r = float(dp(16))
        bg.setCornerRadii(jarray(jfloat)([r, r, r, r, 0.0, 0.0, 0.0, 0.0]))
        root.setBackground(bg)
        root.setPadding(0, 0, 0, dp(12))
        grab = LL(act)
        grab.setGravity(17)
        pill = View(act)
        pg = GD()
        pg.setColor(_mix(self.c_bg, self.c_sub, 0.5))
        pg.setCornerRadius(float(dp(2)))
        pill.setBackground(pg)
        grab.addView(pill, LP(dp(36), dp(4)))
        root.addView(grab, LP(-1, dp(18)))
        has_like = like_message is not None
        if artist_search or artist_view or header_action or has_like:
            header = LL(act)
            header.setOrientation(0)
            header.setGravity(16)
            header.setPadding(dp(20), 0, dp(12), 0)
            title_col = LL(act)
            title_col.setOrientation(1)
            t = self._text(title, 18, self.c_text, bold=True, single=True)
            title_col.addView(t, LP(-1, -2))
            if subtitle:
                tap_artist = bool(has_like and artist_view)
                st = self._text(subtitle, 15 if has_like else 13,
             self.c_accent if tap_artist else self.c_sub, single=True)
                st.setPadding(0, dp(4 if has_like else 2), 0, dp(4 if has_like else 0))
                if tap_artist:
                    def _open_artist(v):
                        dlg.dismiss()
                        self.handler.postDelayed(
                   self.Run(lambda: self.p._view_artist_in_library(artist_view, artist_message)), 80)
                    st.setOnClickListener(self.Click(_open_artist))
                    st.setContentDescription(strings("open_artist_page_in_library"))
                title_col.addView(st, LP(-1, -2))
            if lead is not None:
                header.setPadding(dp(20), dp(2), dp(12), dp(8))
                llp = LP(dp(48), dp(48))
                llp.setMargins(0, 0, dp(14), 0)
                header.addView(lead, llp)
            header.addView(title_col, LP(0, -2, 1.0))
            def _header_chip(label, icon, handler, description, icon_size=40):
                chip = LL(act)
                chip.setOrientation(0)
                chip.setGravity(16)
                chip.addView(self._text(label, 13, self.c_sub, bold=True, single=True), LP(-2, -2))
                chip.addView(icon, LP(dp(icon_size), dp(icon_size)))
                chip.setContentDescription(description)
                chip.setOnClickListener(self.Click(handler))
                header.addView(chip, LP(-2, dp(40)))
            if header_action:
                names, description, callback = header_action
                action_btn = self._glyph_icon(names, self.c_sub, pad=8, size=21, bold=True)
                def _header_action(v):
                    dlg.dismiss()
                    self.handler.postDelayed(self.Run(callback), 80)
                _header_chip(strings("view_chat"), action_btn, _header_action, description)
            if artist_view and not has_like:
                view_btn = self._glyph_icon(
             ("summary_arrow", "msg_profile", "msg_user", "msg_music"), self.c_sub, pad=4, size=18)
                def _view_artist(v):
                    dlg.dismiss()
                    self.handler.postDelayed(
                self.Run(lambda: self.p._view_artist_in_library(artist_view, artist_message)), 80)
                _header_chip(strings("view_artist"), view_btn, _view_artist, strings("open_artist_page_in_library"), icon_size=28)
            if artist_search:
                search_btn = self._glyph_icon(
             ("msg_usersearch", "msg_search", "ic_ab_search"), self.c_sub, pad=8, size=20)
                def _search_artist(v):
                    dlg.dismiss()
                    self.handler.postDelayed(
                self.Run(lambda: self.p._open_artist_music_search(artist_search)), 80)
                _header_chip(strings("search_for_artist"), search_btn, _search_artist, strings("search_for_artist_in_telegram_music"))
            if has_like:
                ids = self._like_res()
                like_btn = jclass("android.widget.ImageView")(act)
                like_btn.setPadding(dp(9), dp(9), dp(9), dp(9))
                def paint_like():
                    liked = bool(self.p._is_track_liked(like_message))
                    like_btn.setImageResource(ids[1 if liked else 0])
                    like_btn.setColorFilter(self.c_accent if liked else self.c_sub)
                    like_btn.setContentDescription(
                strings("remove_from_liked_songs") if liked else strings("add_to_liked_songs"))
                def tap_like(v):
                    self.p._toggle_track_liked(like_message)
                    paint_like()
                    with tolerated():
                        like_btn.animate().cancel()
                        like_btn.setScaleX(0.55)
                        like_btn.setScaleY(0.55)
                        like_btn.animate().scaleX(1.0).scaleY(1.0).setDuration(420).setInterpolator(
                   _cls("android.view.animation.OvershootInterpolator")(4.0)).start()
                paint_like()
                like_btn.setOnClickListener(self.Click(tap_like))
                header.addView(like_btn, LP(dp(46), dp(46)))
            root.addView(header, LP(-1, -2))
        elif lead is not None:
            header = LL(act)
            header.setOrientation(0)
            header.setGravity(16)
            header.setPadding(dp(20), dp(2), dp(20), dp(8))
            llp = LP(dp(48), dp(48))
            llp.setMargins(0, 0, dp(14), 0)
            header.addView(lead, llp)
            title_col = LL(act)
            title_col.setOrientation(1)
            title_col.addView(self._text(title, 18, self.c_text, bold=True, single=True), LP(-1, -2))
            if subtitle:
                st = self._text(subtitle, 13, self.c_sub, single=True)
                st.setPadding(0, dp(2), 0, 0)
                title_col.addView(st, LP(-1, -2))
            header.addView(title_col, LP(0, -2, 1.0))
            root.addView(header, LP(-1, -2))
        else:
            t = self._text(title, 18, self.c_text, bold=True, single=True)
            t.setPadding(dp(20), 0, dp(20), 0)
            root.addView(t, LP(-1, -2))
            if subtitle:
                st = self._text(subtitle, 13, self.c_sub, single=True)
                st.setPadding(dp(20), dp(2), dp(20), 0)
                root.addView(st, LP(-1, -2))
        if order_toggle:
            ord_st = {"d": int(bool(order_toggle[0]))}
            seg = LL(act)
            seg.setOrientation(0)
            seg.setGravity(16)
            seg.setPadding(dp(3), dp(3), dp(3), dp(3))
            segbg = GD()
            segbg.setColor(self.c_item)
            segbg.setCornerRadius(float(dp(19)))
            seg.setBackground(segbg)
            cells = []
            def paint():
                for k, (cell, tv) in enumerate(cells):
                    on = (k == ord_st["d"])
                    g = GD()
                    g.setColor(self.c_sel if on else 0)
                    g.setCornerRadius(float(dp(16)))
                    cell.setBackground(g)
                    tv.setTextColor(self.c_accent if on else self.c_sub)
            def pick_order(k):
                if ord_st["d"] == k:
                    return
                ord_st["d"] = k
                paint()
                with tolerated():
                    order_toggle[1](bool(k))
            for k, name in enumerate((strings("ascending"), strings("descending"))):
                cell = LL(act)
                cell.setGravity(17)
                tv = self._text(name, 13, self.c_sub, bold=True, gravity=17, single=True)
                cell.addView(tv, LP(-2, -2))
                cell.setOnClickListener(self.Click(lambda v, kk=k: pick_order(kk)))
                clp = LP(0, -1, 1.0)
                if k:
                    clp.setMargins(dp(2), 0, 0, 0)
                seg.addView(cell, clp)
                cells.append((cell, tv))
            paint()
            seg_lp = LP(-1, dp(38))
            seg_lp.setMargins(dp(16), dp(10), dp(16), 0)
            root.addView(seg, seg_lp)
        body = LL(act)
        body.setOrientation(1)
        body.setPadding(0, dp(12), 0, 0)
        sv = SV(act)
        sv.addView(body)
        root.addView(sv, LP(-1, -2))
        def go(fn):
            def _c(v):
                dlg.dismiss()
                self.handler.postDelayed(self.Run(fn), 80)
            return self.Click(_c)
        chips = list(quick or [])[:4]
        per = len(chips) if len(chips) <= 4 else 3
        for r0 in range(0, len(chips), per or 1):
            grp = chips[r0:r0 + per]
            line = LL(act)
            line.setOrientation(0)
            line.setPadding(dp(10), 0, dp(10), dp(8))
            for q in grp:
                label, cb, destr = q[0], q[1], q[2]
                names = q[3] if len(q) > 3 and q[3] else self._label_names(label)
                active = len(q) > 4 and bool(q[4])
                disabled = len(q) > 5 and bool(q[5])
                tint = red if destr else self.c_accent
                chip = LL(act)
                chip.setOrientation(1)
                chip.setGravity(17)
                chip.setPadding(dp(4), dp(12), dp(4), dp(10))
                cg = GD()
                cg.setCornerRadius(float(dp(14)))
                cg.setColor(_mix(self.c_bg, tint, 0.26 if active else 0.10))
                chip.setBackground(cg)
                if disabled:
                    chip.setAlpha(0.42)
                has_ic = bool(names and self._res(*names))
                if has_ic:
                    chip.addView(self._glyph_icon(names, tint, pad=0), LP(dp(24), dp(24)))
                lab = self._text(label, 12 if has_ic else 14, self.c_text, bold=not has_ic, gravity=17)
                lab.setMaxLines(2)
                lab.setPadding(0, dp(6) if has_ic else 0, 0, 0)
                chip.addView(lab, LP(-2, -2))
                chip.setOnClickListener(go(cb))
                self._press_fx(chip)
                lp = LP(0, -1, 1.0)
                lp.setMargins(dp(4), 0, dp(4), 0)
                line.addView(chip, lp)
            for _ in range(per - len(grp)):
                line.addView(View(act), LP(0, 1, 1.0))
            body.addView(line, LP(-1, -2))
        opts = list(options or [])
        groups, cur = [], []
        for o in opts:
            if o is None:
                if cur:
                    groups.append(cur)
                cur = []
            else:
                cur.append(o)
        if cur:
            groups.append(cur)
        any_icon = any((len(o) > 8 and o[8]) or (self._label_names(o[0]) and self._res(*self._label_names(o[0])))
       for g in groups for o in g)
        for gi, grp in enumerate(groups):
            for oi, o in enumerate(grp):
                nm = self._label_names(o[0])
                label, sub, destructive, cb = o[:4]
                value = o[4] if len(o) > 4 else ""
                getter = o[5] if len(o) > 5 else None
                long_cb = o[6] if len(o) > 6 else None
                disabled = len(o) > 7 and bool(o[7])
                toggle_sw = None
                first, last = (True, True) if cols > 1 else (oi == 0, oi == len(grp) - 1)
                item = LL(act)
                item.setOrientation(0)
                item.setGravity(16)
                item.setMinimumHeight(dp(52))
                item.setPadding(dp(16), dp(8), dp(16), dp(8))
                item.setBackground(self._group_bg(self.c_item, first, last))
                lead = o[8](self, dp(40)) if len(o) > 8 and o[8] else None
                if lead is not None:
                    item.addView(lead, LP(dp(40), dp(40)))
                elif any_icon:
                    tint = red if destructive else self.c_sub
                    rid = self._res(*nm) if nm else 0
                    if rid:
                        item.addView(self._glyph_icon(nm, tint, pad=0), LP(dp(24), dp(24)))
                    elif (str(o[0])).lower().startswith("lock queue"):
                        try:
                            lock_iv = jclass("android.widget.ImageView")(act)
                            lock_iv.setImageResource(int(jclass("android.R$drawable").ic_lock_lock))
                            lock_iv.setColorFilter(tint)
                            item.addView(lock_iv, LP(dp(24), dp(24)))
                        except Exception:
                            item.addView(View(act), LP(dp(24), dp(24)))
                    else:
                        item.addView(View(act), LP(dp(24), dp(24)))
                col = LL(act)
                col.setOrientation(1)
                if any_icon:
                    col.setPadding(dp(16), 0, 0, 0)
                col.addView(self._text(label, 16, red if destructive else self.c_text), LP(-1, -2))
                if sub:
                    col.addView(self._text(sub, 13, self.c_sub), LP(-1, -2))
                item.addView(col, LP(0, -2, 1.0))
                if str(value).lower() in ("radio_on", "radio_off"):
                    with tolerated():
                        rb = jclass("android.widget.RadioButton")(act)
                        chk = str(value).lower() == "radio_on"
                        rb.setChecked(chk)
                        rb.setClickable(False)
                        rb.setFocusable(False)
                        rb.setFocusableInTouchMode(False)
                        rb.setButtonTintList(jclass("android.content.res.ColorStateList").valueOf(
                       self.c_accent if chk else self.c_sub))
                        item.addView(rb, LP(-2, -2))
                elif str(value).lower() in ("on", "off"):
                    with tolerated():
                        sw = jclass("android.widget.Switch")(act)
                        sw.setChecked(str(value).lower() == "on")
                        sw.setClickable(False)
                        sw.setFocusable(False)
                        sw.setFocusableInTouchMode(False)
                        item.addView(sw, LP(-2, -2))
                        toggle_sw = sw
                elif value:
                    vt = self._text(value, 14, self.c_accent, bold=True, gravity=21)
                    vt.setPadding(dp(12), 0, 0, 0)
                    item.addView(vt, LP(-2, -2))
                if disabled:
                    item.setAlpha(0.42)
                elif toggle_sw is not None:
                    item.setOnClickListener(self._toggle_click(cb, toggle_sw, getter))
                else:
                    item.setOnClickListener(go(cb))
                if long_cb is not None:
                    def _held(v, f=long_cb):
                        dlg.dismiss()
                        self.handler.postDelayed(self.Run(f), 80)
                        return True
                    item.setOnLongClickListener(_viewlong_proxy()(_held))
                if not disabled:
                    self._press_fx(item)
                if cols > 1:
                    if oi % cols == 0:
                        line = LL(act)
                        line.setOrientation(0)
                        llp = LP(-1, -2)
                        llp.setMargins(dp(10), dp(10) if (oi == 0 and (gi > 0 or chips)) else dp(4), dp(10), 0)
                        body.addView(line, llp)
                    clp = LP(0, -1, 1.0)
                    clp.setMargins(dp(2), 0, dp(2), 0)
                    line.addView(item, clp)
                    if oi == len(grp) - 1 and oi % cols == 0:
                        line.addView(View(act), LP(0, 1, 1.0))
                    continue
                lp = LP(-1, -2)
                lp.setMargins(dp(12), dp(10) if (first and (gi > 0 or chips)) else dp(2) if not first else 0,
             dp(12), 0)
                body.addView(item, lp)
        def fit_height():
            MS = jclass("android.view.View$MeasureSpec")
            fr = _cls("android.graphics.Rect")()
            act.getWindow().getDecorView().getWindowVisibleDisplayFrame(fr)
            avail = int(fr.height())
            if avail < dp(240):
                avail = int(dm.heightPixels)
            avail = min(avail, int(dm.heightPixels))
            exact, free = MS.makeMeasureSpec(wpx, 1 << 30), MS.makeMeasureSpec(0, 0)
            sv.setVisibility(8)
            root.measure(exact, free)
            fixed = int(root.getMeasuredHeight())
            sv.setVisibility(0)
            body.measure(exact, free)
            room = max(avail - dp(32) - fixed, dp(120))
            if int(body.getMeasuredHeight()) <= room:
                return -2
            root.removeView(sv)
            root.addView(sv, LP(-1, 0, 1.0))
            return fixed + room
        win_h = -2
        if wpx:
            with tolerated():
                win_h = fit_height()
        dlg.setContentView(root)
        dlg.setCanceledOnTouchOutside(True)
        win = dlg.getWindow()
        if win is not None:
            win.setBackgroundDrawable(CD(0))
            win.setLayout(wpx or -1, win_h)
            win.setGravity(80)
        def sd_move(dy):
            root.setTranslationY(max(0.0, float(root.getTranslationY()) + dy))
        def sd_end(vel):
            ty, h = float(root.getTranslationY()), float(root.getHeight())
            if ty > h * 0.35 or (vel > 1200 and ty > 0):
                root.animate().translationY(h).setDuration(160).withEndAction(
             self.Run(lambda: dlg.dismiss())).start()
            else:
                root.animate().translationY(0.0).setDuration(180).start()
        _attach_sheet_drag(
       self, dlg, lambda: [sv], lambda: 0, lambda: True,
       lambda: float(root.getTranslationY()) > 0.5, lambda: None, sd_move, sd_end)
        dlg.show()
        with tolerated():
            win = dlg.getWindow()
            win.setLayout(wpx or -1, win_h)
            win.setGravity(80)


def _jc(name):
    with tolerated():
        c = find_class(name)
        if c is not None:
            return c
    return jclass(name)


_DELEGATE_CLS = None


def _request_delegate(fn):
    global _DELEGATE_CLS
    if _DELEGATE_CLS is None:
        RD = jclass("org.telegram.tgnet.RequestDelegate")
        class Delegate(dynamic_proxy(RD)):
            def __init__(self, f):
                super().__init__()
                self.f = f
            def run(self, response, error):
                self.f(response, error)
        _DELEGATE_CLS = Delegate
    return _DELEGATE_CLS(fn)


class _PlaybackSheet(_ActionSheet):
    def _ed(self):
        return getattr(self.p, "_editor", None)
    def _refresh(self):
        ed = self._ed()
        if ed is not None:
            with tolerated():
                ed._rep_state = None
                ed._mini_update()
    def _eq_open(self):
        from .eq_sheet import _EqualizerSheet
        try:
            _EqualizerSheet(self.p, self.act).show()
        except Exception:
            self.p._bulletin(strings("couldnt_do_that"), error=True)
    def _set_rep(self, k):
        with tolerated():
            self._sc().setRepeatMode(int(k))
    def _set_order(self, k):
        with tolerated():
            if k == 1:
                self.p._enable_shuffle()
            elif k == 2:
                self.p._enable_reverse()
            else:
                self.p._disable_shuffle()
    def show(self):
        act, dp, LP, p = self.act, self.dp, self.LP, self.p
        LL = jclass("android.widget.LinearLayout")
        SV = jclass("android.widget.ScrollView")
        Dialog = jclass("android.app.Dialog")
        GD = jclass("android.graphics.drawable.GradientDrawable")
        CD = jclass("android.graphics.drawable.ColorDrawable")
        View = jclass("android.view.View")
        SeekBar = jclass("android.widget.SeekBar")
        red = self.c_red
        dlg = Dialog(act)
        dlg.requestWindowFeature(1)
        root = LL(act)
        root.setOrientation(1)
        bg = GD()
        bg.setColor(self.c_bg)
        r = float(dp(16))
        bg.setCornerRadii(jarray(jfloat)([r, r, r, r, 0.0, 0.0, 0.0, 0.0]))
        root.setBackground(bg)
        root.setPadding(0, 0, 0, dp(12))
        grab = LL(act)
        grab.setGravity(17)
        gp = View(act)
        gg = GD()
        gg.setColor(_mix(self.c_bg, self.c_sub, 0.5))
        gg.setCornerRadius(float(dp(2)))
        gp.setBackground(gg)
        grab.addView(gp, LP(dp(36), dp(4)))
        root.addView(grab, LP(-1, dp(18)))
        xf = getattr(p, "_xf", None)
        ed = self._ed()
        refreshers = []
        errs = []
        def guard(where, fn, *a, **k):
            from . import crashlog
            crashlog.crumb("playback build: " + str(where))
            try:
                return fn(*a, **k)
            except Exception as e:
                errs.append(f"{where}: {type(e).__name__}: {str(e)[:90]}")
                crashlog.crumb("  failed: " + errs[-1])
                return None
        def sync():
            for fn in refreshers:
                with tolerated():
                    fn()
            self._refresh()
        def summary():
            st = self._pb_state()
            bits = []
            if st["speed"] != 1.0:
                bits.append(f"{st['speed']:g}×")
            if st["pitch"]:
                bits.append(f"{st['pitch']:+d} st")
            if st["rep"]:
                bits.append(strings("repeat_one") if st["rep"] == 2 else strings("repeat_all"))
            if st["shuf"]:
                bits.append(strings("shuffle"))
            if st["rev"]:
                bits.append(strings("reverse"))
            if st["sleep"]:
                bits.append(p.sleep_status())
            return " · ".join(bits) if bits else strings("default_playback")
        head = LL(act)
        head.setOrientation(0)
        head.setGravity(16)
        head.setPadding(dp(20), 0, dp(8), 0)
        titles = LL(act)
        titles.setOrientation(1)
        t = self._text(strings("playback"), 18, self.c_text, bold=True, single=True)
        titles.addView(t, LP(-1, -2))
        sub = self._text(summary(), 13, self.c_sub, single=True)
        sub.setPadding(0, dp(2), 0, 0)
        titles.addView(sub, LP(-1, -2))
        head.addView(titles, LP(0, -2, 1.0))
        reset_btn = [None]
        with tolerated():
            rb = self._glyph_icon(("msg_reset", "msg_retry", "msg_refresh"), self.c_sub, pad=8)
            rb.setContentDescription(strings("reset_playback_settings"))
            rb.setOnClickListener(self.Click(lambda v: do_reset()))
            self._press_fx(rb)
            head.addView(rb, LP(dp(40), dp(40)))
            reset_btn[0] = rb
        root.addView(head, LP(-1, -2))
        refreshers.append(lambda: sub.setText(summary()))
        body = LL(act)
        body.setOrientation(1)
        body.setPadding(0, dp(12), 0, 0)
        sv = SV(act)
        sv.addView(body)
        root.addView(sv, LP(-1, -2))
        def go(fn):
            def _c(v):
                dlg.dismiss()
                self.handler.postDelayed(self.Run(fn), 80)
            return self.Click(_c)
        def order_on(k):
            sh, rv = p._read_order()
            return sh if k == 1 else (rv and not sh)
        def toggle_order(k):
            self._set_order(0 if order_on(k) else k)
        def rep_label():
            m = self._repeat_mode()
            return strings("repeat_one") if m == 2 else strings("repeat_all") if m == 1 else strings("repeat")
        def rep_names():
            m = self._repeat_mode()
            return ("player_new_repeatone",) if m == 2 else ("player_new_repeatall", "player_new_repeat_off")
        tiles = [
       (rep_label, rep_names, lambda: bool(self._repeat_mode()), lambda: self._set_rep((self._repeat_mode() + 1) % 3), None),
       (lambda: strings("shuffle"), lambda: ("player_new_shuffle", "player_shuffle", "msg_shuffle"),
       lambda: bool(order_on(1)), lambda: toggle_order(1), None),
       (lambda: strings("reverse"), lambda: ("player_new_order", "player_reverse"),
       lambda: bool(order_on(2)), lambda: toggle_order(2), None),
       ]
        line = LL(act)
        line.setOrientation(0)
        line.setPadding(dp(10), 0, dp(10), dp(8))
        for lab_fn, names_fn, on_fn, act_fn, glyph in tiles:
            chip = LL(act)
            chip.setOrientation(1)
            chip.setGravity(17)
            chip.setPadding(dp(4), dp(12), dp(4), dp(10))
            holder = LL(act)
            holder.setGravity(17)
            lab = self._text(lab_fn(), 12, self.c_text, gravity=17)
            lab.setMaxLines(2)
            lab.setPadding(0, dp(6), 0, 0)
            chip.addView(holder, LP(dp(24), dp(24)))
            chip.addView(lab, LP(-2, -2))
            def paint(chip=chip, holder=holder, lab=lab, lab_fn=lab_fn, names_fn=names_fn, on_fn=on_fn, glyph=glyph):
                on = bool(on_fn())
                tint = self.c_accent if on else self.c_sub
                cg = GD()
                cg.setCornerRadius(float(dp(14)))
                cg.setColor(_mix(self.c_bg, self.c_accent, 0.26 if on else 0.10))
                chip.setBackground(cg)
                holder.removeAllViews()
                ic = self._glyph_icon(names_fn(), tint, pad=0)
                holder.addView(ic, LP(dp(24), dp(24)))
                lab.setText(lab_fn())
                lab.setTextColor(self.c_accent if on else self.c_text)
            def tap(v, act_fn=act_fn):
                act_fn()
                sync()
            chip.setOnClickListener(self.Click(tap))
            self._press_fx(chip)
            refreshers.append(paint)
            guard("tile", paint)
            lp = LP(0, -1, 1.0)
            lp.setMargins(dp(4), 0, dp(4), 0)
            line.addView(chip, lp)
        body.addView(line, LP(-1, -2))
        def gap_lp(first):
            lp = LP(-1, -2)
            lp.setMargins(dp(12), dp(10) if first else dp(2), dp(12), 0)
            return lp
        def slider_item(title, names, lo, hi, step, getter, fmt, apply, final, presets, first, last):
            item = LL(act)
            item.setOrientation(1)
            item.setPadding(dp(16), dp(10), dp(16), dp(10))
            item.setBackground(self._group_bg(self.c_item, first, last))
            top = LL(act)
            top.setOrientation(0)
            top.setGravity(16)
            top.addView(self._glyph_icon(names, self.c_sub, pad=0), LP(dp(24), dp(24)))
            tt = self._text(title, 16, self.c_text)
            tt.setPadding(dp(16), 0, 0, 0)
            top.addView(tt, LP(0, -2, 1.0))
            val = self._text("", 14, self.c_accent, bold=True, gravity=21)
            top.addView(val, LP(-2, -2))
            item.addView(top, LP(-1, dp(32)))
            n = int(round((hi - lo) / step))
            sb = SeekBar(act)
            sb.setMax(n)
            def s32(c):
                return ((int(c) & 0xFFFFFFFF) ^ 0x80000000) - 0x80000000
            SRC_IN = jclass("android.graphics.PorterDuff$Mode").SRC_IN
            with tolerated():
                layers = sb.getProgressDrawable()
                bgl = layers.findDrawableByLayerId(16908288)
                if bgl is not None:
                    bgl.mutate().setColorFilter(s32(_mix(self.c_item, self.c_sub, 0.35)), SRC_IN)
                fl = layers.findDrawableByLayerId(16908301)
                if fl is not None:
                    fl.mutate().setColorFilter(s32(self.c_accent), SRC_IN)
            with tolerated():
                th = sb.getThumb()
                if th is not None:
                    th.mutate().setColorFilter(s32(self.c_accent), SRC_IN)
            def paint():
                v = getter()
                sb.setProgress(int(round((v - lo) / step)))
                val.setText(fmt(v))
            def on_seek(kind, pr):
                if kind == "change":
                    v = lo + pr * step
                    val.setText(fmt(v))
                    apply(v)
                elif kind == "stop":
                    final()
                    sync()
            sb.setOnSeekBarChangeListener(_seek_proxy()(on_seek))
            sl = LP(-1, dp(36))
            sl.setMargins(-dp(8), dp(2), -dp(8), 0)
            item.addView(sb, sl)
            if presets:
                pl = LL(act)
                pl.setOrientation(0)
                for k, pv in enumerate(presets):
                    c = LL(act)
                    c.setGravity(17)
                    c.addView(self._text(fmt(pv), 12, self.c_accent, bold=True, gravity=17, single=True), LP(-2, -2))
                    cg = GD()
                    cg.setCornerRadius(float(dp(14)))
                    cg.setColor(_mix(self.c_item, self.c_accent, 0.12))
                    c.setBackground(cg)
                    def pick(v, pv=pv):
                        apply(pv)
                        final()
                        sync()
                    c.setOnClickListener(self.Click(pick))
                    self._press_fx(c)
                    lp = LP(0, dp(30), 1.0)
                    if k:
                        lp.setMargins(dp(6), 0, 0, 0)
                    pl.addView(c, lp)
                pll = LP(-1, -2)
                pll.setMargins(0, dp(4), 0, dp(2))
                item.addView(pl, pll)
            refreshers.append(paint)
            paint()
            body.addView(item, gap_lp(first))
            return item
        def get_speed():
            try:
                return round(float(p._pb_settings()[0]), 2)
            except Exception:
                return 1.0
        def set_speed(v):
            p._pb_store(speed=v)
        def get_pitch():
            try:
                return int(p._pb_settings()[1])
            except Exception:
                return 0
        def set_pitch(v):
            p._pb_store(pitch=v)
        apply_pb = (lambda: ed._pb_apply(True)) if ed is not None else (lambda: self._pb_apply(True))
        guard("speed", slider_item, strings("speed"), ("msg_speed", "msg_timer", "msg_stories_timer"), 0.5, 2.0, 0.05, get_speed,
       lambda v: f"{v:g}×", set_speed, apply_pb, self.PB_SPEEDS, True, False)
        pitch_item = guard("pitch", slider_item, strings("pitch"), ("arrows_select", "msg_voice", "msg_music", "player_new_order"), -6, 6, 1, get_pitch,
       lambda v: f"{int(round(v)):+d} st" if round(v) else strings("original"), set_pitch, apply_pb, None, False, False)
        def row(title, subtitle, names, first, last, value_fn=None, tap=None, switch_get=None, destructive=False):
            item = LL(act)
            item.setOrientation(0)
            item.setGravity(16)
            item.setMinimumHeight(dp(52))
            item.setPadding(dp(16), dp(8), dp(16), dp(8))
            item.setBackground(self._group_bg(self.c_item, first, last))
            tint = red if destructive else self.c_sub
            item.addView(self._glyph_icon(names, tint, pad=0), LP(dp(24), dp(24)))
            col = LL(act)
            col.setOrientation(1)
            col.setPadding(dp(16), 0, 0, 0)
            col.addView(self._text(title, 16, red if destructive else self.c_text), LP(-1, -2))
            if subtitle:
                col.addView(self._text(subtitle, 13, self.c_sub), LP(-1, -2))
            item.addView(col, LP(0, -2, 1.0))
            vt = None
            sw = None
            if switch_get is not None:
                sw = jclass("android.widget.Switch")(act)
                sw.setChecked(bool(switch_get()))
                sw.setClickable(False)
                sw.setFocusable(False)
                item.addView(sw, LP(-2, -2))
            elif value_fn is not None:
                vt = self._text(value_fn(), 14, self.c_accent, bold=True, gravity=21)
                vt.setPadding(dp(12), 0, 0, 0)
                item.addView(vt, LP(-2, -2))
            if sw is not None:
                item.setOnClickListener(self._toggle_click(tap, sw, switch_get))
                refreshers.append(lambda: sw.setChecked(bool(switch_get())))
            else:
                item.setOnClickListener(go(tap))
                if vt is not None:
                    refreshers.append(lambda: vt.setText(value_fn()))
            self._press_fx(item)
            body.addView(item, gap_lp(first))
            return item
        def track_only_get():
            return p._pb_track_only()
        def track_only_tap():
            p._pb_set_track_only(not p._pb_track_only())
            apply_pb()
            self._refresh()
        track_row = guard("track_only", row, strings("save_for_this_track_only"), strings("speed_and_pitch_apply_to_this_track_always"),
            ("msg_saved", "msg_fave", "msg_music"), False, True, tap=track_only_tap, switch_get=track_only_get)
        def track_only_visible():
            if p._pb_track_only():
                return True
            cur = p._pb_settings()
            if abs(float(cur[0]) - 1.0) < 0.005 and int(cur[1]) == 0:
                return False
            base = getattr(p, "_pb_base", None)
            if base is not None and base[0] == p._pb_track_id():
                ref = (float(base[1]), int(base[2]))
            else:
                ref = p._pb_global()
            return abs(float(cur[0]) - float(ref[0])) >= 0.005 or int(cur[1]) != int(ref[1])
        def paint_track_only():
            if track_row is None:
                return
            vis = bool(track_only_visible())
            track_row.setVisibility(0 if vis else 8)
            if pitch_item is not None:
                pitch_item.setBackground(self._group_bg(self.c_item, False, not vis))
        refreshers.append(paint_track_only)
        guard("track_only_vis", paint_track_only)
        def xf_val():
            return (f"{xf.sec()} s" if xf is not None and xf.sec() else strings("state_off"))
        rows = [
       (strings("sleep_timer"), strings("pause_playback_after_a_set_time"), ("msg_stories_timer",),
       {"value_fn": lambda: (strings("track_end") if self._pb_state()["sleep"] == "eot" else self._pb_state()["sleep"]) or strings("state_off"), "tap": self._sleep_menu}),
       ]
        if xf is not None:
            rows.append((strings("crossfade"), strings("blend_the_end_of_a_track"), ("msg_blur_linear",),
          {"value_fn": xf_val, "tap": self._crossfade_menu}))
        if getattr(p, "_eq", None) is not None:
            from .eq_sheet import eq_summary
            rows.append((strings("equalizer"), strings("shape_bass_treble_and_tone"),
          ("msg_download_settings", "msg_equalizer", "equalizer", "msg_filter", "msg_customize"),
          {"value_fn": lambda: eq_summary(p), "tap": self._eq_open}))
        rows.append((strings("offline_mode"), strings("skip_tracks_that_arent_downloaded"), ("menu_download_off_24", "msg_download"),
       {"value_fn": lambda: self._offline_label(), "tap": self._offline_menu}))
        for i, (ti, su, nm, kw) in enumerate(rows):
            guard("row " + str(ti), row, ti, su, nm, i == 0, i == len(rows) - 1, **kw)
        def do_reset():
            self._set_rep(0)
            self._set_order(0)
            set_speed(1.0)
            set_pitch(0)
            if xf is not None:
                p.set_setting("crossfade_sec", 0)
            if getattr(p, "_eq", None) is not None:
                p._eq.reset()
            p._offline_set(2)
            if getattr(p, "_sleep_mode", None):
                p.sleep_cancel()
            apply_pb()
            self._refresh()
        def paint_reset():
            if reset_btn[0] is not None:
                reset_btn[0].setVisibility(4 if self._pb_default(self._pb_state()) else 0)
        refreshers.append(paint_reset)
        guard("reset_vis", paint_reset)
        win_h = -2
        dm = act.getResources().getDisplayMetrics()
        wpx = _wide_px(act, 600)
        if wpx:
            try:
                MS = jclass("android.view.View$MeasureSpec")
                fr = _cls("android.graphics.Rect")()
                act.getWindow().getDecorView().getWindowVisibleDisplayFrame(fr)
                avail = int(fr.height())
                if avail < dp(240):
                    avail = int(dm.heightPixels)
                avail = min(avail, int(dm.heightPixels))
                exact, free = MS.makeMeasureSpec(wpx, 1 << 30), MS.makeMeasureSpec(0, 0)
                sv.setVisibility(8)
                root.measure(exact, free)
                fixed = int(root.getMeasuredHeight())
                sv.setVisibility(0)
                body.measure(exact, free)
                room = max(avail - dp(32) - fixed, dp(120))
                if int(body.getMeasuredHeight()) > room:
                    root.removeView(sv)
                    root.addView(sv, LP(-1, 0, 1.0))
                    win_h = fixed + room
            except Exception:
                win_h = -2
        dlg.setContentView(root)
        dlg.setCanceledOnTouchOutside(True)
        win = dlg.getWindow()
        if win is not None:
            win.setBackgroundDrawable(CD(0))
            win.setLayout(wpx or -1, win_h)
            win.setGravity(80)
        def sd_move(dy):
            root.setTranslationY(max(0.0, float(root.getTranslationY()) + dy))
        def sd_end(vel):
            ty, h = float(root.getTranslationY()), float(root.getHeight())
            if ty > h * 0.35 or (vel > 1200 and ty > 0):
                root.animate().translationY(h).setDuration(160).withEndAction(
             self.Run(lambda: dlg.dismiss())).start()
            else:
                root.animate().translationY(0.0).setDuration(180).start()
        _attach_sheet_drag(
       self, dlg, lambda: [sv], lambda: 0, lambda: True,
       lambda: float(root.getTranslationY()) > 0.5, lambda: None, sd_move, sd_end)
        dlg.show()
        with tolerated():
            win = dlg.getWindow()
            win.setLayout(wpx or -1, win_h)
            win.setGravity(80)
        if errs:
            from . import crashlog
            crashlog.crumb("playback sheet: " + errs[0])
