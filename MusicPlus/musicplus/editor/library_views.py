import json
import re
import threading
import time
from ..compat import find_class, jarray, jclass, jint, run_on_ui_thread
from elyx import strings
from ..helpers import _pln
from ..helpers import _http_stream, _http_text
from ..android import _HOLD_MS, _cls, _mix, _viewlong_proxy, _wide_px
from ..safe import tolerated


class _QueueEditorLibraryViews:
    def _lib_key(self, message=None, track=None):
        if track is not None:
            with tolerated():
                return (int(track["i"]), int(track["d"]))
        if message is not None:
            with tolerated():
                return (int(message.getId()), int(message.getDialogId()))
        return None

    def _lib_set_selection_context(self, context):
        if self.lib_sel_context != context:
            self.lib_sel_context = context
            self.lib_sel_mode = False
            self.lib_selected.clear()

    def _lib_reset_selection(self, context=None):
        self.lib_sel_context = context
        self.lib_sel_mode = False
        self.lib_selected = set()
        self._lib_apply_selection()

    def _lib_begin_selection(self, key=None):
        self.lib_sel_mode = True
        if key is not None:
            self.lib_selected.add(key)
        self._lib_apply_selection()

    def _lib_toggle_selection(self, key):
        if not self.lib_sel_mode:
            self.lib_sel_mode = True
        if key in self.lib_selected:
            self.lib_selected.discard(key)
        else:
            self.lib_selected.add(key)
        if not self.lib_selected:
            self.lib_sel_mode = False
        self._lib_apply_selection()

    def _lib_update_playing_icons(self, playing_key=None, paused=True):
        for key, refs in list(self.lib_track_rows.items()):
            drawable = refs.get("play_pp")
            if drawable is None:
                continue
            with tolerated():
                drawable.setPause(bool(key == playing_key and not paused), True)

    def _lib_apply_selection(self, keys=None, update_header=True):
        with tolerated():
            self._lib_sync_back_cb()
        selected_count = len(self.lib_selected)
        target_keys = list(self.lib_track_rows) if keys is None else keys
        for key in target_keys:
            refs = self.lib_track_rows.get(key)
            if refs is None:
                continue
            on = self.lib_sel_mode and key in self.lib_selected
            with tolerated():
                refs["check"].setVisibility(0 if on else 8)
                refs["row"].setBackground(self._group_bg(
             self.c_sel if on else self.c_item, refs["first"], refs["last"],
             inset=(0, 1, 0, 1)))
                refs["row"].setPadding(self.dp(self.ROW_PAD_START), 0, self.dp(4), 0)
                refs["more"].setVisibility(4 if self.lib_sel_mode else 0)
                if refs.get("handle") is not None:
                    refs["handle"].setVisibility(4 if self.lib_sel_mode else 0)
        if not update_header:
            return
        with tolerated():
            if self.lib_detail_title is not None:
                self.lib_detail_title.setText(strings("n_selected", selected_count) if self.lib_sel_mode
             else self.lib_detail_base_title)
            if self.lib_detail_meta is not None:
                meta = (self.lib_detail_base_title if self.lib_sel_mode and selected_count
             else (strings("tap_tracks_to_select") if self.lib_sel_mode
             else self.lib_detail_base_meta))
                self.lib_detail_meta.setText(meta or "")

    def _lib_track_drag(self, pid, source_index, row, state, event):
        action = int(event.getActionMasked())
        if action == 0:
            state["start_y"] = float(event.getRawY())
            with tolerated():
                row.getParent().requestDisallowInterceptTouchEvent(True)
                row.performHapticFeedback(0)
                row.setTranslationZ(float(self.dp(6)))
            return True
        if state.get("start_y") is None:
            return False
        if action == 2:
            row.setTranslationY(float(event.getRawY()) - state["start_y"])
            return True
        if action in (1, 3):
            raw_y = float(event.getRawY())
            with tolerated():
                row.setTranslationY(0.0)
                row.setTranslationZ(0.0)
            state["start_y"] = None
            if action == 3 or self.lib_sel_mode:
                return True
            entries = list(self.lib_track_reorder_rows)
            if len(entries) < 2:
                return True
            centers = []
            for idx, other_row in entries:
                if idx == source_index:
                    continue
                loc = jarray(jint)(2)
                other_row.getLocationOnScreen(loc)
                centers.append(int(loc[1]) + int(other_row.getHeight()) // 2)
            target = sum(1 for center in centers if raw_y > center)
            pl = self.p._lib_pl(pid)
            if pl is None:
                return True
            tracks = pl["tracks"]
            if source_index < 0 or source_index >= len(tracks):
                return True
            item = tracks.pop(source_index)
            target = max(0, min(len(tracks), target))
            tracks.insert(target, item)
            self.p._lib_save()
            sy = int(self.lib_sv.getScrollY())
            self._lib_render()
            self.handler.postDelayed(self.Run(lambda: self.lib_sv.scrollTo(0, sy)), 40)
            return True
        return True

    def _lib_track_row(self, m, t, cb, more_cb, first, last,
    selection_key=None, reorder_pid=None, reorder_index=None, selectable=True):
        gone = m is None
        status = "gone"
        if gone:
            try:
                status = self.p._resolver.state(self._lib_key(track=t))
            except Exception:
                status = "gone"
            if status not in ("loading", "failed"):
                status = "gone"
        title = (t or {}).get("t", strings("audio")) if gone else self._title_of(m)
        if gone:
            author = {"loading": strings("loading_song"),
          "failed": strings("couldnt_load_tap_to_retry")}.get(
          status, strings("unavailable_deleted_or_too_old_to"))
        else:
            author = self._author_of(m)
        base = self._track_row_base(
       m, first, last, title, author,
       author_color=(self.c_accent if status == "failed" else self.c_sub) if gone else self.c_accent,
       )
        row, lead, art, scrim = (base[k] for k in ("row", "lead", "art", "scrim"))
        play_iv = play_pp = None
        if not gone:
            play_iv, play_pp = self._track_play_icon(lead, m)
            if art is not None:
                self.lib_covers.append({
             "art": art, "m": m, "scrim": scrim, "glyph": None,
             "row": row, "done": False,
             })
        check = None
        dl = None
        if not gone:
            ov = self._track_overlays(lead, pad=8, size=20)
            check = ov["check"]
            dl = {"badge": ov["badge"], "arrow": ov["arrow"], "spin": ov["spin"],
          "state": -1, "m": m, "row": row, "info": base["info"], "lead": lead}
            self._apply_dl(dl, self._dl_state(m))
            self._lib_dim_offline(dl)
        else:
            check = _cls("android.widget.FrameLayout")(self.act)
            check.setVisibility(8)
            with tolerated():
                if status == "loading":
                    pb = _cls("android.widget.ProgressBar")(self.act)
                    with tolerated():
                        pb.setIndeterminateTintList(_cls("android.content.res.ColorStateList").valueOf(-1))
                    pb.setPadding(self.dp(10), self.dp(10), self.dp(10), self.dp(10))
                    lead.addView(pb, base["FLP"](-1, -1))
                elif status == "failed":
                    lead.addView(self._glyph_icon(("msg_retry", "ic_refresh", "msg_reset"), -1,
                pad=10, size=22, bold=True), base["FLP"](-1, -1))
        handle = None
        if reorder_pid is not None and reorder_index is not None:
            handle = self._drag_handle(strings("drag_to_reorder_track"))
            state = {"start_y": None}
            handle.setOnTouchListener(self._hold_drag(
          lambda v, e, pid=reorder_pid, idx=reorder_index, rr=row, st=state:
          self._lib_track_drag(pid, idx, rr, st, e)))
            row.addView(handle, self.LP(self.dp(30), -1))
            self.lib_track_reorder_rows.append((reorder_index, row))
        more = self._glyph_icon(("ic_ab_other", "msg_more", "ic_more_vert"), self.c_sub, bold=True)
        more.setContentDescription(strings("track_actions"))
        more.setOnClickListener(self.Click(lambda v: more_cb()))
        row.addView(more, self.LP(self.dp(40), -1))
        if gone and status == "gone":
            base["info"].setAlpha(0.55)
            lead.setAlpha(0.4)
        elif gone and status == "loading":
            base["info"].setAlpha(0.75)
        key = selection_key if selection_key is not None else self._lib_key(m, t)
        if key is not None:
            self.lib_track_rows[key] = {"row": row, "check": check, "more": more,
          "handle": handle, "play_iv": play_iv, "play_pp": play_pp, "liked": base.get("liked"),
          "first": first, "last": last, "dl": dl}
            if selectable:
                row.setOnLongClickListener(_viewlong_proxy()(
             lambda v, k=key: (self._lib_begin_selection(k), True)[1]))
        def click_row(v):
            if selectable and key is not None and self.lib_sel_mode:
                self._lib_toggle_selection(key)
            elif not gone and self._lib_pause_if_playing(m):
                return
            else:
                cb()
        row.setOnClickListener(self.Click(click_row))
        self._lib_add_row(row, first)
        return key

    def _lib_pause_if_playing(self, m):
        try:
            mc, pm = self._mini_playing()
            if mc is None or pm is None or self._key(pm) != self._key(m):
                return False
            if bool(mc.isMessagePaused()):
                return False
            mc.pauseMessage(pm)
            self._mini_update()
            self._nudge_update()
            return True
        except Exception:
            return False

    def _lib_render_track_rows(self, count, row_at, playlist_id=None, tail=None):
        shown = min(count, self.PAGE_ROWS)
        self.lib_track_loader = {"count": count, "row_at": row_at, "rendered": 0,
       "context": self.lib_state, "playlist_id": playlist_id,
       "busy": False, "tail": tail, "tail_done": False}
        self._lib_append_track_rows(shown)

    def _lib_append_track_rows(self, target):
        loader = self.lib_track_loader
        if not loader or loader["context"] != self.lib_state:
            return
        count = loader["count"]
        end = min(count, max(loader["rendered"], int(target)))
        if end <= loader["rendered"]:
            return
        start = loader["rendered"]
        added_keys = []
        for i in range(start, end):
            m, track, on_click, on_more = loader["row_at"](i)
            key = self._lib_track_row(
          m, track, on_click, on_more, i == 0, i == count - 1,
          selection_key=self._lib_key(m, track),
          reorder_pid=loader["playlist_id"], reorder_index=i if loader["playlist_id"] else None)
            if key is not None:
                added_keys.append(key)
                loader.setdefault("rows", []).append(key)
        loader["rendered"] = end
        loader["busy"] = False
        self._lib_sync_last_corners()
        self._lib_apply_selection(added_keys, update_header=False)
        if end >= count and loader.get("tail") and not loader.get("tail_done"):
            loader["tail_done"] = True
            with tolerated():
                loader["tail"]()
        self.handler.postDelayed(self.Run(self._lib_load_covers), 30)

    def _lib_sync_last_corners(self):
        loader = self.lib_track_loader
        if not loader:
            return
        keys = loader.get("rows") or []
        if not keys:
            return
        done = loader["rendered"] >= loader["count"]
        want_key = keys[-1] if done else None
        cands = {keys[-1], loader.get("last_key")}
        if len(keys) > 1:
            cands.add(keys[-2])
        changed = []
        for key in cands:
            if key is None:
                continue
            refs = self.lib_track_rows.get(key)
            if refs is None:
                continue
            want = key == want_key
            if bool(refs.get("last")) != want:
                refs["last"] = want
                changed.append(key)
        loader["last_key"] = want_key
        if changed:
            self._lib_apply_selection(changed, update_header=False)

    def _lib_maybe_load_more(self):
        loader = self.lib_track_loader
        if not loader or loader["busy"] or loader["context"] != self.lib_state:
            return
        if loader["rendered"] >= loader["count"]:
            return
        with tolerated():
            sy = int(self.lib_sv.getScrollY())
            vh = int(self.lib_sv.getHeight())
            content_h = int(self.lib_box.getHeight())
            if vh <= 0:
                return
            if sy + vh + self.H * 2 >= content_h:
                loader["busy"] = True
                next_target = loader["rendered"] + self.PAGE_ROWS
                expected_loader = loader
                def append_next():
                    if self.lib_track_loader is expected_loader:
                        self._lib_append_track_rows(next_target)
                self.handler.postDelayed(self.Run(append_next), 16)

    def _lib_cancel_selected(self):
        _, messages, _pl = self._lib_selected_rows()
        self.p._cancel_downloads(messages)

    def _lib_selected_rows(self):
        context = self.lib_sel_context
        selected = set(self.lib_selected)
        if not selected:
            return [], [], None
        if context and context[0] == "pl":
            pl = self.p._lib_pl(context[1])
            if pl is None:
                return [], [], None
            tracks = [t for t in pl["tracks"] if self._lib_key(track=t) in selected]
            messages = [m for m in self._lib_known(tracks, refresh=True) if m is not None]
            return tracks, messages, pl
        if context and context[0] == "chat":
            msgs = list(self.p._chat_track_cache.get(tuple(context[1]), []) or [])
            selected_msgs = [m for m in msgs if self._lib_key(m) in selected]
            return selected_msgs, selected_msgs, None
        if context and context[0] == "artist":
            selected_msgs = [m for m in self._lib_artist_msgs(context[1]) if self._lib_key(m) in selected]
            return selected_msgs, selected_msgs, None
        return [], [], None

    def _lib_scope(self, state):
        sc = self.__dict__.get("lib_scope")
        return sc if sc and sc["state"] == state else None

    def _lib_all_track_keys(self):
        context = self.lib_sel_context
        sc = self._lib_scope(tuple(context)) if context and context[0] in ("chat", "artist") else None
        if sc is not None:
            return {self._lib_key(m) for m in sc["shown"] if m is not None}
        if context and context[0] == "pl":
            pl = self.p._lib_pl(context[1])
            return {self._lib_key(track=t) for t in (pl["tracks"] if pl else [])}
        if context and context[0] == "chat":
            msgs = self.p._chat_track_cache.get(tuple(context[1]), []) or []
            rows = getattr(msgs, "rows", None)
            if rows is not None:
                return {(int(r["i"]), int(r["d"])) for r in rows}
            return {self._lib_key(m) for m in msgs}
        if context and context[0] == "artist":
            return {self._lib_key(m) for m in self._lib_artist_msgs(context[1])}
        return set()

    def _lib_selection_menu(self):
        context = self.lib_sel_context
        selected_count = len(self.lib_selected)
        title = strings("n_selected", selected_count) if selected_count else strings("select_tracks")
        all_keys = self._lib_all_track_keys()
        all_selected = bool(all_keys) and self.lib_selected >= all_keys
        hero = [(strings("play_next"), self._lib_play_selected_next, False),
       (strings("add_to"), self._lib_add_selected_to, False, ("msg_add",))]
        if context and context[0] == "pl":
            hero.append((strings("remove"), self._lib_remove_selected_tracks, True))
        if context and context[0] == "chat":
            hero.append((strings("open_chat"), lambda: self.p._open_chat_scope(
          context[1][0], context[1][1]), False, ("msg_openin", "msg_profile")))
        self.p._selection_sheet(
       self.act, title, strings("library_track_selection"), hero,
       None if all_selected else (strings("select_all"), "", False, self._lib_select_all),
       self._lib_forward_selected, self._lib_save_selected,
       done=(strings("clear_selection"), "", False, self._lib_exit_selection),
       download=self._lib_download_selected, count=selected_count,
       items=lambda: self._lib_selected_rows()[1], cancel=self._lib_cancel_selected)

    def _lib_select_all(self):
        self.lib_sel_mode = True
        keys = self._lib_all_track_keys()
        if keys and self.lib_selected >= keys:
            self.lib_selected.clear()
        else:
            self.lib_selected = set(keys)
        self._lib_apply_selection()

    def _lib_exit_selection(self):
        self._lib_reset_selection(self.lib_sel_context)

    def _lib_play_selected_next(self):
        tracks, messages, pl = self._lib_selected_rows()
        if not tracks:
            self.p._bulletin(strings("select_at_least_one_track"), error=True)
            return
        context = self.lib_sel_context
        if context and context[0] == "pl":
            self.p._lib_play(self.act, tracks, "next", name=pl["name"] if pl else strings("playlist"))
        else:
            chat = next((c for c in self.p._lib_data()["chats"]
          if (int(c["d"]), int(c["t"])) == tuple(context[1])), None)
            self.p._lib_play_msgs(messages, "next", name=chat["n"] if chat else strings("chat"))
        self._lib_reset_selection(context)

    def _lib_add_selected_to(self):
        tracks, messages, pl = self._lib_selected_rows()
        if not tracks:
            self.p._bulletin(strings("select_at_least_one_track"), error=True)
            return
        context = self.lib_sel_context
        selected_items = tracks if context and context[0] == "pl" else messages
        default = pl["name"] if pl else strings("tracks")
        exclude = pl["id"] if pl else None
        self._lib_reset_selection(context)
        self.p._lib_add_to_sheet(self.act, lambda cb: cb(selected_items), default,
       strings("n_selected", len(selected_items)), exclude=exclude)

    def _lib_forward_selected(self):
        _, messages, _pl = self._lib_selected_rows()
        if not messages:
            self.p._bulletin(strings("no_available_tracks_to_forward"), error=True)
            return
        if len(messages) > 100:
            self.p._bulletin(strings("forward_up_to_100_tracks_at"), error=True)
            return
        self._lib_reset_selection(self.lib_sel_context)
        self._after_close(lambda: self.p._pick_forward(messages))

    def _lib_download_selected(self):
        _, messages, _pl = self._lib_selected_rows()
        if not messages:
            self.p._bulletin(strings("no_available_tracks_to_download"), error=True)
            return
        if len(messages) > 100:
            self.p._bulletin(strings("download_up_to_100_tracks_at"), error=True)
            return
        self.p._download_tracks(messages)

    def _lib_select_all_menu(self):
        self.lib_sel_mode = True
        self.lib_selected = set(self._lib_all_track_keys())
        self._lib_apply_selection()
        self._lib_selection_menu()

    def _lib_save_selected(self):
        _, messages, _pl = self._lib_selected_rows()
        if not messages:
            self.p._bulletin(strings("no_available_tracks_to_save"), error=True)
            return
        if len(messages) > 100:
            self.p._bulletin(strings("save_up_to_100_tracks_at"), error=True)
            return
        self._lib_reset_selection(self.lib_sel_context)
        self.p._save_to_music(messages)

    def _lib_remove_selected_tracks(self):
        context = self.lib_sel_context
        if not context or context[0] != "pl":
            return
        pl = self.p._lib_pl(context[1])
        if pl is None:
            return
        selected = set(self.lib_selected)
        before = len(pl["tracks"])
        pl["tracks"] = [t for t in pl["tracks"] if self._lib_key(track=t) not in selected]
        removed = before - len(pl["tracks"])
        self.p._lib_save()
        self._lib_reset_selection(context)
        self._lib_render()
        self.p._bulletin(strings("removed_n_tracks", removed))

    def _lib_has_cover(self, message):
        with tolerated():
            doc = message.getDocument()
            if doc is not None and self._best_thumb(doc, bool(self.p.get_setting("hq_thumbs", True))) is not None:
                return True
        for small in (True, False):
            with tolerated():
                url = message.getArtworkUrl(small)
                if url and str(url).strip():
                    return True
        return False

    def _lib_playlist_cover_messages(self, tracks):
        found = []
        saved_tracks = (tracks or [])[:96]
        for message in self._lib_known(saved_tracks):
            if message is not None and self._lib_has_cover(message):
                found.append(message)
                if len(found) == 4:
                    break
        with tolerated():
            memo = self.p.__dict__.setdefault("_lib_cover_memo", {})
            sig = tuple((int(t["i"]), int(t["d"])) for t in saved_tracks[:24])
            old = memo.get(sig)
            if old is not None and len(old) >= len(found):
                return list(old)
            if found:
                if len(memo) > 200:
                    memo.clear()
                memo[sig] = list(found)
        return found

    def _lib_playlist_card(self, title, subtitle, callback, grid_row, playlist=None,
    cover_messages=None):
        LL = jclass("android.widget.LinearLayout")
        FL = _cls("android.widget.FrameLayout")
        FLP = _cls("android.widget.FrameLayout$LayoutParams")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        card = LL(self.act)
        card.setOrientation(1)
        card.setGravity(1)
        card.setPadding(self.dp(4), self.dp(10), self.dp(4), self.dp(8))
        cover_size = self._lib_grid_size()
        icon = self._lib_pl_icon(playlist) if playlist else None
        def build():
            if icon:
                return self._lib_tile_b(None, cover_size, None, None, icon)
            cover_host = FL(self.act)
            cover_grid = LL(self.act)
            cover_grid.setOrientation(1)
            cover_grid.setBackgroundColor(_mix(self.c_item, self.c_sub, 0.08))
            for r in range(2):
                line = LL(self.act)
                line.setOrientation(0)
                line.setGravity(16)
                for c in range(2):
                    index = r * 2 + c
                    cell = FL(self.act)
                    cell_bg = GD()
                    cell_bg.setColor(_mix(self.c_item, self.c_sub, 0.10))
                    cell_bg.setCornerRadius(float(self.dp(4)))
                    cell.setBackground(cell_bg)
                    message = cover_messages[index] if cover_messages and index < len(cover_messages) else None
                    if message is not None:
                        try:
                            art = find_class("org.telegram.ui.Components.BackupImageView")(self.act)
                            art.setRoundRadius(self.dp(4))
                            cell.addView(art, FLP(-1, -1))
                            self.lib_covers.append({"art": art, "m": message, "scrim": None,
                       "glyph": None, "row": grid_row, "done": False})
                        except Exception:
                            cell.addView(self._glyph_icon(("files_music", "msg_filled_data_music", "msg_music", "msg_media"), self.c_sub, pad=6, size=12), FLP(-1, -1))
                    else:
                        cell.addView(self._glyph_icon(("files_music", "msg_filled_data_music", "msg_music", "msg_media"), self.c_sub, pad=6, size=12), FLP(-1, -1))
                    cell_lp = self.LP(0, -1, 1.0)
                    cell_lp.setMargins(self.dp(1), self.dp(1), self.dp(1), self.dp(1))
                    line.addView(cell, cell_lp)
                cover_grid.addView(line, self.LP(-1, 0, 1.0))
            cover_host.addView(cover_grid, FLP(-1, -1))
            return cover_host
        ks = tuple(self.p._msg_key(m) for m in (cover_messages or []))
        key = (("i", icon, cover_size, self._lib_cvsig()) if icon
               else ("c", ks, cover_size, self._lib_cvsig()) if None not in ks else None)
        card.addView(self._lib_cv_cache(key, grid_row, build), self.LP(cover_size, cover_size))
        fs = {2: 15, 3: 14, 4: 12}.get(self._lib_cols(), 11)
        title_tv = self._text(title, fs, self.c_text, bold=True, single=True, gravity=17)
        title_tv.setPadding(0, self.dp(8), 0, 0)
        card.addView(title_tv, self.LP(-1, -2))
        if subtitle:
            card.addView(self._text(subtitle, max(9, fs - 2), self.c_sub,
          single=True, gravity=17), self.LP(-1, -2))
        card.setContentDescription((strings("playlist") + ": ") + str(title))
        card.setOnClickListener(self.Click(lambda v: callback()))
        if playlist is not None:
            self._lib_bind_grid_drag(card, "playlists", playlist["id"],
          lambda pid=playlist["id"]: self._lib_playlist_menu(pid))
        lp = self.LP(0, -2, 1.0)
        lp.setMargins(self.dp(3), self.dp(3), self.dp(3), self.dp(3))
        grid_row.addView(card, lp)
        return card

    def _lib_cols(self):
        try:
            wide = 2 if _wide_px(self.act, 600) else 0
            return max(2, min(5 + wide, 2 + wide + int(self.p.get_setting("lib_grid_columns", 2))))
        except Exception:
            return 4

    def _lib_grid_size(self):
        try:
            w = _wide_px(self.act, 840) or int(self.act.getResources().getDisplayMetrics().widthPixels)
            return max(self.dp(42), min(self.dp(120), int((w - self.dp(96)) / float(self._lib_cols()))))
        except Exception:
            return self.dp(58)

    def _lib_grid(self, entries, build):
        LL = jclass("android.widget.LinearLayout")
        View = _cls("android.view.View")
        per_row = self._lib_cols()
        for start in range(0, len(entries), per_row):
            grid_row = LL(self.act)
            grid_row.setOrientation(0)
            grid_row.setGravity(16)
            chunk = entries[start:start + per_row]
            for item in chunk:
                build(item, grid_row)
            for _ in range(per_row - len(chunk)):
                grid_row.addView(View(self.act), self.LP(0, 1, 1.0))
            self._lib_add_row(grid_row, start == 0)

    def _lib_view(self, kind):
        return self.p._lib_data().get("views", {}).get(kind, self.VIEW_DEFAULTS.get(kind, "list"))

    def _lib_toggle_view(self, kind):
        views = self.p._lib_data().setdefault("views", {})
        views[kind] = "list" if self._lib_view(kind) == "grid" else "grid"
        self.p._lib_save()
        self._lib_render()

    def _lib_section(self, kind, title, items, as_row, as_card, sort=None,
    sort_desc=strings("sort"), extra=None):
        grid = self._lib_view(kind) == "grid"
        switch = (strings("list") if grid else strings("grid"), lambda: self._lib_toggle_view(kind),
       strings("show_as") + ("list" if grid else "grid"))
        self._lib_label(title, action=sort, action_description=sort_desc,
       extra=list(extra or []) + [switch])
        if grid:
            self._lib_grid(items, as_card)
        else:
            for i, item in enumerate(items):
                as_row(item, i == 0, i == len(items) - 1)

    def _lib_bind_grid_drag(self, view, group, item_id, menu_cb=None):
        self.lib_reorder_rows.setdefault(group, []).append((view, item_id))
        self._lib_hold_bind(view, menu_cb, group, item_id)

    def _lib_hold_bind(self, view, menu_cb, group=None, item_id=None):
        state = {
       "down_x": None, "down_y": None, "active": False, "lift": None,
       "armed": False, "fired": False, "timers": [],
       "drag": {"start_y": None, "start_x": None, "ty": {}},
       }
        slop = float(self.dp(8))
        def cancel():
            for r in state["timers"]:
                with tolerated():
                    self.handler.removeCallbacks(r)
            state["timers"] = []
        def finish():
            cancel()
            state["active"] = False
            state["armed"] = False
            state["down_x"] = None
            state["down_y"] = None
            if group is not None:
                self.sheet_lock = False
            lf = state["lift"]
            if lf is not None:
                state["lift"] = None
                with tolerated():
                    lf[0].setClipChildren(True)
                    lf[1].setClipChildren(True)
                    lf[0].setTranslationZ(0.0)
        def arm():
            if state["down_y"] is not None:
                state["armed"] = True
                with tolerated():
                    view.getParent().requestDisallowInterceptTouchEvent(True)
        def fire():
            if state["down_y"] is None or state["active"] or menu_cb is None:
                return
            state["fired"] = True
            finish()
            with tolerated():
                view.performHapticFeedback(0)
                view.setPressed(False)
            menu_cb()
        def start_drag():
            if group is None or len(self.lib_reorder_rows.get(group, [])) < 2:
                return False
            drag_state = state["drag"]
            drag_state["start_y"] = state["down_y"]
            drag_state["start_x"] = state["down_x"]
            drag_state["ty"] = {}
            state["active"] = True
            with tolerated():
                parent = view.getParent()
                if parent is not None:
                    parent.requestDisallowInterceptTouchEvent(True)
                    box = parent.getParent()
                    parent.setClipChildren(False)
                    box.setClipChildren(False)
                    parent.setTranslationZ(float(self.dp(12)))
                    state["lift"] = (parent, box)
                view.performHapticFeedback(0)
                view.setTranslationZ(float(self.dp(6)))
            return True
        def touch(v, event):
            action = int(event.getActionMasked())
            if action == 0:
                cancel()
                state["down_x"] = float(event.getRawX())
                state["down_y"] = float(event.getRawY())
                state["active"] = False
                state["armed"] = False
                state["fired"] = False
                if group is not None:
                    self.sheet_lock = True
                state["drag"]["start_x"] = None
                state["drag"]["start_y"] = None
                state["drag"]["ty"] = {}
                runs = []
                if group is not None:
                    runs.append((self.Run(arm), 250))
                if menu_cb is not None:
                    runs.append((self.Run(fire), _HOLD_MS))
                state["timers"] = [r for r, _d in runs]
                for r, d in runs:
                    self.handler.postDelayed(r, d)
                return False
            if state["fired"]:
                if action in (1, 3):
                    state["fired"] = False
                return True
            if state["active"]:
                handled = self._lib_reorder_touch(
             group, item_id, view, state["drag"], event, grid=True)
                if action in (1, 3):
                    finish()
                return handled
            if action == 2 and state["down_y"] is not None and (
          abs(float(event.getRawX()) - state["down_x"]) > slop
          or abs(float(event.getRawY()) - state["down_y"]) > slop):
                armed = state["armed"]
                cancel()
                if armed and start_drag():
                    return self._lib_reorder_touch(
                group, item_id, view, state["drag"], event, grid=True)
                return False
            if action in (1, 3):
                finish()
            return False
        with tolerated():
            view.setOnTouchListener(self.Touch(touch))

    def _lib_round_card(self, grid_row, make_photo, title, sub, callback, label,
    reorder_type=None, reorder_id=None, long_cb=None, menu_cb=None):
        LL = jclass("android.widget.LinearLayout")
        size = self._lib_grid_size()
        fs = {2: 15, 3: 14, 4: 12}.get(self._lib_cols(), 11)
        card = LL(self.act)
        card.setOrientation(1)
        card.setGravity(1)
        card.setPadding(self.dp(4), self.dp(10), self.dp(4), self.dp(8))
        card.addView(make_photo(size), self.LP(size, size))
        name = self._text(title, fs, self.c_text, bold=True, single=True, gravity=17)
        name.setPadding(0, self.dp(8), 0, 0)
        card.addView(name, self.LP(-1, -2))
        if sub:
            card.addView(self._text(sub, max(9, fs - 2), self.c_sub, single=True, gravity=17), self.LP(-1, -2))
        card.setContentDescription(label + str(title))
        card.setOnClickListener(self.Click(lambda v: callback()))
        if reorder_type is not None and reorder_id is not None:
            self._lib_bind_grid_drag(card, reorder_type, reorder_id, menu_cb)
        elif long_cb is not None:
            self._lib_hold_bind(card, long_cb)
        lp = self.LP(0, -2, 1.0)
        lp.setMargins(self.dp(3), self.dp(3), self.dp(3), self.dp(3))
        grid_row.addView(card, lp)

    def _lib_playlist_entry_card(self, pl, grid_row, _unused=None):
        self._lib_playlist_card(
       _pln(pl["name"]), self._lib_tracks_meta(len(pl.get("tracks", [])),
       self.p._lib_minutes(pl.get("tracks", []))),
       lambda pid=pl["id"]: self._lib_go("pl", pid), grid_row,
       playlist=pl,
       cover_messages=self._lib_playlist_cover_messages(pl.get("tracks", [])))

    def _lib_sort_sheet(self, title, subtitle, modes, apply, desc=False, extra=None, current=None):
        from ..sheets import _ActionSheet
        order = {"desc": bool(desc)}
        def on_toggle(d):
            order.update(desc=bool(d))
        options = [(label, sub, False, (lambda m=mode: apply(m, order["desc"])))
       for mode, label, sub in modes] + list(extra or [])
        _ActionSheet(self.p, self.act).show_sheet(
       title, subtitle, options,
       order_toggle=(order["desc"], on_toggle))

    def _lib_playlist_list_sort_menu(self):
        self._lib_sort_sheet(
       strings("sort_playlists"), strings("n_playlists", len(self.p._lib_data().get('playlists', []))),
       [("created", strings("creation_date"), strings("when_the_playlist_was_made")),
       ("count", strings("track_count"), strings("number_of_tracks")),
       ("last_played", strings("last_played"), strings("when_it_was_last_played"))],
       self._lib_sort_playlists,
       desc=bool((self.p._lib_data().get("pl_sort") or [None, True])[1]),
       current=lambda: (self.p._lib_data().get("pl_sort") or [None])[0])

    def _lib_sort_playlists(self, mode, desc=True):
        playlists = self.p._lib_data().get("playlists", [])
        def created(pl):
            value = pl.get("created")
            if value is not None:
                with tolerated():
                    return int(value)
            raw = str(pl.get("id", ""))
            try:
                return int(raw[1:14]) // 1000 if raw.startswith("p") else 0
            except Exception:
                return 0
        keys = {"created": created,
       "count": lambda pl: len(pl.get("tracks", [])),
       "last_played": lambda pl: int(pl.get("last_played", 0) or 0)}
        if mode not in keys:
            return
        d = self.p._lib_data()
        snap = (list(playlists), d.get("last"), d.get("pl_sort"))
        playlists.sort(key=keys[mode], reverse=bool(desc))
        d["pl_sort"] = [mode, bool(desc)]
        self.p._lib_save()
        self._lib_render()
        self._lib_undo_list("playlists", snap, strings("list_sorted"), strings("sort_undone"))

    def _lib_excluded_artists(self):
        try:
            raw = self.p.get_setting("excluded_artists", "[]")
            values = json.loads(raw) if isinstance(raw, str) else raw
            return set(str(x).casefold() for x in values or [])
        except Exception:
            return set()

    def _lib_exclude_artist(self, key, name):
        try:
            excluded = self._lib_excluded_artists()
            excluded.add(str(key).casefold())
            self.p.set_setting("excluded_artists", json.dumps(sorted(excluded)))
            self._lib_go("home")
            self.p._bulletin(
          strings("removed_from_library_change_this_later"))
        except Exception:
            self.p._bulletin(strings("couldnt_remove_artist_from_library"), error=True)

    def _lib_artist_data(self):
        return self.p._lib_data().setdefault(
       "artists", {"list": [], "scanned": 0, "sort": "count", "desc": True})

    def _lib_artist_min(self):
        try:
            return self.ARTIST_MINS[int(self.p.get_setting("artist_min_tracks", 1))]
        except Exception:
            return 2

    def _lib_artist_sync(self, key):
        p = self.p
        a = next((x for x in self._lib_artist_data()["list"] if x["k"] == key), None)
        if a is None or self.__dict__.get("_artist_syncing"):
            return
        with tolerated():
            a["nf"] = {}
            p.__dict__.setdefault("_album_tried", {}).pop(a["k"], None)
            p.__dict__.setdefault("_album_busy", set()).discard(a["k"])
            p._lib_save()
        p.__dict__.setdefault("_artist_tried", set()).clear()
        todo = [k for k in ((int(c["d"]), int(c["t"])) for c in p._lib_data()["chats"]) if k not in p._chat_track_cache]
        self._artist_syncing = True
        def finish():
            self._artist_syncing = False
            p._artist_dirty = True
            with tolerated():
                if self.lib_state == ("artist", key):
                    self._lib_render()
        if not todo:
            finish()
            return
        total, left = len(todo), list(todo)
        def per_chat(_m):
            with tolerated():
                self._sync_pct_set(min(99, int(100 * (total - len(left)) / total)))
        def tick(_m):
            if left:
                left.pop(0)
            per_chat(_m)
        self._lib_each_chat(todo, tick, finish)

    def _lib_each_chat(self, keys, per_chat, done):
        keys = list(keys)
        total, p, pkey = len(keys), self.p, ("each", id(keys))
        def step():
            if not keys:
                p._prog_end(pkey)
                done()
                return
            p._prog_set(pkey, total - len(keys), total)
            key = keys.pop(0)
            self._lib_fetch_chat_tracks(key, self.act, lambda msgs: (per_chat(msgs), step()))
        step()

    def _lib_artist_auto(self):
        p = self.p
        if not p._lib_data()["chats"]:
            return
        old = self.__dict__.get("_artist_auto_run")
        if old is not None:
            with tolerated():
                self.handler.removeCallbacks(old)
        def go():
            self._artist_auto_run = None
            if not self.__dict__.get("_artist_scanning"):
                self._lib_artist_rescan()
        self._artist_auto_run = self.Run(go)
        self.handler.postDelayed(self._artist_auto_run, 4000)

    def _lib_artist_rescan(self):
        from ..editor import _QueueEditor
        p = self.p
        keys = [(int(c["d"]), int(c["t"])) for c in p._lib_data()["chats"]]
        if not keys or self.__dict__.get("_artist_scanning"):
            return
        self._artist_scanning = True
        p._artist_dirty = False
        token = self._artist_tok = getattr(self, "_artist_tok", 0) + 1
        p.__dict__.setdefault("_artist_tried", set()).clear()
        counts, seen = {}, set()
        ad0 = self._lib_artist_data()
        last = dict(ad0.get("last") or {})
        incremental = bool(ad0.get("scanned")) and bool(last)
        newlast = dict(last)
        order = list(keys)
        def tally(msgs):
            ck = "%d:%d" % order.pop(0) if order else "?"
            floor = int(last.get(ck, 0)) if incremental else 0
            top = floor
            rows = getattr(msgs, "rows", None)
            pairs = []
            if rows is not None:
                for r in rows:
                    try:
                        mid = int(r.get("i", 0) or 0)
                    except Exception:
                        mid = 0
                    top = max(top, mid)
                    if mid > floor:
                        pairs.append((r.get("a") or "", r.get("t") or ""))
            else:
                for m in msgs or []:
                    try:
                        mid = int(m.getId())
                    except Exception:
                        mid = 0
                    top = max(top, mid)
                    if mid > floor:
                        pairs.append((_QueueEditor._author_of(m) or "", _QueueEditor._title_of(m)))
            if top:
                newlast[ck] = top
            for author, title in pairs:
                name = author.strip()
                if not name:
                    continue
                k = name.casefold()
                tk = (k, title.casefold())
                if tk in seen:
                    continue
                seen.add(tk)
                counts[k] = (counts[k][0] if k in counts else name, (counts[k][1] if k in counts else 0) + 1)
        def finish():
            if token != self._artist_tok:
                self._artist_scanning = False
                return
            self._artist_scanning = False
            ad = self._lib_artist_data()
            old = {a["k"]: a for a in ad["list"]}
            if incremental:
                for k, a in old.items():
                    c0 = 0 if a.get("q") else int(a.get("c", 0))
                    if k in counts:
                        counts[k] = (a.get("n") or counts[k][0], counts[k][1] + c0)
                    elif not a.get("q"):
                        counts[k] = (a.get("n"), c0)
            ad["last"] = newlast
            ad["list"] = [dict({"k": k, "n": v[0], "c": v[1]},
          **({"u": old[k]["u"]} if k in old and old[k].get("u") else {}),
          **({f: old[k][f] for f in ("al", "alv", "am", "tn", "nf") if old[k].get(f) is not None}
          if k in old and old[k].get("al") else {}))
          for k, v in counts.items()]
            ad["list"] += [a for k, a in old.items() if a.get("q") and k not in counts]
            ad["scanned"] = int(time.time())
            p._lib_save()
            if self.lib_state == ("home", None) or self.lib_state[0] == "artist":
                self._lib_render()
        self._lib_each_chat(keys, lambda m: token == self._artist_tok and tally(m), finish)

    def _lib_artist_sort_menu(self):
        ad = self._lib_artist_data()
        def apply(mode, desc):
            _unset = object()
            snap = (ad.get("sort", _unset), ad.get("desc", _unset), self.p.get_setting("pinned_artists", "[]"))
            ad["sort"], ad["desc"] = mode, bool(desc)
            pins = self._lib_pinned_artists()
            by = {a["k"]: a for a in ad["list"]}
            ps = [by[k] for k in pins if k in by]
            ps.sort(key=lambda a: a["n"].casefold(), reverse=mode == "name" and bool(desc))
            if mode != "name":
                ps.sort(key=lambda a: a["c"], reverse=bool(desc))
            self.p.set_setting("pinned_artists", json.dumps([a["k"] for a in ps] + [k for k in pins if k not in by]))
            self.p._lib_save()
            self._lib_render()
            def restore():
                for key, val in (("sort", snap[0]), ("desc", snap[1])):
                    if val is _unset:
                        ad.pop(key, None)
                    else:
                        ad[key] = val
                self.p.set_setting("pinned_artists", snap[2])
                self.p._lib_save()
                self._lib_render()
                return True
            self._start_undo(snap, strings("list_sorted"), restore, strings("sort_undone"))
        self._lib_sort_sheet(strings("sort_artists"), strings("n_found", len(ad['list'])),
       [("count", strings("track_count"), strings("number_of_tracks")),
       ("name", strings("artist_name"), strings("alphabetical"))],
       apply, desc=ad.get("desc", True), current=lambda: ad.get("sort") or "count")

    def _lib_artists_section(self):
        ad = self._lib_artist_data()
        mn = self._lib_artist_min()
        excluded = self._lib_excluded_artists()
        pinned = self._lib_pinned_artists()
        entries = [a for a in ad["list"]
       if (a["c"] >= mn or a["k"] in pinned) and str(a.get("k", "")).casefold() not in excluded]
        entries.sort(key=lambda a: a["n"].casefold(), reverse=ad.get("sort") == "name" and bool(ad.get("desc")))
        if ad.get("sort") != "name":
            entries.sort(key=lambda a: a["c"], reverse=bool(ad.get("desc", True)))
        entries.sort(key=lambda a: a["k"] not in pinned)
        page = self.ARTIST_PAGE * self._lib_cols() if self._lib_view("artists") == "grid" else 20
        limit = getattr(self, "lib_artist_limit", page)
        pinned_entries = sorted((a for a in entries if a["k"] in pinned), key=lambda a: pinned.index(a["k"]))
        others = [a for a in entries if a["k"] not in pinned]
        room = max(0, limit - len(pinned_entries))
        shown = pinned_entries + others[:room]
        tracks = lambda a: strings("n_tracks", a['c'])
        go = lambda a: (lambda: self._lib_go("artist", a["k"]))
        self._lib_section(
       "artists", strings("artists"), shown,
       lambda a, first, last: self._lib_row(
       a["n"], tracks(a), go(a), first, last,
       tile_fn=lambda cd, a=a: self._lib_artist_photo(a, cd), description=(strings("artist") + ": ") + a["n"],
       pin=(a["k"] in pinned, lambda a=a: self._lib_toggle_pin_artist(a["k"], a["n"])),
       reorder_type="pinned_artists" if a["k"] in pinned else None,
       reorder_id=a["k"] if a["k"] in pinned else None,
       long_cb=lambda a=a: self._lib_artist_menu(a["k"])),
       lambda a, row: self._lib_round_card(
       row, lambda size, a=a: self._lib_artist_photo(a, size), a["n"], tracks(a), go(a), (strings("artist") + ": "),
       reorder_type="pinned_artists" if a["k"] in pinned else None,
       reorder_id=a["k"] if a["k"] in pinned else None,
       long_cb=lambda a=a: self._lib_artist_menu(a["k"]),
       menu_cb=lambda a=a: self._lib_artist_menu(a["k"])),
       sort=self._lib_artist_sort_menu, sort_desc=strings("sort_artists"))
        if getattr(self.p, "_artist_dirty", False) or (not ad.get("scanned") and self.p._lib_data()["chats"]):
            self._lib_artist_auto()
        if not entries:
            self._lib_hint(strings("add_your_favorite_chats_to_library")
          if not ad.get("scanned") else
          strings("no_artists_with_n_tracks_lower", mn))
            return
        rest = len(others) - room
        if rest > 0:
            def more():
                self.lib_artist_limit = max(limit, len(pinned_entries)) + page
                old_y = int(self.lib_sv.getScrollY())
                self._lib_render()
                self.handler.postDelayed(self.Run(lambda: self.lib_sv.scrollTo(0, old_y)), 50)
            self._lib_row(strings("load_more_artists"), strings("n_remaining", rest), more, True, True,
          glyph=("msg_add",), description=strings("load_more_artists"), top_margin_dp=8)
        self._lib_hint(strings("search_and_pin_your_favorite_artists"))
        self._lib_artist_images(shown)

    def _lib_artist_photo(self, a, size, views=None):
        FL = _cls("android.widget.FrameLayout")
        FLP = _cls("android.widget.FrameLayout$LayoutParams")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        photo = FL(self.act)
        oval = GD()
        oval.setShape(1)
        oval.setColor(_mix(self.c_item, self.c_accent, 0.2))
        photo.setBackground(oval)
        with tolerated():
            photo.setClipToOutline(True)
        photo.addView(self._text(a["n"][:1].upper(), max(18, int(size / self.density / 3)),
       self.c_accent, bold=True, gravity=17), FLP(-1, -1))
        iv = _cls("android.widget.ImageView")(self.act)
        iv.setScaleType(_cls("android.widget.ImageView$ScaleType").CENTER_CROP)
        photo.addView(iv, FLP(-1, -1))
        bmp = self.p.__dict__.get("_artist_bmp", {}).get(a["k"])
        if bmp is not None:
            iv.setImageBitmap(bmp)
        (self.lib_artist_views if views is None else views)[a["k"]] = iv
        return photo

    def _lib_artist_images(self, entries):
        p = self.p
        cache = p.__dict__.setdefault("_artist_bmp", {})
        pending = p.__dict__.setdefault("_artist_pending", [])
        for a in entries:
            if a["k"] not in cache and a.get("u") != "" and a not in pending:
                pending.append(a)
        if not pending or p.__dict__.get("_artist_img_busy"):
            return
        p._artist_img_busy = True
        def work():
            try:
                while pending and self.dialog.isShowing():
                    a = pending.pop(0)
                    bmp = self._lib_artist_fetch_image(a)
                    if bmp is not None:
                        cache[a["k"]] = bmp
                        from ..helpers import mem_tight, trim_caches
                        trim_caches(cache, keep=(20 if mem_tight() else 150))
                        run_on_ui_thread(lambda k=a["k"], b=bmp: self._lib_artist_set_image(k, b))
            finally:
                p._artist_img_busy = False
                run_on_ui_thread(p._lib_save)
        threading.Thread(target=work, daemon=True).start()

    def _lib_artist_fetch_image(self, a):
        import os, hashlib, urllib.parse
        BF = _cls("android.graphics.BitmapFactory")
        norm = lambda t: re.sub(r"\\W+", "", str(t).casefold())
        artist_name = str(a.get("n") or "").strip()
        first = re.split(r"\\s*(?:,|&|/|;|\\bfeat\\.?|\\bft\\.?|\\bwith\\b)\\s*",
       artist_name, flags=re.I)[0].strip()
        queries = list(dict.fromkeys(q for q in (artist_name, first) if q))
        try:
            ctx = find_class("org.telegram.messenger.ApplicationLoader").applicationContext
            folder = os.path.join(str(ctx.getCacheDir().getAbsolutePath()), "smq_artists")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, hashlib.md5(a["k"].encode("utf-8")).hexdigest() + ".jpg")
            bmp = BF.decodeFile(path) if os.path.exists(path) else None
            if bmp is not None:
                small = _cls("android.graphics.Bitmap").createScaledBitmap(bmp, 200, 200, True)
                if small is not bmp:
                    with tolerated():
                        bmp.recycle()
                return small
            candidates = []
            if a.get("u"):
                candidates.append(a.get("u"))
            for q in queries:
                with tolerated():
                    hits = json.loads(_http_text(
                "https://api.deezer.com/search/artist?limit=5&q=" +
                urllib.parse.quote(q))).get("data") or []
                    hit = next((h for h in hits
                if norm(h.get("name", "")) == norm(q)
                and h.get("picture_medium")), None)
                    if hit:
                        candidates.append(hit.get("picture_medium"))
                        break
            for q in queries:
                with tolerated():
                    data = json.loads(_http_text(
                "https://itunes.apple.com/search?term=" + urllib.parse.quote(q) +
                "&entity=album&attribute=artistTerm&limit=15"))
                    results = data.get("results") or []
                    hit = next((r for r in results
                if norm(r.get("artistName", "")) == norm(q)
                and r.get("artworkUrl100")), None)
                    if hit:
                        candidates.append(hit["artworkUrl100"].replace("100x100bb", "600x600bb"))
                        break
            for q in queries:
                with tolerated():
                    data = json.loads(_http_text(
                "https://en.wikipedia.org/w/api.php?action=query&generator=search"
                "&gsrsearch=" + urllib.parse.quote(q) +
                "&gsrnamespace=0&gsrlimit=5&prop=pageimages&piprop=thumbnail"
                "&pithumbsize=500&format=json"))
                    pages = (data.get("query") or {}).get("pages") or {}
                    page_list = pages.values() if isinstance(pages, dict) else []
                    hit = next((pg for pg in page_list
                if norm(q) in norm(pg.get("title", ""))
                and (pg.get("thumbnail") or {}).get("source")), None)
                    if hit:
                        candidates.append(hit["thumbnail"]["source"])
                        break
            for url in dict.fromkeys(u for u in candidates if u):
                try:
                    stream = _http_stream(url)
                    try:
                        image = BF.decodeStream(stream)
                    finally:
                        stream.close()
                    if image is None:
                        continue
                    bmp = image
                    with tolerated():
                        fos = jclass("java.io.FileOutputStream")(path)
                        bmp.compress(_cls("android.graphics.Bitmap$CompressFormat").JPEG, 85, fos)
                        fos.close()
                    a["u"] = url
                    small = _cls("android.graphics.Bitmap").createScaledBitmap(bmp, 200, 200, True)
                    if small is not bmp:
                        with tolerated():
                            bmp.recycle()
                    return small
                except Exception:
                    continue
            return None
        except Exception:
            return None

    def _lib_artist_set_image(self, key, bmp):
        with tolerated():
            iv = self.lib_artist_views.get(key)
            if iv is not None:
                iv.setImageBitmap(bmp)
            hv = getattr(self, "hdr_artist_views", {}).get(key)
            if hv is not None:
                hv.setImageBitmap(bmp)

    def _lib_artist_scan(self, key):
        from ..editor import _QueueEditor
        target = str(key).casefold()
        seen, kept, dupes, natural = set(), [], [], []
        by_title = {}
        def author_ok(message):
            return (_QueueEditor._author_of(message) or "").strip().casefold() == target
        def is_dupe(message):
            try:
                raw_title = _QueueEditor._title_of(message)
                title = self._album_norm(raw_title, _QueueEditor._author_of(message) or "") \
             or " ".join(raw_title.casefold().split())
                exact = (" ".join(raw_title.casefold().split()), target)
            except Exception:
                return False
            try:
                dur = int(message.getDuration())
            except Exception:
                dur = 0
            for entry in by_title.get(title, ()):
                other, other_exact = entry["dur"], entry["exact"]
                gap = abs(dur - other)
                if not dur or not other or gap <= 2 or (gap <= 6 and exact == other_exact):
                    entry["dupes"].append(message)
                    return True
            by_title.setdefault(title, []).append(
          {"dur": dur, "exact": exact, "msg": message, "dupes": []})
            return False
        groups = []
        cache = self.p._chat_track_cache
        for ck in list(cache.keys()):
            msgs = cache.get(ck)
            rows = getattr(msgs, "rows", None)
            found = []
            if rows is not None:
                for n, r in enumerate(rows):
                    if (r.get("a") or "").strip().casefold() == target:
                        with tolerated():
                            found.append(msgs[n])
            else:
                for message in msgs or []:
                    if message is not None and author_ok(message):
                        found.append(message)
            if found:
                groups.append(found)
        groups.sort(key=lambda g: -len(g))
        extra = [m for m in (self.p.__dict__.get("_artist_extra_msgs", {}).get(target, []) or [])
       if m is not None and author_ok(m)]
        if extra:
            groups.append(extra)
        for group in groups:
            for message in group:
                if message is None or not author_ok(message):
                    continue
                k = self._lib_key(message)
                if k in seen:
                    continue
                seen.add(k)
                natural.append(message)
                is_dupe(message)
        hidden = set()
        for entries in by_title.values():
            for entry in entries:
                if not entry["dupes"]:
                    continue
                shown, others = entry["msg"], list(entry["dupes"])
                with tolerated():
                    if not self.p._is_downloaded(shown):
                        better = next((d for d in others if self.p._is_downloaded(d)), None)
                        if better is not None:
                            others.remove(better)
                            others.append(shown)
                            shown = better
                hidden.update(self._lib_key(d) for d in others)
        for message in natural:
            (dupes if self._lib_key(message) in hidden else kept).append(message)
        return kept, dupes, natural

    def _lib_artist_msgs(self, key):
        return self._lib_artist_scan(key)[0]

    def _lib_on_artist_page(self, name):
        try:
            kind, ref = self.lib_state
            if kind != "artist" or getattr(self, "tab", None) != "library":
                return False
            n = str(name or "").strip().casefold()
            if not n:
                return False
            if str(ref).casefold() == n:
                return True
            a = next((a for a in self._lib_artist_data().get("list", [])
          if str(a.get("k", "")).casefold() == str(ref).casefold()), None)
            return a is not None and str(a.get("n", "")).strip().casefold() == n
        except Exception:
            return False

    def _lib_ensure_artist(self, name, message=None):
        name = str(name or "").strip()
        if not name:
            return None
        key = name.casefold()
        ad = self._lib_artist_data()
        artist = next((a for a in ad.get("list", [])
       if str(a.get("k", "")).casefold() == key
       or str(a.get("n", "")).strip().casefold() == key), None)
        if artist is not None:
            key = str(artist.get("k", key)).casefold()
        if message is not None:
            extras = self.p.__dict__.setdefault("_artist_extra_msgs", {})
            bucket = extras.setdefault(key, [])
            try:
                message_key = self._lib_key(message)
                if all(self._lib_key(existing) != message_key for existing in bucket):
                    bucket.append(message)
            except Exception:
                if message not in bucket:
                    bucket.append(message)
        if artist is None:
            msgs = self._lib_artist_msgs(key)
            artist = {"k": key, "n": name, "c": max(1, len(msgs)), "q": 1}
            ad.setdefault("list", []).append(artist)
            self.p._lib_save()
        return key

    def _lib_artist_view(self, key):
        p = self.p
        if str(key).casefold() in self._lib_excluded_artists():
            self._lib_go("home")
            return
        a = next((x for x in self._lib_artist_data()["list"] if x["k"] == key), None)
        if a is None:
            self._lib_go("home")
            return
        self._lib_set_selection_context(("artist", key))
        self.lib_scope = None
        tried = p.__dict__.setdefault("_artist_tried", set())
        missing = [k for k in ((int(c["d"]), int(c["t"])) for c in p._lib_data()["chats"])
       if k not in p._chat_track_cache and k not in tried]
        if missing:
            tried.update(missing)
            self._lib_each_chat(missing, lambda _m: None,
          lambda: self.lib_state == ("artist", key) and self._lib_render())
        msgs, dupes, natural = self._lib_artist_scan(key)
        meta = (strings("loading_tracks") if missing else
       self._lib_tracks_meta(len(msgs), self._lib_message_minutes(msgs)) if msgs else strings("no_cached_tracks"))
        artist_avatar = self._artist_avatar(key, self.dp(36), a["n"])
        self._lib_detail_header(
       a["n"], meta, lambda: self._lib_go("home"),
       lambda: self._lib_artist_menu(key), avatar_view=artist_avatar,
       sync_action=(lambda: self._lib_artist_sync(key),
                    lambda: bool(self.__dict__.get("_artist_syncing")) or bool(self.__dict__.get("_artist_scanning"))
                    or a["k"] in p.__dict__.get("_album_busy", ())))
        if missing:
            self._lib_empty_loading_view(strings("loading_tracks"))
            return
        if not msgs:
            self._lib_hint(strings("no_cached_tracks_rescan_the_chat"))
            return
        src = ("artist", key)
        qname, qcover = a["n"], None
        self.lib_filter_label = None
        shown = self._lib_album_tabs(a, msgs, dupes, natural)
        dupe_info = self.lib_dupe_info
        if self.lib_filter_label:
            src = ("artist", key, self.lib_album_sel.get(key))
            qname = f"{a['n']}:{self.lib_filter_label}"[:60]
            qcover = shown[0] if shown else None
        self._lib_apply_filter_meta(shown)
        if self.lib_filter_label:
            self.lib_scope = {"state": ("artist", key), "shown": shown, "name": qname,
          "src": src, "cover": qcover, "label": self.lib_filter_label}
        self._lib_detail_actions(
       lambda: p._lib_play_msgs(shown, "play", name=qname, source_key=src, cover=qcover),
       lambda: p._lib_play_msgs(shown, "play", shuffle=True, name=qname, source_key=src, cover=qcover))
        def row_at(i):
            m = shown[i]
            return (m, None,
          lambda mm=m, idx=i: p._lib_play_msgs(
          shown, "play", start=p._msg_key(mm), name=qname,
          source_key=src, cover=qcover, _start_index=idx),
          lambda mm=m: self._lib_track_menu(mm))
        miss = int(getattr(self, "lib_album_missing", 0) or 0)
        def tail():
            if miss and self.lib_filter_label:
                self._lib_hint(strings("n_songs_missing_from_this_album", miss))
            if dupe_info:
                self._lib_dupes_card(dupe_info)
            if a.get("q") and len(msgs) <= 1:
                self._lib_hint(strings("add_your_favorite_chats_to_library"))
        self._lib_render_track_rows(len(shown), row_at, tail=tail)

    def _lib_dupes_card(self, info):
        n = int(info["n"])
        album = bool(info.get("album"))
        if info["open"]:
            title = strings("showing_n_dupe_tracks_from_this", n) if album else strings("showing_n_duplicate_tracks", n)
            sub = strings("tap_to_hide_them")
        else:
            title = strings("n_dupe_tracks_from_this_album", n) if album else strings("n_duplicate_tracks_hidden", n)
            sub = strings("tap_to_show_them_in_list")
        def toggle():
            opened = self.__dict__.setdefault("lib_dupes_open", set())
            scope = info["scope"]
            if scope in opened:
                opened.discard(scope)
            else:
                opened.add(scope)
            try:
                y = int(self.lib_sv.getScrollY())
            except Exception:
                y = 0
            self._lib_render()
            with tolerated():
                self.handler.postDelayed(self.Run(lambda: self.lib_sv.scrollTo(0, y)), 30)
        self._lib_row(title, sub, toggle, True, True, glyph=("msg_folders", "msg_media"),
       description=f"{title}. {sub}", top_margin_dp=12)
