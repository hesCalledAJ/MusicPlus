import time
from ..compat import ArrayList, BulletinHelper, MethodHook, Optional, find_class, get_last_fragment, get_private_field, jclass, jfloat, run_on_ui_thread
from ..constants import SEARCH_QUERY_NAMES, TOPIC_FLAG_NAMES, TOPIC_ID_NAMES
from elyx import strings
from ..android import _proxies
from ..tabs import _TabHook
from ..safe import tolerated


class _PluginUndoFilters:
    _adv_key = None

    def _ghost_silence(self, mc=None):
        with tolerated():
            mc = mc or self._get_mc()
            if mc is None or not bool(mc.isMessagePaused()) or mc.getPlayingMessageObject() is None:
                return
            f = mc.getClass().getDeclaredField("audioPlayer")
            f.setAccessible(True)
            pl = f.get(mc)
            if pl is not None and bool(pl.isPlaying()):
                pl.pause()

    def _ghost_watch(self):
        for ms in (700, 2000, 5000):
            run_on_ui_thread(self._ghost_silence, ms)

    def _install_playback_guards(self):
        MC = find_class("org.telegram.messenger.MediaController")
        if MC is None:
            return
        def add(name, before, after=None):
            with tolerated():
                u = self.hook_all_methods(MC, name, _TabHook(self, before, after))
                if u:
                    self._hooks.extend(u if isinstance(u, list) else [u])
        def adv_before(param):
            self._adv_until = time.time() + 2.0
        def adv_after(param):
            self._adv_until = 0.0
            self._adv_key = None
        for name in ("playNextMessage", "playPreviousMessage", "playNextMessageWithoutOrder"):
            add(name, adv_before, adv_after)
        def reset_progress(m):
            for f, v in (("forceSeekTo", -1.0), ("audioProgress", 0.0), ("audioProgressSec", 0)):
                with tolerated():
                    setattr(m, f, v)
        def pm_before(param):
            with tolerated():
                m = param.args[0] if param.args else None
                if m is None or not m.isMusic():
                    return
                mc = self._get_mc()
                cur = mc.getPlayingMessageObject() if mc is not None else None
                same = cur is not None and self._msg_key(cur) == self._msg_key(m)
                if same:
                    return
                if time.time() < self._adv_until:
                    self._adv_key = self._msg_key(m)
                    reset_progress(m)
        def pm_after(param):
            with tolerated():
                m = param.args[0] if param.args else None
                if m is None or self._adv_key is None or self._msg_key(m) != self._adv_key:
                    return
                self._adv_key = None
                if float(m.audioProgress) > 0.005 or int(m.audioProgressSec) > 0:
                    reset_progress(m)
                    mc = self._get_mc()
                    mc.seekToProgress(m, jfloat(0.0) if jfloat else 0.0)
        add("playMessage", pm_before, pm_after)
        add("pauseMessage", None, lambda param: self._ghost_watch())
        self._install_focus_guard(add)


    def _install_focus_guard(self, add):
        def clear_flag(param):
            with tolerated():
                mc = param.thisObject
                f = mc.getClass().getDeclaredField("resumeAudioOnFocusGain")
                f.setAccessible(True)
                f.setBoolean(mc, False)
        for name in ("playMessage", "pauseMessage", "cleanupPlayer"):
            add(name, None, clear_flag)

    UNDO_SECONDS = 5
    _pundo_token = 0
    _pundo_kind = None

    def _pundo_hide(self, hide_bulletin=True):
        self._pundo_token += 1
        self._pundo_kind = None
        h = getattr(self, "_pundo_h", None)
        for cb in (getattr(self, "_pundo_act", None), getattr(self, "_pundo_exp", None)):
            if cb is not None and h is not None:
                with tolerated():
                    h.removeCallbacks(cb)
        b = getattr(self, "_pundo_bulletin", None)
        self._pundo_bulletin = self._pundo_act = self._pundo_exp = None
        if hide_bulletin and b is not None:
            with tolerated():
                b.hide()

    def _pundo_start(self, text, restore, done_text, kind=None):
        def go():
            self._pundo_hide()
            _, _, Run = _proxies()
            h = getattr(self, "_pundo_h", None)
            if h is None:
                h = self._pundo_h = jclass("android.os.Handler")(jclass("android.os.Looper").getMainLooper())
            token = self._pundo_token
            self._pundo_kind = kind
            def undo_action():
                if token != self._pundo_token:
                    return
                self._pundo_hide()
                try:
                    ok = bool(restore())
                except Exception:
                    ok = False
                if ok:
                    try:
                        BulletinHelper.show_success(done_text, get_last_fragment())
                    except Exception:
                        self._bulletin(done_text)
                else:
                    self._bulletin(strings("queue_changed_cant_undo"), error=True)
            def expire_action():
                if token == self._pundo_token:
                    self._pundo_hide(hide_bulletin=False)
            self._pundo_act = Run(undo_action)
            self._pundo_exp = Run(expire_action)
            try:
                factory = find_class("org.telegram.ui.Components.BulletinFactory").of(get_last_fragment())
                b = factory.createUndoBulletin(text, self._pundo_act, self._pundo_exp)
                self._pundo_bulletin = b
                b.show()
            except Exception:
                try:
                    factory = find_class("org.telegram.ui.Components.BulletinFactory").of(get_last_fragment())
                    dur = int(getattr(find_class("org.telegram.ui.Components.Bulletin"), "DURATION_PROLONG",
                self.UNDO_SECONDS * 1000))
                    b = factory.createSimpleBulletin(0, text, strings("undo"), dur, False, self._pundo_act)
                    self._pundo_bulletin = b
                    b.show()
                    h.postDelayed(self._pundo_exp, self.UNDO_SECONDS * 1000)
                except Exception:
                    self._pundo_hide(hide_bulletin=False)
                    self._bulletin(text)
        run_on_ui_thread(go)

    _filter_entry = None
    _filter_skip = False

    def _filter_undo_notify(self, text):
        entry = self._filter_entry
        if not entry:
            self._bulletin(text)
            return
        now = time.time()
        if text == getattr(self, "_last_note", None) and now - getattr(self, "_last_note_t", 0) < 1.5:
            return
        self._last_note = text
        self._last_note_t = now
        self._pundo_start(text, lambda: self._filter_undo_restore(entry), strings("queue_unfiltered"), kind="filter")

    def _filter_undo_restore(self, entry):
        if entry is not self._filter_entry:
            return False
        mc = self._get_mc()
        pm = mc.getPlayingMessageObject() if mc is not None else None
        if pm is None:
            return False
        orig = entry["args"][0]
        keys = {self._msg_key(orig.get(i)) for i in range(int(orig.size()))}
        if self._msg_key(pm) not in keys:
            return False
        self._cancel_topic_hydration()
        self._unlock_playlist()
        pl = self._get_playlist(mc)
        if pl is None:
            return False
        items = [orig.get(i) for i in range(int(orig.size()))]
        pmap = get_private_field(mc, "playlistMap")
        pl.clear()
        if pmap is not None:
            pmap.clear()
        for m in items:
            if m is not None:
                pl.add(m)
                self._map_put(mc, m)
        self._finish_bulk_edit(mc, pl)
        self._filter_entry = None
        with tolerated():
            frag = get_last_fragment()
            self._name_queue(pm, frag, 0, None)
            if frag is not None and "ChatActivity" in str(frag.getClass().getName()):
                self._schedule_topic_queue_hydration(pm, 0, None, expected_filter="chat")
        with tolerated():
            ed = getattr(self, "_editor", None)
            if ed is not None:
                ed._reload()
        return True

    def _src_canon(self, key):
        return self._origin_chat_key(key) or key

    def _jump_in_queue(self, msg) -> bool:
        mc = self._get_mc()
        pl = self._get_playlist(mc) if mc is not None else None
        if pl is None or msg is None or int(pl.size()) == 0 or mc.getPlayingMessageObject() is None:
            return False
        mid, did = int(msg.getId()), int(msg.getDialogId())
        if self._index_of(pl, mid, did) < 0:
            if self.__dict__.get("_queue_build_state") is not None:
                return False
            if not self._playlist_append(msg):
                return False
            owned = getattr(self, "_lib_owned", None)
            if owned is not None:
                self._lib_owned = (frozenset(owned[0]) | {self._msg_key(msg)}, owned[1])
        prev_remote = bool(getattr(self, "_allow_remote", False))
        prev_bypass = bool(getattr(self, "_lib_bypass", False))
        self._allow_remote = True
        self._lib_bypass = True
        try:
            mc.playMessage(msg)
        finally:
            self._allow_remote = prev_remote
            self._lib_bypass = prev_bypass
        with tolerated():
            self._sync_order_to(mc, msg)
        with tolerated():
            ed = getattr(self, "_editor", None)
            if ed is not None:
                ed._on_track_changed()
        return True

    def _native_scope_key(self, args, current, fragment):
        uid = self._profile_activity_user_id(fragment, current)
        if uid:
            return ("profile_music", int(uid))
        did = int(current.getDialogId())
        global_search = self._global_search_params(args)
        if global_search is not None or self._is_media_search_active(fragment):
            q = (self._get_search_query(fragment) or self._search_query_from_params(global_search)
          or strings("search"))
            return (did, 0, str(q).strip().lower())
        topic_id = 0
        query = None
        if fragment is not None and "ChatActivity" in str(fragment.getClass().getName()):
            if self.get_setting("respect_topic", True):
                topic_id = self._detect_topic_id(fragment, current)
            if self.get_setting("respect_hashtag", True):
                query = self._get_search_query(fragment)
        return (did, int(topic_id or 0), (query or "").strip().lower())

    def _open_in_existing_queue(self, param) -> bool:
        try:
            if getattr(self, "_allow_remote", False) or getattr(self, "_lib_bypass", False):
                return False
            args = param.args
            current = args[1] if len(args) > 1 else None
            if current is None or not current.isMusic() or self._queue_scope_key is None:
                return False
            key = self._native_scope_key(args, current, get_last_fragment())
            if self._src_canon(key) != self._src_canon(self._queue_scope_key):
                return False
            if not self._jump_in_queue(current):
                return False
            param.setResult(None)
            return True
        except Exception:
            return False

    def _make_set_playlist_hook(self):
        plugin = self
        class SetPlaylistHook(MethodHook):
            def before_hooked_method(self, param):
                with tolerated():
                    if getattr(plugin, "_lib_bypass", False):
                        plugin._force_no_load_music(param)
                        return
                    if plugin._is_library_owned_queue(param.args[0] if param.args else None):
                        plugin._force_no_load_music(param)
                        return
                    if plugin._intercept_locked_playlist_build(param):
                        return
                    if plugin._open_in_existing_queue(param):
                        return
                    args = param.args
                    messages = args[0] if len(args) > 0 else None
                    current = args[1] if len(args) > 1 else None
                    if messages is None or current is None:
                        return
                    orig_args = list(args)
                    plugin._filter_entry = None
                    if plugin._pundo_kind == "filter":
                        plugin._pundo_hide()
                    size_in = messages.size()
                    block_more = True
                    fragment = get_last_fragment()
                    is_chat = (
                fragment is not None
                and "ChatActivity" in str(fragment.getClass().getName())
                )
                    global_search = plugin._global_search_params(args)
                    media_search = (
                global_search is not None
                or plugin._is_media_search_active(fragment)
                )
                    profile_uid = plugin._profile_activity_user_id(fragment, current)
                    if profile_uid:
                        plugin._unlock_playlist()
                        plugin._name_queue(current, fragment, 0, None)
                        return
                    if media_search:
                        search_query = (plugin._get_search_query(fragment)
                   or plugin._search_query_from_params(global_search))
                        if block_more:
                            plugin._force_no_load_music(param)
                            plugin._lock_playlist("media_search")
                        else:
                            plugin._unlock_playlist()
                        plugin._name_queue(current, fragment, 0, search_query or strings("search"))
                        if search_query:
                            plugin._schedule_topic_queue_hydration(
                      current, 0, search_query, expected_filter="media_search")
                        return
                    topic_id = 0
                    query = None
                    if is_chat:
                        if plugin.get_setting("respect_topic", True):
                            topic_id = plugin._detect_topic_id(fragment, current)
                        if plugin.get_setting("respect_hashtag", True):
                            query = plugin._get_search_query(fragment)
                    if topic_id == 0 and not query:
                        if plugin._active_filter is not None:
                            plugin._unlock_playlist()
                        plugin._name_queue(current, fragment, 0, None)
                        if is_chat:
                            plugin._schedule_topic_queue_hydration(current, 0, None, expected_filter="chat")
                        return
                    plugin._name_queue(current, fragment, topic_id, query)
                    filtered = plugin._filter_messages(messages, topic_id, query, current)
                    changed = (
                filtered is not None
                and 0 < filtered.size() < size_in
                )
                    if changed:
                        param.args[0] = filtered
                    if block_more:
                        plugin._force_no_load_music(param)
                        plugin._lock_playlist(("filter", topic_id, query))
                    else:
                        plugin._unlock_playlist()
                    if topic_id or query:
                        if changed or block_more:
                            plugin._filter_entry = {"args": orig_args, "full": True}
                        plugin._schedule_topic_queue_hydration(current, topic_id, query)
                    if changed:
                        n = filtered.size()
                        parts = []
                        if topic_id:
                            parts.append("topic")
                        if query:
                            parts.append("search")
                        plugin._filter_undo_notify(strings("queue_filtered_n_n_tracks", ' + '.join(parts), n))
        return SetPlaylistHook()

    def _make_load_more_hook(self):
        plugin = self
        class LoadMoreHook(MethodHook):
            def before_hooked_method(self, param):
                if plugin._active_filter is None:
                    return
                with tolerated():
                    mc = plugin._get_mc()
                    if mc is not None and get_private_field(mc, "playlistGlobalSearchParams") is not None:
                        return
                param.setResult(None)
        return LoadMoreHook()

    def _filter_messages(self, messages, topic_id, search_query, current_message):
        try:
            filtered = ArrayList()
            q = (search_query or "").strip().lower()
            cur_id = cur_dialog = None
            if current_message is not None:
                with tolerated():
                    cur_id = current_message.getId()
                    cur_dialog = current_message.getDialogId()
            has_current = False
            for i in range(messages.size()):
                msg = messages.get(i)
                if msg is None:
                    continue
                try:
                    if not msg.isMusic():
                        continue
                except Exception:
                    continue
                is_current = False
                with tolerated():
                    is_current = cur_id is not None and msg.getId() == cur_id and msg.getDialogId() == cur_dialog
                keep = is_current
                if not keep:
                    keep = True
                    if topic_id != 0:
                        mt = self._get_message_topic_id(msg, general=True)
                        if mt != 0 and mt != topic_id:
                            keep = False
                    if keep and q and not self._message_matches_query(msg, q):
                        keep = False
                if keep:
                    filtered.add(msg)
                    has_current = has_current or is_current
            if current_message is not None and not has_current:
                filtered.add(0, current_message)
            return filtered if filtered.size() > 0 else None
        except Exception:
            return None

    def _message_matches_query(self, msg, q: str) -> bool:
        parts = []
        def add(val):
            with tolerated():
                if val:
                    parts.append(str(val))
        add(getattr(msg, "messageText", None))
        add(getattr(msg, "caption", None))
        for getter in ("getMusicTitle", "getMusicAuthor", "getFileName"):
            with tolerated():
                add(getattr(msg, getter)())
        with tolerated():
            add(msg.messageOwner.message)
        return q in " ".join(parts).lower()

    def _get_message_topic_id(self, msg, general: bool = True) -> int:
        if msg is None:
            return 0
        owner = getattr(msg, "messageOwner", None)
        with tolerated():
            MessageObject = find_class("org.telegram.messenger.MessageObject")
            tid = self._to_int(
          MessageObject.getTopicId(msg.currentAccount, owner, bool(general))
          )
            if tid:
                return tid
        with tolerated():
            rt = getattr(owner, "reply_to", None) if owner is not None else None
            if rt is not None and bool(getattr(rt, "forum_topic", False)):
                for attr in ("reply_to_top_id", "reply_to_msg_id"):
                    val = self._to_int(getattr(rt, attr, 0))
                    if val:
                        return val
        return 0

    def _detect_topic_id(self, act, current) -> int:
        tid = self._to_int(self._read(act, *TOPIC_ID_NAMES))
        if tid:
            return tid
        flag = self._read_flag(act, TOPIC_FLAG_NAMES)
        if flag is True:
            return self._get_message_topic_id(current, general=True)
        if flag is None:
            return self._get_message_topic_id(current, general=False)
        return 0

    def _get_search_query(self, act) -> Optional[str]:
        val = self._read(act, *SEARCH_QUERY_NAMES)
        try:
            s = str(val).strip() if val is not None else ""
        except Exception:
            s = ""
        return s or None

    def _is_media_search_active(self, fragment) -> bool:
        if fragment is None:
            return False
        try:
            cls = str(fragment.getClass().getName())
        except Exception:
            cls = ""
        if "MediaActivity" in cls or "ProfileActivity" in cls:
            if self._read_flag(fragment, ("searching", "searchWas")):
                return True
        layout = self._read(fragment, "sharedMediaLayout")
        if layout is not None and self._read_flag(layout, ("searching", "searchWas")):
            return True
        return False
