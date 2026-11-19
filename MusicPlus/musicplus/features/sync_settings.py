import threading
import time
from ..compat import (
 Any,
 ArrayList,
 Dict,
 MenuItemData,
 MenuItemType,
 Optional,
 find_class,
 get_last_fragment,
 get_private_field,
 jclass,
 run_on_ui_thread,
)
from elyx import strings
from ..telegram_io import _MusicFetcher
from ..editor import _QueueEditor
from ..sheets import _ActionSheet
from ..native_sheets import _ProgressSheet
from ..safe import tolerated


class _PluginSyncSettings:
    def _sync_editor_after_library_start(self, attempt=0):
        editor = getattr(self, "_editor", None)
        if editor is not None:
            with tolerated():
                if getattr(editor, "drag", None) is None and editor._load():
                    editor.win_start = editor.win_end = 0
                    editor.queue_lazy_ready = False
                    editor._refresh()
                    editor._scroll_to_playing()
                editor._mini_update()
        if attempt < 3:
            self._post(lambda: self._sync_editor_after_library_start(attempt + 1), 160)

    def _finish_scope_tracks_sync(self, tracks, topic_id, on_ready):
        used = list(tracks or [])
        if topic_id == 1 and used:
            with tolerated():
                batch = ArrayList()
                for item in used:
                    batch.add(item)
                general = self._filter_messages(batch, 1, None, None)
                used = [general.get(i) for i in range(general.size())] if general is not None else []
        with tolerated():
            used.sort(key=lambda m: -int(m.getId()))
        for message in used:
            key = self._msg_key(message)
            if key:
                self._msg_cache[key] = message
        on_ready(used)

    def _finish_scope_tracks_async(self, tracks, topic_id, on_ready):
        def work():
            used = list(tracks or [])
            if topic_id == 1 and used:
                with tolerated():
                    batch = ArrayList()
                    for item in used:
                        batch.add(item)
                    general = self._filter_messages(batch, 1, None, None)
                    used = [general.get(i) for i in range(general.size())] if general is not None else []
            with tolerated():
                used.sort(key=lambda m: -int(m.getId()))
            for message in used:
                key = self._msg_key(message)
                if key:
                    self._msg_cache[key] = message
            def finish():
                with tolerated():
                    on_ready(used)
            try:
                run_on_ui_thread(finish)
            except Exception:
                finish()
        threading.Thread(target=work, daemon=True, name="smq-scope-finish").start()

    def _fetch_scope_tracks(self, frag, dialog_id, topic_id, loaded_tracks, on_ready, act=None, on_fail=None,
    since_id=0, on_batch=None, silent=False):
        pkey = ("fetch", int(dialog_id or 0), int(topic_id or 0))
        def _failed():
            self._prog_end(pkey)
            self._activity_status(pkey, None)
            if on_fail is not None:
                with tolerated():
                    on_fail()
        act = act or (frag.getParentActivity() if frag is not None else None)
        if act is None or not dialog_id:
            self._bulletin(strings("cant_determine_this_chat"), error=True)
            _failed()
            return
        scope = strings("topic") if topic_id else strings("chat").lower()
        acc = self._chat_account(frag, loaded_tracks)
        sheet = _ProgressSheet(self, act)
        partial = {"continue": False}
        streamed_tracks = []
        def on_progress(count, total):
            sheet.set_text(strings("n_of_n_tracks", count, total) if total and total >= count else strings("n_tracks_found", count))
            self._prog_set(pkey, count, total if total and total >= count else 0)
        def batch_ready(batch, count, total):
            used_batch = list(batch or [])
            if topic_id == 1 and used_batch:
                with tolerated():
                    arr = ArrayList()
                    for item in used_batch:
                        arr.add(item)
                    general = self._filter_messages(arr, 1, None, None)
                    used_batch = [general.get(i) for i in range(general.size())] if general is not None else []
            for item in used_batch:
                k = self._msg_key(item)
                if k:
                    self._msg_cache[k] = item
            if on_batch is not None and used_batch:
                streamed_tracks.extend(used_batch)
                on_batch(used_batch, count, total)
        def on_done(tracks, error, cancelled):
            sheet.close()
            self._prog_end(pkey)
            self._activity_status(pkey, None)
            self._request_library_refresh()
            if cancelled and not partial["continue"]:
                _failed()
                return
            used = tracks
            using_loaded_fallback = False
            if (error or partial["continue"]) and not tracks and loaded_tracks:
                used = loaded_tracks
                using_loaded_fallback = True
                self._bulletin(strings("fetch_failed_n_using_loaded_messages", error), error=True)
            elif error and not tracks:
                self._bulletin(
             strings("couldnt_check_for_new_music_n", error) if since_id else strings("couldnt_load_music_n", error),
             error=True)
                _failed()
                return
            if on_batch is not None and not using_loaded_fallback and streamed_tracks:
                used = list(streamed_tracks)
                already_streamed = True
            else:
                already_streamed = False
            if since_id:
                if error and not tracks:
                    _failed()
                    return
                if already_streamed:
                    on_ready(used)
                else:
                    self._finish_scope_tracks_async(used, topic_id, on_ready)
                return
            if not used:
                self._bulletin(strings("no_music_found_in_this_n", scope), error=True)
                _failed()
                return
            if already_streamed:
                on_ready(used)
            elif len(used) >= 128:
                self._finish_scope_tracks_async(used, topic_id, on_ready)
            else:
                self._finish_scope_tracks_sync(used, topic_id, on_ready)
        fetcher = _MusicFetcher(self, acc, dialog_id, topic_id, on_progress, on_done,
       min_id=since_id, on_batch=batch_ready if on_batch is not None else None)
        def continue_partial():
            partial["continue"] = True
            fetcher.stop_with_partial()
        def _cancel():
            fetcher.cancel()
            _failed()
        if not silent and not self._library_ui_active():
            sheet.show_progress(strings("loading_music_of_this_n", scope), _cancel,
          on_continue=continue_partial)
        else:
            with tolerated():
                sheet.close()
        self._prog_set(pkey, 0, 0)
        fetcher.start()

    def _chat_add_friend(self, frag, dialog_id, tracks):
        acc = self._chat_account(frag, tracks)
        user = None
        with tolerated():
            user = find_class("org.telegram.messenger.MessagesController").getInstance(acc).getUser(int(dialog_id))
        self._friend_add_profile({"user": user, "userId": int(dialog_id), "account": acc})

    def _chat_add_chat(self, context, whole=False):
        try:
            frag, dialog_id, topic_id, tracks, _n = self._chat_scope(context)
            if whole:
                topic_id = 0
            if not dialog_id:
                self._bulletin(strings("cant_do_that_here"), error=True)
                return
            name = self._auto_queue_name(dialog_id, topic_id, None, self._chat_account(frag, tracks))
            new = self._lib_add_chat(
          dialog_id, topic_id, name, self._chat_account(frag, tracks))
            self._bulletin(strings("added_n_to_library_chats", name) if new else strings("already_in_library"))
        except Exception:
            self._bulletin(strings("library_action_failed"), error=True)

    def _chat_add_to_sheet(self, context):
        try:
            frag, dialog_id, topic_id, tracks, _n = self._chat_scope(context)
            act = frag.getParentActivity() if frag is not None else None
            if act is None or not dialog_id:
                self._bulletin(strings("cant_do_that_here"), error=True)
                return
            name = self._auto_queue_name(dialog_id, topic_id, None, self._chat_account(frag, tracks))
            def get_items(cb):
                self._fetch_scope_tracks(frag, dialog_id, topic_id, tracks, cb, act)
            self._lib_add_to_sheet(act, get_items, name, name, need_active=True)
        except Exception:
            self._bulletin(strings("add_to_failed"), error=True)

    def _chat_set_profile(self, context):
        try:
            frag, dialog_id, topic_id, tracks, _n = self._chat_scope(context)
            act = frag.getParentActivity() if frag is not None else None
            if act is None or not dialog_id:
                self._bulletin(strings("cant_do_that_here"), error=True)
                return
            name = self._auto_queue_name(dialog_id, topic_id, None, self._chat_account(frag, tracks))
            def get_items(cb):
                self._fetch_scope_tracks(frag, dialog_id, topic_id, tracks, cb, act)
            self._profile_playlist_sheet(act, name, get_items, None)
        except Exception:
            self._bulletin(strings("profile_playlist_failed"), error=True)

    def _lock_playlist(self, reason):
        scope = getattr(self, "_topic_hydration_scope", None)
        if scope is not None:
            same_topic_scope = (
          isinstance(reason, tuple) and len(reason) >= 3
          and reason[0] == "filter"
          and int(reason[1]) == int(scope[1])
          and str(reason[2] or "").strip() == str(scope[2] or "").strip()
          )
            if not same_topic_scope:
                self._cancel_topic_hydration()
        self._active_filter = reason

    def _unlock_playlist(self):
        self._active_filter = None
        if getattr(self, "_topic_hydration_scope", None) is not None:
            self._cancel_topic_hydration()

    @staticmethod
    def _to_int(val) -> int:
        try:
            return int(val) if val else 0
        except Exception:
            return 0

    @staticmethod
    def _read(obj, *names):
        if obj is None:
            return None
        for name in names:
            with tolerated():
                val = getattr(obj, name, None)
                if val is not None:
                    if callable(val):
                        val = val()
                    if val is not None:
                        return val
            with tolerated():
                val = get_private_field(obj, name)
                if val is not None:
                    return val
        return None

    def _read_flag(self, obj, names) -> Optional[bool]:
        found = None
        for name in names:
            val = self._read(obj, name)
            if val is None:
                continue
            try:
                if bool(val):
                    return True
                found = False
            except Exception:
                continue
        return found

    def _install_menu_items(self):
        with tolerated():
            mid = self.add_menu_item(MenuItemData(
          menu_type=MenuItemType.MESSAGE_CONTEXT_MENU,
          text="Music +",
          on_click=self._safe_message_actions,
          icon="files_music",
          priority=60,
          item_id="smart_music_queue_actions",
          ))
            if mid:
                self._menu_ids.append(mid)
        with tolerated():
            profile_type = getattr(MenuItemType, "PROFILE_ACTION_MENU", None)
            if profile_type is not None:
                mid = self.add_menu_item(MenuItemData(
             menu_type=profile_type,
             text="Music +",
             on_click=lambda ctx: self._show_chat_sheet(ctx),
             icon="files_music",
             priority=20,
             item_id="sq_profile_menu",
             ))
                if mid:
                    self._menu_ids.append(mid)
        self._sync_drawer_menu_item(bool(self.get_setting("drawer_enabled", True)))

    def _sync_drawer_menu_item(self, enabled):
        old = getattr(self, "_drawer_menu_id", None)
        if old:
            with tolerated():
                self.remove_menu_item(old)
            with tolerated():
                self._menu_ids.remove(old)
            self._drawer_menu_id = None
        if not enabled:
            return
        try:
            drawer_type = getattr(MenuItemType, "DRAWER_MENU", None)
            if drawer_type is None:
                return
            mid = self.add_menu_item(MenuItemData(
          menu_type=drawer_type,
          text="Music +",
          on_click=lambda ctx: self._open_queue_editor(),
          icon="files_music",
          priority=20,
          item_id="sq_drawer_menu",
          ))
            if mid:
                self._drawer_menu_id = mid
                self._menu_ids.append(mid)
        except Exception:
            self._drawer_menu_id = None

    _MINI_OPT_DEFAULTS = {"mini_show_prev": True, "mini_show_like": True, "mini_show_locate": False}

    def _mini_opt(self, key):
        return self._MINI_OPT_DEFAULTS.get(key, False)


    def _drawer_setting_changed(self, value):
        self._sync_drawer_menu_item(bool(value))

    def _msg_file_name(self, msg):
        name = ""
        with tolerated():
            name = str(msg.getDocumentName() or "")
        if not name:
            with tolerated():
                name = str(msg.getFileName() or "")
        return name

    def _safe_message_actions(self, context: Dict[str, Any]):
        with tolerated():
            msg = context.get("message") if context else None
            music = False
            try:
                music = msg is not None and bool(msg.isMusic())
            except Exception:
                music = False
            if not music:
                self._open_queue_editor()
                return
            run_on_ui_thread(lambda: self._show_message_actions(msg))

    def _is_message_in_queue(self, msg) -> bool:
        if msg is None:
            return False
        mc = self._get_mc()
        pl = self._get_playlist(mc) if mc is not None else None
        if pl is None:
            return False
        try:
            return self._index_of(pl, int(msg.getId()), int(msg.getDialogId())) >= 0
        except Exception:
            return False

    def _track_sheet(self, act, msg, hero, extras=None, editor=None, subtitle=None):
        def close(fn):
            if editor is not None:
                editor._after_close(fn)
            else:
                fn()
        opts = list(extras or [])
        artist = (_QueueEditor._author_of(msg) or "").strip()
        if artist:
            opts.append((strings("search_for_artist"), strings("search_telegram_music_for_this_artist"), False,
          lambda a=artist: close(lambda: self._open_artist_music_search(a))))
        if opts:
            opts.append(None)
        opts += [
       (strings("forward"), strings("forward_this_track_to_a_chat"), False, lambda: close(lambda: self._pick_forward(msg))),
       self._dl_option(msg, strings("download_this_track"), strings("stop_downloading_this_track")),
       (strings("save_to_music"), strings("download_and_save_this_track"), False, lambda: self._save_to_music(msg)),
       (strings("show_in_chat"), strings("open_the_original_message"), False, lambda: close(lambda: self._show_in_chat(msg))),
       ]
        opts = [o for o in opts if o != ()]
        if subtitle is None:
            sub = artist
        else:
            sub = f"{artist} \u00b7 {subtitle}" if artist else subtitle
        sheet = _ActionSheet(self, act)
        lead = None
        with tolerated():
            lead = sheet._lead_cover(m=msg)
        sheet.show_sheet(
       _QueueEditor._title_of(msg), sub,
       opts, list(hero)[:4], artist_view=artist or None,
       artist_message=msg if artist else None, like_message=msg, lead=lead)

    def _collection_sheet(self, act, title, meta, play_next, add_to, select=None, exclude=None,
    extras=(), danger=(), header_action=None, artist_search=None, lead=None, playlist=None):
        hero = [(strings("play_next"), play_next, False, ("ic_action_next", "msg_arrowright")),
       (strings("add_to"), add_to, False, ("msg_add",))]
        if select is not None:
            hero.append((strings("select_all"), select, False))
        if exclude is not None:
            hero.append((strings("exclude_from_queue"), exclude, True, ("filled_clear", "msg_close")))
        opts = list(extras)
        if artist_search:
            opts.append((strings("search_for_artist"), strings("search_telegram_music_for_this_artist"), False,
          lambda name=artist_search: self._open_artist_music_search(name)))
        if danger:
            if opts and opts[-1] is not None:
                opts.append(None)
            opts += list(danger)
        sheet = _ActionSheet(self, act)
        if lead is None and playlist is not None:
            with tolerated():
                lead = sheet._opt_tile(playlist, sheet.dp(48))
        sheet.show_sheet(
       title, meta, opts, hero[:4], header_action=header_action, lead=lead)

    def _selection_sheet(self, act, title, subtitle, hero, select_all, forward, save,
    done=None, extras=(), download=None, count=0, items=None, cancel=None):
        over = count > 100
        hint = strings("select_up_to_100_tracks")
        opts = ([select_all] if select_all else []) + ([done] if done else []) + list(extras)
        opts += [None,
       (strings("forward"), hint if over else strings("forward_selected_tracks_to_a_chat"), False, forward, "", None, None, over)]
        if download is not None:
            state = "download"
            if not over and items is not None:
                with tolerated():
                    state = self._dl_state(items())
            if state == "cancel" and cancel is not None:
                opts.append((strings("cancel_downloading"), strings("stop_downloading_the_selected_tracks"), False, cancel))
            elif state != "done":
                opts.append((strings("download"), hint if over else strings("download_the_selected_tracks"), False, download, "", None, None, over))
        opts.append((strings("save_to_music"), hint if over else strings("downloads_tracks_before_saving"), False, save, "", None, None, over))
        _ActionSheet(self, act).show_sheet(title, subtitle, opts, list(hero)[:4])

    def _exclude_from_queue(self, msgs, name):
        msgs = [m for m in msgs or [] if m is not None]
        if not msgs:
            self._bulletin(strings("no_cached_tracks_to_exclude"), error=True)
            return
        removed, kept = self._queue_exclude_messages(msgs)
        if removed:
            self._bulletin(strings("excluded_n_tracks_n", removed, name)
          + (strings("kept_the_playing_track") if kept else ""))
        elif kept:
            self._bulletin(strings("kept_the_currently_playing_track_n", name))
        else:
            self._bulletin(strings("nothing_from_n_is_in_the", name), error=True)

    def _hero_add_to(self, act, msg, end_of_queue=True, subtitle=strings("add_this_track_to_the_queue")):
        return (strings("add_to"), lambda: self._lib_add_to_sheet(
       act, lambda cb: cb([msg]), default_name=_QueueEditor._title_of(msg),
       subtitle=subtitle, end_of_queue=end_of_queue), False, ("msg_add",))

    def _show_queue_track_menu(self, msg, editor=None):
        try:
            frag = get_last_fragment()
            act = editor.act if editor is not None else (frag.getParentActivity() if frag is not None else None)
            if act is None:
                self._bulletin(strings("cant_open_music_actions_here"), error=True)
                return
            mc = self._get_mc()
            playing = self._msg_key(msg) == self._playing_key(mc)
            def play_next():
                if editor is not None:
                    editor._row_action(self._queue_next, msg)
                elif not self._queue_next(msg):
                    self._bulletin(strings("couldnt_do_that"), error=True)
            def remove_from_queue():
                if editor is not None:
                    editor._remove(msg)
                    return
                if self._msg_key(msg) == self._playing_key(self._get_mc()):
                    self._bulletin(strings("cant_remove_the_track_that_is"), error=True)
                elif not self._queue_remove(msg):
                    self._bulletin(strings("couldnt_remove_that_track"), error=True)
            def play_track():
                if editor is not None:
                    editor._play(msg)
                    return
                controller = self._get_mc()
                if controller is None:
                    self._bulletin(strings("player_not_available"), error=True)
                    return
                try:
                    self._allow_remote = True
                    try:
                        controller.playMessage(msg)
                    finally:
                        self._allow_remote = False
                except Exception:
                    self._bulletin(strings("could_not_play_that_track"), error=True)
            def select_track():
                if editor is not None:
                    editor._enter_sel(msg)
                else:
                    self._open_queue_editor_select(msg)
            select = (strings("select"), select_track, False)
            hero, extras = [self._hero_add_to(act, msg, False, strings("add_this_track_to_a_playlist")), select], []
            if not playing:
                hero = [(strings("play_next"), play_next, False), hero[0], select,
             (strings("remove"), remove_from_queue, True)]
                if editor is not None:
                    extras.append((strings("play"), "", False, play_track))
            self._track_sheet(act, msg, hero, extras, editor=editor)
        except Exception:
            self._bulletin(strings("couldnt_open_music_actions"), error=True)

    def _open_queue_editor_select(self, msg):
        self._open_queue_editor()
        def _select_when_ready():
            ed = getattr(self, "_editor", None)
            if ed is None:
                return
            with tolerated():
                if not ed.dialog.isShowing():
                    return
                if any(ed._key(item) == self._msg_key(msg) for item in ed.items):
                    ed._enter_sel(msg)
        self._post(_select_when_ready, 350)

    def _show_message_actions(self, msg):
        try:
            frag = get_last_fragment()
            act = frag.getParentActivity() if frag is not None else None
            if act is None:
                self._bulletin(strings("cant_open_music_actions_here"), error=True)
                return
            if self._is_message_in_queue(msg):
                self._show_queue_track_menu(msg)
                return
            hero = [(strings("play_next"), lambda: self._do_play_next(msg), False), self._hero_add_to(act, msg)]
            self._track_sheet(act, msg, hero)
        except Exception:
            self._bulletin(strings("couldnt_open_music_actions"), error=True)

    def _drop_editor(self, ed):
        try:
            for r in (getattr(ed, "mini_run", None), getattr(ed, "tick_run", None),
          getattr(ed, "undo_action_run", None), getattr(ed, "undo_expire_run", None)):
                if r is not None:
                    with tolerated():
                        ed.handler.removeCallbacks(r)
            with tolerated():
                ed._hide_undo()
            with tolerated():
                ed.dialog.dismiss()
        finally:
            if getattr(self, "_editor", None) is ed:
                self._editor = None
            if getattr(self, "_kept_editor", None) is ed:
                self._kept_editor = None

    def _open_queue_editor(self):
        def _go():
            try:
                if self._tab_open():
                    return
                act = None
                with tolerated():
                    frag = get_last_fragment()
                    act = frag.getParentActivity() if frag is not None else None
                if act is None:
                    try:
                        act = find_class("org.telegram.ui.LaunchActivity").instance
                    except Exception:
                        act = None
                if act is None:
                    self._bulletin(strings("cant_open_the_queue_editor_here"), error=True)
                    return
                ed = getattr(self, "_editor", None)
                if ed is not None and getattr(ed, "tabmode", False):
                    ed = None
                if ed is not None:
                    live = False
                    try:
                        live = (bool(ed.act.equals(act)) and bool(ed.dialog.isShowing())
                   and bool(ed.dialog.getWindow().getDecorView().isAttachedToWindow()))
                    except Exception:
                        live = False
                    if live:
                        return
                    self._drop_editor(ed)
                kept = getattr(self, "_kept_editor", None)
                self._kept_editor = None
                if kept is not None:
                    with tolerated():
                        if (bool(self.get_setting("keep_sheet_alive", True))
                   and bool(kept.act.equals(act)) and kept._theme_same()):
                            kept.reopen()
                            return
                    self._drop_editor(kept)
                _QueueEditor(self, act).show()
            except Exception as e:
                self._bulletin(strings("queue_editor_failed_n", e), error=True)
        try:
            run_on_ui_thread(_go)
        except Exception:
            _go()

    def _friend_add_profile(self, context):
        try:
            context = context or {}
            user = context.get("user")
            user_id = self._to_int(context.get("userId") or context.get("user_id"))
            if not user_id and user is not None:
                user_id = self._to_int(self._read(user, "id", "user_id"))
            try:
                acc = int(context.get("account", 0) or 0)
            except Exception:
                acc = 0
            if not user_id:
                self._bulletin(strings("couldnt_identify_this_profile"), error=True)
                return
            with tolerated():
                me = int(find_class("org.telegram.messenger.UserConfig").getInstance(acc).getClientUserId())
                if user_id == me:
                    self._bulletin(strings("your_own_profile_doesnt_need_to"), error=True)
                    return
            access_hash = self._to_int(self._read(user, "access_hash", "accessHash"))
            name = self._dialog_title(user_id, acc)
            if not name and user is not None:
                with tolerated():
                    name = str(find_class("org.telegram.messenger.UserObject").getUserName(user)).strip()
            name = (name or str(self._read(user, "first_name") or strings("profile"))).strip()
            friend = {"d": int(user_id), "h": int(access_hash), "a": int(acc), "n": name}
            data = self._lib_data()
            existing = next((f for f in data["friends"]
          if int(f.get("d", f.get("id", 0)) or 0) == user_id), None)
            if existing is None:
                data["friends"].append(friend)
                message = strings("saved_n_to_library_friends", name)
            else:
                existing.update(friend)
                message = strings("updated_n_in_library_friends", name)
            self._lib_save()
            self._friend_track_cache.pop((acc, user_id), None)
            self._bulletin(message)
            editor = getattr(self, "_editor", None)
            if editor is not None:
                with tolerated():
                    editor._lib_render()
        except Exception:
            self._bulletin(strings("couldnt_save_this_profile"), error=True)

    def _open_profile_user(self, user_id, acc=0):
        try:
            frag = get_last_fragment()
            act = frag.getParentActivity() if frag is not None else None
            if frag is None or act is None:
                self._bulletin(strings("cant_open_this_profile_here"), error=True)
                return
            args = jclass("android.os.Bundle")()
            args.putLong("user_id", int(user_id))
            profile = find_class("org.telegram.ui.ProfileActivity")(args)
            frag.presentFragment(profile)
        except Exception:
            self._bulletin(strings("couldnt_open_this_profile"), error=True)

    def _install_chat_menu_items(self):
        mtype = getattr(MenuItemType, "CHAT_ACTION_MENU", None)
        if mtype is None:
            return
        with tolerated():
            mid = self.add_menu_item(MenuItemData(
          menu_type=mtype,
          text="Music +",
          on_click=lambda ctx: self._show_chat_sheet(ctx),
          icon="files_music",
          priority=20,
          item_id="sq_chat_menu",
          ))
            if mid:
                self._menu_ids.append(mid)

    def _show_chat_sheet(self, context):
        def _go():
            try:
                frag, dialog_id, topic_id, tracks, _ = self._chat_scope(context)
                act = frag.getParentActivity() if frag is not None else None
                if act is None:
                    self._bulletin(strings("cant_open_the_menu_here"), error=True)
                    return
                scope = strings("topic") if topic_id else strings("chat").lower()
                private = int(dialog_id or 0) > 0 and not topic_id
                friend_opt = [(strings("add_as_friend"), strings("save_this_users_profile_music_to"), False,
             lambda: self._chat_add_friend(frag, dialog_id, tracks))] if private else []
                chat_lead = None
                with tolerated():
                    sheet_ed = _ActionSheet(self, act)
                    chat_lead = sheet_ed._lib_avatar_tile(int(dialog_id), self._chat_account(frag, tracks), sheet_ed.dp(48), True)
                sheet_title, sheet_sub = "Music +", ""
                with tolerated():
                    acc0 = self._chat_account(frag, tracks)
                    nm = (self._topic_label(dialog_id, topic_id, acc0) if topic_id else "") or self._dialog_title(int(dialog_id), acc0)
                    if nm:
                        sheet_title = str(nm)[:60]
                with tolerated():
                    key0 = (int(dialog_id), int(topic_id or 0))
                    cached0 = self._chat_track_cache.get(key0)
                    n0 = len(cached0) if cached0 is not None else 0
                    if not n0:
                        ent = next((c for c in self._lib_data()["chats"] if (int(c["d"]), int(c["t"])) == key0), None)
                        n0 = int((ent or {}).get("cn") or 0)
                    if n0:
                        sheet_sub = strings("n_tracks", n0)
                self._collection_sheet(
             act, sheet_title, sheet_sub,
             lambda: self._do_chat_action("next", context),
             lambda: self._chat_add_to_sheet(context),
             exclude=lambda: self._do_chat_action("exclude", context),
             extras=[
             (strings("add_chat_to_library"), strings("the_whole_group_all_topics") if topic_id else "", False,
             lambda: self._chat_add_chat(context, whole=True)),
             *([(strings("add_topic_to_library"), strings("only_this_topic"), False,
             lambda: self._chat_add_chat(context))] if topic_id else []),
             *friend_opt,
             self._share_playlist_opt(
             (self._topic_label(dialog_id, topic_id, self._chat_account(frag, tracks)) if topic_id else "")
             or self._auto_queue_name(dialog_id, topic_id, None, self._chat_account(frag, tracks)),
             lambda cb: self._fetch_scope_tracks(frag, dialog_id, topic_id, tracks, cb, act)),
             (strings("set_as_profile_playlist"), strings("use_this_n_s_music_as", scope), False,
             lambda: self._chat_set_profile(context)),
             None,
             (strings("open_music"), strings("queue_and_library"), False, self._open_queue_editor)],
             lead=chat_lead)
            except Exception:
                self._bulletin(strings("music_menu_failed"), error=True)
        try:
            run_on_ui_thread(_go)
        except Exception:
            _go()

    def _request_library_refresh(self):
        def refresh():
            with tolerated():
                editor = getattr(self, "_editor", None)
                if editor is not None and getattr(editor, "tab", None) == "library":
                    editor._queue_library_refresh()
        try:
            run_on_ui_thread(refresh)
        except Exception:
            refresh()

    def _activity_status(self, key, text=None):
        jobs = self.__dict__.setdefault("_activity_jobs", {})
        if text is None:
            jobs.pop(key, None)
        else:
            jobs[key] = (str(text), time.monotonic())
        editor = getattr(self, "_editor", None)
        if editor is not None:
            def refresh():
                with tolerated():
                    editor._activity_refresh()
            try:
                run_on_ui_thread(refresh)
            except Exception:
                refresh()

    def _prog_notify(self):
        fn = getattr(getattr(self, "_editor", None), "_lib_progress_refresh", None)
        if fn is not None:
            with tolerated():
                fn()

    def _prog_set(self, key, done, total=0):
        self.__dict__.setdefault("_prog_tasks", {})[key] = (int(done), int(total), time.time())
        self._prog_notify()

    def _prog_end(self, key):
        if self.__dict__.setdefault("_prog_tasks", {}).pop(key, None) is not None:
            self._prog_notify()

    def _library_ui_active(self):
        try:
            ed = getattr(self, "_editor", None)
            return ed is not None and getattr(ed, "tab", None) == "library"
        except Exception:
            return False

    def _prog_state(self):
        tasks = self.__dict__.setdefault("_prog_tasks", {})
        now = time.time()
        for k in [k for k, v in tasks.items() if now - v[2] > 120]:
            tasks.pop(k, None)
        if not tasks:
            return None
        fetch = [min(1.0, d / t) for k, (d, t, _) in tasks.items() if k[0] != "each" and t > 0]
        ff = sum(fetch) / len(fetch) if fetch else 0.0
        eaches = [(d, t) for k, (d, t, _) in tasks.items() if k[0] == "each" and t > 0]
        if eaches:
            frac = sum(min(1.0, (d + ff) / t) for d, t in eaches) / len(eaches)
        elif fetch:
            frac = ff
        else:
            return -1
        return max(0, min(100, int(frac * 100)))

    def _net_ok(self):
        try:
            return not self._net_down()
        except Exception:
            return True

    _XFER_EXTS = (".mpdb", ".mppl", ".mpss")
    _XFER_SKIP = ("downloaded", "profile", "last_queue")
    _XFER_MAX_BYTES = 33554432
