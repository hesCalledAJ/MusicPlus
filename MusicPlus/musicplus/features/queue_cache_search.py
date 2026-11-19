import threading
import time
from ..compat import ArrayList, Boolean, MethodHook, Optional, get_last_fragment, jclass, run_on_ui_thread
from elyx import strings
from ..telegram_io import _MusicFetcher, _TLCodec
from ..stores import _LazyTracks
from ..sheets import _ActionSheet
from ..safe import tolerated


class _PluginQueueCacheSearch:
    @staticmethod
    def _called_from_mini_player() -> bool:
        with tolerated():
            for el in jclass("java.lang.Thread").currentThread().getStackTrace():
                if "FragmentContextView" in str(el.getClassName()):
                    return True
        return False

    def _make_cleanup_hook(self):
        plugin = self
        class CleanupHook(MethodHook):
            def before_hooked_method(self, param):
                with tolerated():
                    plugin._rs_note()
                with tolerated():
                    if (len(param.args) >= 2 and bool(param.args[0]) and bool(param.args[1])
                            and plugin._called_from_mini_player()):
                        plugin._rs_hold_closed()
                try:
                    if (not plugin.get_setting("lock_queue", False)
                or getattr(plugin, "_cleanup_ok", False)
                or not plugin._called_from_mini_player()):
                        return
                    args = [bool(a) for a in param.args]
                except Exception:
                    return
                param.setResult(None)
                run_on_ui_thread(lambda: plugin._confirm_close_player(args))
        return CleanupHook()

    def _confirm_close_player(self, args):
        frag = get_last_fragment()
        act = frag.getParentActivity() if frag is not None else None
        if act is None:
            return
        def confirm():
            with tolerated():
                self.set_setting("lock_queue", False)
            self._cleanup_ok = True
            try:
                mc = self._get_mc()
                if mc is not None:
                    mc.cleanupPlayer(*args)
            except Exception:
                pass
            finally:
                self._cleanup_ok = False
        _ActionSheet(self, act).show_sheet(
       strings("close_player"), strings("the_queue_is_locked"),
       [(strings("close_and_unlock_queue"), strings("turns_off_lock_queue"), True, confirm)])

    @staticmethod
    def _force_no_load_music(param) -> bool:
        args = param.args
        for i in range(2, len(args)):
            if isinstance(args[i], (bool, Boolean)):
                param.args[i] = False
                return True
        return False

    @staticmethod
    def _global_search_params(args):
        for i in range(3, len(args)):
            a = args[i]
            if a is None or isinstance(a, (bool, int, float, Boolean)):
                continue
            try:
                if "PlaylistGlobalSearchParams" in str(a.getClass().getName()):
                    return a
            except Exception:
                continue
        return None

    def _search_query_from_params(self, params) -> Optional[str]:
        value = self._read(params, "query", "searchQuery", "searchingQuery", "q",
       "getQuery", "getSearchQuery")
        try:
            text = str(value or "").strip()
        except Exception:
            text = ""
        return text or None

    def _cancel_topic_hydration(self):
        with tolerated():
            fetcher = getattr(self, "_topic_fetcher", None)
            if fetcher is not None:
                fetcher.cancel()
        with tolerated():
            sheet = getattr(self, "_topic_progress_sheet", None)
            if sheet is not None:
                sheet.close()
        pk = getattr(self, "_topic_pkey", None)
        if pk is not None:
            with tolerated():
                self._activity_status(pk, None)
                self._prog_end(pk)
            self._topic_pkey = None
        self._topic_fetcher = None
        self._topic_progress_sheet = None
        self._topic_hydration_scope = None
        self._queue_hydration_expected = None
        self._queue_hydration_open = False
        self._topic_hydration_generation = int(getattr(self, "_topic_hydration_generation", 0)) + 1
        with tolerated():
            editor = getattr(self, "_editor", None)
            if editor is not None:
                run_on_ui_thread(editor._update_title)

    def _schedule_topic_queue_hydration(self, current, topic_id, query, expected_filter=None):
        try:
            dialog_id = int(current.getDialogId())
            topic_id = int(topic_id)
            query = str(query or "").strip()
        except Exception:
            return
        if not dialog_id:
            return
        if expected_filter is None:
            if not topic_id and not query:
                return
            expected_filter = ("filter", topic_id, query or None)
        scope = (dialog_id, topic_id, query, expected_filter)
        if scope == getattr(self, "_topic_hydration_scope", None):
            return
        self._cancel_topic_hydration()
        self._topic_hydration_scope = scope
        generation = self._topic_hydration_generation
        if not query:
            cn = self._lib_cached_chat_count(dialog_id, topic_id)
            cap_now = self._max_queue_songs()
            if cap_now and cn:
                cn = min(cn, cap_now)
            if cn:
                self._queue_hydration_expected = cn
                self._queue_hydration_open = False
                with tolerated():
                    editor = getattr(self, "_editor", None)
                    if editor is not None:
                        run_on_ui_thread(editor._update_title)
        self._post(lambda: self._start_topic_queue_hydration(current, scope, generation), 250)

    def _start_topic_queue_hydration(self, tapped_message, scope, generation):
        if generation != getattr(self, "_topic_hydration_generation", -1):
            return
        dialog_id, topic_id, query, expected_filter = scope
        scope_label = (strings("search_results").lower() if query and not topic_id
       else strings("topic_search_results") if query
       else strings("this_topic") if topic_id else strings("this_chat"))
        def filter_matches():
            if expected_filter == "chat":
                return self._active_filter is None
            return self._active_filter == expected_filter
        if not filter_matches():
            return
        try:
            mc = self._get_mc()
            pl = self._get_playlist(mc) if mc is not None else None
            if mc is None or pl is None or pl.size() == 0:
                self._topic_hydration_scope = None
                return
            acc = self._chat_account(get_last_fragment(), [tapped_message])
            if acc is None:
                acc = int(getattr(tapped_message, "currentAccount", 0) or 0)
            pkey = ("topic_hydrate", int(dialog_id), int(topic_id))
            self._topic_pkey = pkey
            queue_scope = (int(dialog_id), int(topic_id), str(query or "").strip().lower())
            state = {"keys": None, "desc": None, "pending": [], "last": 0.0, "sent": False, "refresh_pending": False, "last_progress": 0.0, "last_refresh": 0.0, "cache_mode": False}
            def alive():
                return (generation == getattr(self, "_topic_hydration_generation", -1)
             and filter_matches() and getattr(self, "_queue_scope_key", None) == queue_scope)
            def prepare(items):
                used = list(items or [])
                if (topic_id or query) and used:
                    with tolerated():
                        mc_now = self._get_mc()
                        pm = mc_now.getPlayingMessageObject() if mc_now is not None else None
                        if pm is not None and int(pm.getDialogId()) != int(dialog_id):
                            pm = None
                        arr = ArrayList()
                        for item in used:
                            if item is not None:
                                arr.add(item)
                        filtered = self._filter_messages(arr, topic_id, query, pm)
                        used = [filtered.get(i) for i in range(filtered.size())] if filtered is not None else []
                return used
            def refresh_editor():
                editor = getattr(self, "_editor", None)
                if editor is None:
                    return
                with tolerated():
                    mc_now = self._get_mc()
                    pl_now = self._get_playlist(mc_now) if mc_now is not None else None
                    if pl_now is None:
                        return
                    now = time.monotonic()
                    scrolling = editor.tab == "queue" and (editor.drag is not None or
                now - getattr(editor, "_last_scroll_change", 0.0) < 0.24)
                    gap = 0.14 + 0.00012 * int(pl_now.size())
                    throttled = editor.tab == "queue" and now - state["last_refresh"] < gap
                    if scrolling or throttled:
                        editor.pl_size = int(pl_now.size())
                        if not state["refresh_pending"]:
                            state["refresh_pending"] = True
                            delay = 270 if scrolling else max(55, int((gap - (now - state["last_refresh"])) * 1000) + 25)
                            def delayed_refresh():
                                state["refresh_pending"] = False
                                if alive():
                                    refresh_editor()
                            editor.handler.postDelayed(editor.Run(delayed_refresh), delay)
                        return
                    state["last_refresh"] = now
                    shuffle_on, rev = self._read_order()
                    reversed_now = bool(rev and not shuffle_on)
                    raw = [pl_now.get(i) for i in range(int(pl_now.size()))]
                    new_items = raw if reversed_now else raw[::-1]
                    new_keys = [editor._key(m) for m in new_items]
                    old_keys = list(getattr(editor, "keys", ()) or ())
                    old_len = len(old_keys)
                    old_end = int(editor.win_end)
                    editor.reversed = reversed_now
                    editor.items = new_items
                    editor.keys = new_keys
                    editor.pl_size = len(raw)
                    editor.ghost = False
                    playing = mc_now.getPlayingMessageObject() if mc_now is not None else None
                    new_playing = editor._key(playing) if playing is not None else None
                    changed_playing = new_playing != editor.playing_key
                    editor.playing_key = new_playing
                    if editor.tab != "queue":
                        editor._rebuild_key_index()
                        return
                    prefix = suffix = 0
                    contiguous = False
                    if old_len and old_len <= len(new_keys):
                        with tolerated():
                            first = new_keys.index(old_keys[0])
                            if new_keys[first:first + old_len] == old_keys:
                                prefix = first
                                suffix = len(new_keys) - first - old_len
                                contiguous = True
                    if not contiguous:
                        editor.win_start = editor.win_end = 0
                        editor.queue_lazy_ready = False
                        editor._refresh(True)
                        return
                    if prefix:
                        editor._shift_queue_rows(prefix)
                        editor.win_start += prefix
                        editor.win_end += prefix
                        editor.queue_data_token += 1
                        editor.queue_load_pending = False
                    editor._rebuild_key_index()
                    editor.queue_lazy_ready = True
                    if not editor.rows and new_items:
                        editor.win_start = editor.win_end = 0
                        editor._refresh(True)
                        return
                    if suffix and old_end == old_len and old_len < editor.QUEUE_BATCH_ROWS:
                        target_end = min(len(new_items), old_end + max(0, editor.QUEUE_BATCH_ROWS - len(editor.rows)))
                        if target_end > editor.win_end:
                            editor._append_queue_rows(editor.win_end, target_end)
                    if changed_playing:
                        pi = editor._playing_pos()
                        for i in list(editor.row_refs.keys()):
                            editor._style_row(i, pi)
                        editor._styled_playing = pi
                    editor._update_title()
                    editor._update_locate_visibility()
                    editor.handler.postDelayed(editor.Run(editor._maybe_load_queue_rows), 60)
                    if suffix and editor.win_end > old_end:
                        editor.handler.postDelayed(editor.Run(editor._load_visible_covers), 40)
            def insert(items, final=False, prep=None):
                if not alive():
                    return False
                mc_now = self._get_mc()
                pl_now = self._get_playlist(mc_now) if mc_now is not None else None
                pm = mc_now.getPlayingMessageObject() if mc_now is not None else None
                if pl_now is None or pm is None or int(pm.getDialogId()) != int(dialog_id):
                    return False
                if items or final:
                    if not self._queue_insert_sorted(items, state, final, prep):
                        return False
                    refresh_editor()
                return True
            def on_progress(count, total):
                if alive():
                    if cap:
                        count = min(int(count or 0), cap)
                        total = min(int(total or 0), cap) if total else total
                    expected = max(int(count or 0), int(total or 0))
                    if expected:
                        if not state["cache_mode"] and total and total >= count:
                            self._queue_hydration_expected = int(total)
                        else:
                            self._queue_hydration_expected = max(expected, int(getattr(self, "_queue_hydration_expected", 0) or 0))
                    if not state["cache_mode"]:
                        self._queue_hydration_open = not (total and total >= count)
                    now = time.time()
                    if now - state["last_progress"] < 0.65 and count != total:
                        return
                    state["last_progress"] = now
                    status = strings("loading_n_n_tracks", scope_label, count)
                    if total and total >= count:
                        status = strings("loading_n_n_of_n_tracks", scope_label, count, total)
                    self._activity_status(pkey, status)
                    self._prog_set(pkey, count, total if total and total >= count else 0)
                    editor = getattr(self, "_editor", None)
                    if editor is not None:
                        with tolerated():
                            editor._update_title()
            def on_batch(batch, count, total):
                if not alive():
                    return
                if cap and not state["cache_mode"]:
                    room = cap - int(state.get("got", 0))
                    if room <= 0:
                        return
                    batch = list(batch)[:room]
                    state["got"] = int(state.get("got", 0)) + len(batch)
                state["pending"].extend(batch)
                now = time.time()
                if state.get("ui_busy"):
                    return
                if not state["cache_mode"] and len(state["pending"]) < 400 and now - state["last"] < 0.8:
                    return
                items, state["pending"] = state["pending"], []
                state["last"] = now
                state["sent"] = True
                with tolerated():
                    ready = prepare(items)
                    prep = None
                    with tolerated():
                        prep = self._queue_prep(ready, state)
                    state["ui_busy"] = True
                    def merge_on_ui(r=ready, pp=prep):
                        state["ui_busy"] = False
                        insert(r, False, pp)
                    run_on_ui_thread(merge_on_ui)
            def finish_loaded(items, error):
                if generation != getattr(self, "_topic_hydration_generation", -1):
                    return
                if not filter_matches():
                    return
                if items:
                    ready = prepare(items)
                else:
                    ready = []
                def finish_ui():
                    if generation != getattr(self, "_topic_hydration_generation", -1):
                        return
                    self._activity_status(pkey, None)
                    self._prog_end(pkey)
                    self._topic_fetcher = None
                    if not alive():
                        self._queue_hydration_expected = None
                        self._queue_hydration_open = False
                        self._topic_hydration_scope = None
                        return
                    if not insert(ready, True):
                        self._topic_hydration_scope = None
                        self._queue_hydration_expected = None
                        self._queue_hydration_open = False
                        return
                    self._queue_hydration_expected = None
                    self._queue_hydration_open = False
                    self._topic_hydration_scope = None
                    mc_now = self._get_mc()
                    pl_now = self._get_playlist(mc_now) if mc_now is not None else None
                    n = int(pl_now.size()) if pl_now is not None else 0
                    if error:
                        self._bulletin(strings("loaded_n_tracks_from_n_partial", n, scope_label), error=True)
                    else:
                        pass
                    refresh_editor()
                run_on_ui_thread(finish_ui)
            def on_done(tracks, error, cancelled):
                if cancelled:
                    self._activity_status(pkey, None)
                    self._prog_end(pkey)
                    self._topic_fetcher = None
                    if generation == getattr(self, "_topic_hydration_generation", -1):
                        self._topic_hydration_scope = None
                        self._queue_hydration_expected = None
                        self._queue_hydration_open = False
                    return
                if error and not tracks and not state["pending"] and not state["sent"]:
                    self._activity_status(pkey, None)
                    self._prog_end(pkey)
                    self._topic_fetcher = None
                    if generation == getattr(self, "_topic_hydration_generation", -1):
                        self._topic_hydration_scope = None
                        self._queue_hydration_expected = None
                        self._queue_hydration_open = False
                        self._bulletin(strings("couldnt_load_all_n", scope_label), error=True)
                    return
                items, state["pending"] = state["pending"], []
                if not items and tracks and not state["sent"]:
                    items = tracks[-cap:] if cap else tracks
                if items:
                    def work():
                        with tolerated():
                            finish_loaded(items, error)
                    threading.Thread(target=work, daemon=True, name="smq-queue-hydrate-finish").start()
                else:
                    finish_loaded([], error)
            cap = self._max_queue_songs()
            known_count = 0 if query else self._lib_cached_chat_count(dialog_id, topic_id)
            if cap and known_count:
                known_count = min(known_count, cap)
            self._queue_hydration_expected = known_count or None
            self._queue_hydration_open = not known_count
            self._activity_status(pkey, strings("loading_n_2", scope_label))
            self._prog_set(pkey, 0, 0)
            library_has_chat = False
            if not query:
                with tolerated():
                    library_has_chat = any(
                int(c.get("d", 0)) == int(dialog_id) and int(c.get("t", 0)) == int(topic_id)
                for c in (self._lib_data().get("chats", []) or []) if isinstance(c, dict))
            def start_remote_fetch():
                if not alive():
                    return
                def start_on_ui():
                    if not alive():
                        return
                    fetcher = _MusicFetcher(self, acc, dialog_id, topic_id, on_progress, on_done,
                query=query, on_batch=on_batch, batch_on_ui=False, cap=cap)
                    self._topic_fetcher = fetcher
                    fetcher.start()
                run_on_ui_thread(start_on_ui)
            if library_has_chat:
                state["cache_mode"] = True
                def load_library_cache():
                    cached_items = []
                    try:
                        cached = self._chat_track_cache.get((int(dialog_id), int(topic_id)))
                        if cached is not None and len(cached):
                            idx = getattr(cached, "_idx", None)
                            objs = getattr(cached, "_objs", None)
                            if objs is not None:
                                cached_items = [m for m in objs if m is not None]
                            elif idx is not None:
                                seen = set()
                                rows_iter = sorted(idx.rows, key=lambda r: -int(r.get("i", 0) or 0))
                                if cap:
                                    rows_iter = rows_iter[:cap]
                                with open(idx.path, "rb") as fh:
                                    for row in rows_iter:
                                        if not alive():
                                            return
                                        try:
                                            fh.seek(int(row["o"]))
                                            blob = fh.read(int(row["l"]))
                                            m = _TLCodec.load(int(idx.acc), int(row["d"]), blob) if blob else None
                                            if m is None:
                                                continue
                                            k = self._msg_key(m)
                                            if k is not None and k in seen:
                                                continue
                                            if k is not None:
                                                seen.add(k)
                                            cached_items.append(m)
                                            if k is not None:
                                                with tolerated():
                                                    self._msg_cache[k] = m
                                        except Exception:
                                            continue
                        elif cached is not None:
                            cached_items = [m for m in cached if m is not None]
                    except Exception:
                        cached_items = []
                    if cap and len(cached_items) > cap:
                        cached_items = sorted(cached_items, key=lambda m: -int(m.getId()))[:cap]
                    if not alive():
                        return
                    if not cached_items:
                        state["cache_mode"] = False
                        start_remote_fetch()
                        return
                    total = len(cached_items)
                    def show_cached_status():
                        if alive():
                            self._queue_hydration_expected = total
                            self._activity_status(pkey, strings("loading_n_cached_tracks", total))
                    run_on_ui_thread(show_cached_status)
                    for offset in range(0, total, 160):
                        if not alive():
                            return
                        batch = cached_items[offset:offset + 160]
                        loaded = min(total, offset + len(batch))
                        on_batch(batch, loaded, total)
                        run_on_ui_thread(lambda c=loaded, t=total: on_progress(c, t) if alive() else None)
                    newest = 0
                    for m in cached_items:
                        with tolerated():
                            newest = max(newest, int(m.getId()))
                    if not newest or not alive():
                        on_done([], None, False)
                        return
                    def delta_progress(count, total_):
                        if not alive():
                            return
                        self._queue_hydration_expected = max(total + int(count or 0), int(getattr(self, "_queue_hydration_expected", 0) or 0))
                        self._queue_hydration_open = False
                        self._activity_status(pkey, strings("checking_n_for_new_tracks", scope_label))
                        editor = getattr(self, "_editor", None)
                        if editor is not None:
                            with tolerated():
                                editor._update_title()
                    def delta_done(tracks, error, cancelled):
                        self._topic_fetcher = None
                        if cancelled:
                            on_done([], None, True)
                            return
                        new = list(tracks or [])
                        def merge():
                            self._chat_cache_merge_new((int(dialog_id), int(topic_id)), prepare(new), acc)
                        if new:
                            threading.Thread(target=merge, daemon=True, name="smq-cache-delta-merge").start()
                        on_done(new, None, False)
                    def start_delta():
                        if not alive():
                            on_done([], None, True)
                            return
                        self._queue_hydration_open = False
                        fetcher = _MusicFetcher(self, acc, dialog_id, topic_id, delta_progress, delta_done,
                  query=query, min_id=newest, on_batch=on_batch, batch_on_ui=False)
                        self._topic_fetcher = fetcher
                        fetcher.start()
                    run_on_ui_thread(start_delta)
                threading.Thread(target=load_library_cache, daemon=True, name="smq-library-queue-cache").start()
            else:
                start_remote_fetch()
        except Exception:
            self._topic_hydration_scope = None
            self._topic_fetcher = None
            self._topic_progress_sheet = None

    def _intercept_locked_playlist_build(self, param) -> bool:
        with tolerated():
            if getattr(self, "_allow_remote", False):
                return False
            if not self.get_setting("lock_queue", False):
                return False
            args = param.args
            msg = args[1] if len(args) > 1 else None
            if msg is None:
                return False
            try:
                if not msg.isMusic():
                    return False
                msg_id, dialog_id = int(msg.getId()), int(msg.getDialogId())
            except Exception:
                return False
            mc = self._get_mc()
            playlist = self._get_playlist(mc) if mc is not None else None
            if mc is None or playlist is None or playlist.size() == 0:
                return False
            if self._index_of(playlist, msg_id, dialog_id) >= 0:
                return False
            try:
                mode = int(self.get_setting("locked_queue_behavior", 2))
            except Exception:
                mode = 2
            if mode not in (0, 1, 2):
                mode = 2
            if mode == 0:
                param.setResult(None)
                def add_next():
                    if not self._queue_next(msg):
                        self._bulletin(strings("queue_is_locked_but_this_track_2"), error=True)
                    else:
                        self._bulletin(strings("added_to_play_next"))
                run_on_ui_thread(add_next)
                return True
            if mode == 1:
                param.setResult(None)
                def add_end():
                    if not self._playlist_append(msg):
                        self._bulletin(strings("queue_is_locked_but_this_track"), error=True)
                    else:
                        self._bulletin(strings("added_to_the_end_of_the"))
                run_on_ui_thread(add_end)
                return True
            if mode == 2:
                param.setResult(None)
                run_on_ui_thread(lambda: self._show_tap_behavior_menu(msg))
                return True
        return False

    _MAX_QUEUE_STEPS = (250, 500, 1000, 2000, 5000, 10000, 0)

    def _max_queue_songs(self):
        try:
            idx = int(self.get_setting("max_queue_songs", 2))
        except Exception:
            idx = 2
        steps = self._MAX_QUEUE_STEPS
        return steps[idx] if 0 <= idx < len(steps) else 1000

    def _lib_cached_chat_count(self, dialog_id, topic_id):
        with tolerated():
            for c in (self._lib_data().get("chats", []) or []):
                if (isinstance(c, dict) and int(c.get("d", 0)) == int(dialog_id)
             and int(c.get("t", 0)) == int(topic_id)):
                    return max(0, int(c.get("cn", 0) or 0))
        return 0

    def _chat_cache_merge_new(self, key, new, acc):
        with tolerated():
            new = [m for m in (new or []) if m is not None]
            if not new:
                return
            cache = self._chat_track_cache
            old = cache.revive(key)
            merged = None
            if old is not None and getattr(old, "rows", None) is not None:
                try:
                    use_acc = int(old._idx.acc)
                except Exception:
                    use_acc = int(acc)
                nidx = self._tstore.append(key, new, use_acc)
                if nidx is not None:
                    merged = _LazyTracks(cache, key, idx=nidx)
            elif old is not None and getattr(old, "_objs", None) is not None:
                by_key = {}
                for item in list(new) + list(old._objs or []):
                    with tolerated():
                        by_key[(int(item.getId()), int(item.getDialogId()))] = item
                merged = sorted(by_key.values(), key=lambda m: -int(m.getId()))
            if merged is None:
                return
            def commit():
                with tolerated():
                    cache[key] = merged
                    self.__dict__.setdefault("_lib_fresh", {})[("c",) + tuple(key)] = time.time()
                    self._request_library_refresh()
            run_on_ui_thread(commit)

    def _is_library_owned_queue(self, messages) -> bool:
        owned = getattr(self, "_lib_owned", None)
        if owned is None or messages is None:
            return False
        try:
            if int(messages.size()) != len(owned[0]):
                return False
            keys = {self._msg_key(messages.get(i)) for i in range(int(messages.size()))}
            return keys == set(owned[0]) and self._queue_scope_key == owned[1]
        except Exception:
            return False

    _adv_until = 0.0
