import random
import threading
import time
from ..compat import (
 MethodHook,
 find_class,
 get_last_fragment,
 get_media_controller,
 get_private_field,
 jclass,
 jint,
 run_on_ui_thread,
 set_private_field,
)
from elyx import strings
from ..tabs import _TabHook
from ..crossfade import _Blend, _XfHook, _xf_widest
from ..sheets import _ActionSheet, _jc
from ..safe import tolerated
from .. import availability as _avail


class _PluginPlaylists:
    def _schedule_deleted_check(self, msg, delay):
        try:
            key = (int(msg.getDialogId()), int(msg.getId()))
        except Exception:
            return
        checked = self.__dict__.setdefault("_del_checked", {})
        now = time.time()
        if now - checked.get(key, 0) < 900 or now - self.__dict__.get("_del_last", 0) < 2.0:
            return
        def later():
            with tolerated():
                if self._is_downloaded(msg):
                    return
                mc = self._get_mc()
                pm = mc.getPlayingMessageObject() if mc is not None else None
                if pm is not None and (int(pm.getDialogId()), int(pm.getId())) == key:
                    with tolerated():
                        if int(pm.audioProgressSec) > 0 or float(pm.audioProgress) > 0.0:
                            return
                if not self._net_ok():
                    return
                checked[key] = time.time()
                self.__dict__["_del_last"] = time.time()
                threading.Thread(target=self._verify_deleted, args=(msg,), daemon=True).start()
        def fire():
            run_on_ui_thread(later)
        t = threading.Timer(float(delay), fire)
        t.daemon = True
        t.start()


    def _server_probe(self, msg):
        acc, did, mid = int(msg.currentAccount), int(msg.getDialogId()), int(msg.getId())
        MCtl = _jc("org.telegram.messenger.MessagesController").getInstance(acc)
        channel = False
        if did < 0:
            chat = MCtl.getChat(-did)
            if chat is None:
                return None
            channel = bool(_jc("org.telegram.messenger.ChatObject").isChannel(chat))
        if channel:
            req = _jc("org.telegram.tgnet.TLRPC$TL_channels_getMessages")()
            ic = MCtl.getInputChannel(-did)
            if ic is None:
                return None
            req.channel = ic
        else:
            req = _jc("org.telegram.tgnet.TLRPC$TL_messages_getMessages")()
        try:
            im = _jc("org.telegram.tgnet.TLRPC$TL_inputMessageID")()
            im.id = mid
            req.id.add(im)
        except Exception:
            req.id.add(jclass("java.lang.Integer")(int(mid)))
        res, err = self._pm_rpc(acc, req, lambda: False, timeout=15.0, retries=0)
        if err is not None or res is None:
            return None
        try:
            lst = res.messages
            for i in range(int(lst.size())):
                m = lst.get(i)
                if int(m.id) != mid:
                    continue
                name = str(m.getClass().getSimpleName())
                if name == "TL_messageEmpty":
                    return "deleted"
                return "removed" if self._tl_audio_stripped(m) else "ok"
        except Exception:
            return None
        return None

    @staticmethod
    def _tl_audio_stripped(m):
        if _avail.restricted_reason(getattr(m, "restriction_reason", None)):
            return True
        media = getattr(m, "media", None)
        if media is None:
            return True
        mn = _avail._name(media)
        if mn in ("TL_messageMediaEmpty", "TL_messageMediaUnsupported"):
            return True
        if mn == "TL_messageMediaDocument":
            doc = getattr(media, "document", None)
            return doc is None or _avail._name(doc).lower().endswith("documentempty")
        return False

    def _mark_media_removed(self, msg):
        k = _avail.key_of(msg)
        if k is None or k in _avail.removed:
            return
        _avail.removed.add(k)
        with tolerated():
            if self._is_loading(msg):
                self._cancel_load(msg)
        def refresh():
            with tolerated():
                ed = getattr(self, "_editor", None)
                if ed is not None and ed.dialog.isShowing():
                    ed.dl_cache.pop(k, None)
                    ed._refresh_dl()
        run_on_ui_thread(refresh)

    def _verify_deleted(self, msg):
        with tolerated():
            did, mid = int(msg.getDialogId()), int(msg.getId())
            state = self._server_probe(msg)
            if state == "removed":
                self._mark_media_removed(msg)
                return
            if state != "deleted":
                return
            removed = self._prune_deleted_track(did, mid)
            if removed:
                def refresh():
                    with tolerated():
                        ed = getattr(self, "_editor", None)
                        if ed is not None and ed.dialog.isShowing() and ed.tab == "library":
                            ed._lib_render()
                run_on_ui_thread(refresh)

    def _prune_deleted_track(self, did, mid):
        cache = self._chat_track_cache
        removed = 0
        for ck in list(cache.keys()):
            with tolerated():
                if int(ck[0]) != did:
                    continue
                lz = cache.get(ck)
                if lz is None:
                    continue
                rows = getattr(lz, "rows", None)
                if rows is not None and not any(int(r.get("i", 0)) == mid for r in rows):
                    continue
                objs = [m for m in lz if m is not None]
                keep = [m for m in objs if int(m.getId()) != mid]
                if len(keep) == len(objs):
                    continue
                if keep:
                    cache[ck] = keep
                else:
                    cache.forget(ck)
                removed += 1
        return removed

    def _install_offline_hook(self):
        MediaController = find_class("org.telegram.messenger.MediaController")
        if MediaController is None:
            return
        plugin = self
        class OfflineHook(MethodHook):
            def before_hooked_method(self, param):
                with tolerated():
                    if not plugin._offline_active() or not param.args:
                        return
                    target = param.args[0]
                    if target is None:
                        return
                    res = plugin._offline_target(target)
                    if res is None:
                        return
                    if res is False:
                        param.setResult(False)
                        plugin._notify_once(strings("offline_mode_no_more_downloaded_tracks"))
                        return
                    param.args[0] = res
                    plugin._offline_fix = True
            def after_hooked_method(self, param):
                if not getattr(plugin, "_offline_fix", False):
                    return
                plugin._offline_fix = False
                with tolerated():
                    mc = plugin._get_mc()
                    plugin._resync_current(mc, plugin._get_playlist(mc))
        unhooks = self.hook_all_methods(MediaController, "playMessage", OfflineHook())
        if unhooks:
            self._hooks.extend(unhooks if isinstance(unhooks, list) else [unhooks])

    def _queue_next(self, msg) -> bool:
        mc = self._get_mc()
        pl = self._get_playlist(mc) if mc is not None else None
        return bool(pl is not None and self._queue_bulk_insert(mc, pl, [msg], True))

    def _queue_remove(self, msg) -> bool:
        mc = self._get_mc()
        pl = self._get_playlist(mc) if mc is not None else None
        if pl is None:
            return False
        ok = self._playlist_remove_by_id(mc, pl, msg.getId(), msg.getDialogId())
        self._resync_current(mc, pl)
        return ok

    @staticmethod
    def _is_player_alert(obj) -> bool:
        try:
            return obj is not None and "AudioPlayerAlert" in str(obj.getClass().getName())
        except Exception:
            return False

    def _install_player_hooks(self):
        BottomSheet = find_class("org.telegram.ui.ActionBar.BottomSheet")
        if BottomSheet is None:
            return
        plugin = self
        class PlayerShowHook(MethodHook):
            def before_hooked_method(self, param):
                with tolerated():
                    obj = param.thisObject
                    if not plugin._is_player_alert(obj):
                        return
                    if getattr(plugin, "_native_once", False):
                        plugin._native_once = False
                        return
                    if plugin._own_profile_queue():
                        plugin._blocked_alert = obj
                        param.setResult(None)
                        try:
                            run_on_ui_thread(lambda: plugin._open_own_profile_playlist(obj))
                        except Exception:
                            plugin._open_own_profile_playlist(obj)
                        return
                    mc = plugin._get_mc()
                    pl = plugin._get_playlist(mc) if mc is not None else None
                    if pl is None or pl.size() == 0 or plugin._playing_key(mc) is None:
                        return
                    plugin._blocked_alert = obj
                    param.setResult(None)
                    def _go():
                        with tolerated():
                            obj.dismiss()
                        plugin._open_queue_editor()
                    try:
                        run_on_ui_thread(_go)
                    except Exception:
                        _go()
            def after_hooked_method(self, param):
                with tolerated():
                    obj = param.thisObject
                    if not plugin._is_player_alert(obj):
                        return
                    blocked = getattr(plugin, "_blocked_alert", None)
                    if blocked is not None and blocked == obj:
                        plugin._blocked_alert = None
                        return
        unhooks = self.hook_all_methods(BottomSheet, "show", PlayerShowHook())
        if unhooks:
            self._hooks.extend(unhooks if isinstance(unhooks, list) else [unhooks])
        class AlertGuard(MethodHook):
            def after_hooked_method(self, param):
                with tolerated():
                    th = getattr(param, "throwable", None)
                    if th is None and hasattr(param, "getThrowable"):
                        th = param.getThrowable()
                    if th is not None and "NullPointerException" in str(th.getClass().getName()):
                        param.setResult(None)
        with tolerated():
            AP = find_class("org.telegram.ui.Components.AudioPlayerAlert")
            if AP is not None:
                unhooks = self.hook_all_methods(AP, "didReceivedNotification", AlertGuard())
                if unhooks:
                    self._hooks.extend(unhooks if isinstance(unhooks, list) else [unhooks])

    def _shuffle_step(self):
        try:
            return 1 if self._read_order()[1] else -1
        except Exception:
            return -1

    def _rebuild_shuffle(self, mc, playlist):
        with tolerated():
            n = int(playlist.size())
            sp = get_private_field(mc, "shuffledPlaylist")
            if n == 0 or sp is None:
                return
            pi = self._playing_index(mc, playlist)
            if pi < 0:
                pi = 0
            others = [playlist.get(i) for i in range(n) if i != pi]
            random.shuffle(others)
            sp.clear()
            if self._shuffle_step() < 0:
                for m in others:
                    sp.add(m)
                sp.add(playlist.get(pi))
                self._set_int_field(mc, "currentPlaylistNum", n - 1)
            else:
                sp.add(playlist.get(pi))
                for m in others:
                    sp.add(m)
                self._set_int_field(mc, "currentPlaylistNum", 0)

    def _shuffle_place(self, mc, playlist, msgs, next_):
        try:
            sp = get_private_field(mc, "shuffledPlaylist")
            if sp is None:
                return False
            if int(sp.size()) == 0:
                self._rebuild_shuffle(mc, playlist)
                if int(sp.size()) == 0:
                    return False
            playing = self._playing_key(mc)
            incoming = []
            seen = set()
            for m in msgs:
                k = self._msg_key(m) if m is not None else None
                if k is None or k in seen:
                    continue
                seen.add(k)
                incoming.append((m, k))
            if not incoming:
                return True
            i = int(sp.size()) - 1
            while i >= 0:
                k = self._msg_key(sp.get(i))
                if k in seen and k != playing:
                    sp.remove(i)
                i -= 1
            cur = -1
            for j in range(int(sp.size())):
                if self._msg_key(sp.get(j)) == playing:
                    cur = j
                    break
            if cur < 0:
                cur = self._current_index(mc)
                if not (0 <= cur < int(sp.size())):
                    cur = -1
            block = [m for m, k in incoming if k != playing]
            step = self._shuffle_step()
            size = int(sp.size())
            if cur < 0:
                for m in block:
                    sp.add(m)
                return True
            if step < 0:
                at = cur if next_ else 0
                for m in reversed(block):
                    sp.add(at, m)
                cur += len(block)
            else:
                at = cur + 1 if next_ else size
                for m in block:
                    sp.add(at, m)
                    at += 1
            self._set_int_field(mc, "currentPlaylistNum", cur)
            return True
        except Exception:
            return False

    def _shuffle_sync(self, mc, playlist):
        try:
            sp = get_private_field(mc, "shuffledPlaylist")
            if sp is None:
                return
            cur = self._current_index(mc)
            size = int(sp.size())
            if size == 0 or not (0 <= cur < size):
                self._rebuild_shuffle(mc, playlist)
                return
            have = set()
            for i in range(size):
                k = self._msg_key(sp.get(i))
                if k is not None:
                    have.add(k)
            new = []
            for i in range(int(playlist.size())):
                m = playlist.get(i)
                k = self._msg_key(m) if m is not None else None
                if k is not None and k not in have:
                    new.append(m)
            step = self._shuffle_step()
            cur0 = cur
            for m in new:
                if step < 0:
                    sp.add(random.randint(0, cur), m)
                    cur += 1
                else:
                    sp.add(random.randint(cur + 1, size), m)
                size += 1
            if cur != cur0:
                self._set_int_field(mc, "currentPlaylistNum", cur)
        except Exception:
            self._rebuild_shuffle(mc, playlist)

    def _ensure_shuffle_built(self):
        with tolerated():
            shuffle_on, _ = self._read_order()
            if not shuffle_on:
                return
            mc = self._get_mc()
            pl = self._get_playlist(mc) if mc is not None else None
            sp = get_private_field(mc, "shuffledPlaylist") if mc is not None else None
            if pl is None or sp is None or int(pl.size()) == 0:
                return
            if int(sp.size()) != int(pl.size()):
                if int(sp.size()) == 0:
                    self._rebuild_shuffle(mc, pl)
                else:
                    self._shuffle_sync(mc, pl)

    def _install_crossfade(self):
        xf = _Blend(self)
        self._xf = xf
        plan = (
       ("playMessage", xf.play_pre, xf.play_post),
       ("cleanupPlayer", xf.cleanup_pre, None),
       ("pauseMessage", None, xf.pause_post),
       )
        for name, before, after in plan:
            m = _xf_widest(name)
            if m is None:
                continue
            r = self.hook_method(m, _XfHook(before, after))
            if r:
                self._hooks.append(r)
        run_on_ui_thread(xf.start, 0)

    def _install_repeat_hook(self):
        MC = find_class("org.telegram.messenger.MediaController")
        plugin = self
        class RepeatHook(MethodHook):
            def before_hooked_method(self, param):
                with tolerated():
                    if not param.args or not bool(param.args[0]):
                        return
                    SC = find_class("org.telegram.messenger.SharedConfig")
                    if int(getattr(SC, "repeatMode", 0)) != 2:
                        return
                    mc = plugin._get_mc()
                    pm = mc.getPlayingMessageObject()
                    if pm is None:
                        return
                    plugin._cleanup_ok = True
                    plugin._allow_remote = True
                    try:
                        mc.cleanupPlayer(False, False)
                        with tolerated():
                            pm.audioProgress = 0.0
                            pm.audioProgressSec = 0
                        mc.playMessage(pm)
                    finally:
                        plugin._cleanup_ok = False
                        plugin._allow_remote = False
                    param.setResult(True)
        u = self.hook_all_methods(MC, "playNextMessageWithoutOrder", RepeatHook())
        if u:
            self._hooks.extend(u if isinstance(u, list) else [u])

    def _install_shuffle_hooks(self):
        MC = find_class("org.telegram.messenger.MediaController")
        for name in ("playNextMessage", "playPreviousMessage", "playNextMessageWithoutOrder"):
            with tolerated():
                u = self.hook_all_methods(
             MC, name, _TabHook(self, lambda param: self._ensure_shuffle_built(), None))
                if u:
                    self._hooks.extend(u if isinstance(u, list) else [u])

    def _sync_order_to(self, mc, msg):
        with tolerated():
            playlist = self._get_playlist(mc)
            if playlist is None or msg is None:
                return
            idx = self._index_of(playlist, int(msg.getId()), int(msg.getDialogId()))
            if idx < 0:
                return
            shuffle_on, _ = self._read_order()
            self._set_int_field(mc, "currentPlaylistNum", idx)
            if shuffle_on:
                self._rebuild_shuffle(mc, playlist)

    def _finish_bulk_edit(self, mc, playlist):
        shuffle_on, _ = self._read_order()
        if shuffle_on:
            self._rebuild_shuffle(mc, playlist)
        else:
            self._resync_current(mc, playlist)

    def _clear_queue(self):
        with tolerated():
            self._cancel_topic_hydration()
        mc = self._get_mc()
        pl = self._get_playlist(mc) if mc is not None else None
        if pl is None or pl.size() == 0:
            return 0, False
        playing = self._playing_key(mc)
        keep = [m for m in (pl.get(i) for i in range(pl.size()))
       if playing is not None and m is not None and self._msg_key(m) == playing][:1]
        removed = pl.size() - len(keep)
        if removed <= 0:
            return 0, bool(keep)
        pl.clear()
        with tolerated():
            pmap = get_private_field(mc, "playlistMap")
            if pmap is not None:
                pmap.clear()
        for m in keep:
            pl.add(m)
            self._map_put(mc, m)
        self._set_int_field(mc, "currentPlaylistNum", 0)
        with tolerated():
            sp = get_private_field(mc, "shuffledPlaylist")
            if sp is not None:
                sp.clear()
                for m in keep:
                    sp.add(m)
        return removed, bool(keep)

    def _do_play_next(self, msg):
        try:
            ok = self._playlist_insert_next(msg)
            self._bulletin(strings("playing_next") if ok else strings("could_not_add_as_next"), error=not ok)
        except Exception:
            self._bulletin(strings("play_next_failed"), error=True)

    def _do_add_to_queue(self, msg):
        try:
            ok = self._playlist_append(msg)
            self._bulletin(strings("added_to_queue") if ok else strings("already_in_queue_no_player"), error=not ok)
        except Exception:
            self._bulletin(strings("add_to_queue_failed"), error=True)

    def _get_mc(self):
        with tolerated():
            mc = get_media_controller()
            if mc is not None:
                return mc
        with tolerated():
            MC = find_class("org.telegram.messenger.MediaController")
            if MC is not None:
                return MC.getInstance()
        return None

    def _get_playlist(self, mc):
        with tolerated():
            pl = mc.getPlaylist()
            if pl is not None:
                return pl
        try:
            return get_private_field(mc, "playlist")
        except Exception:
            return None

    def _current_index(self, mc) -> int:
        try:
            return int(get_private_field(mc, "currentPlaylistNum"))
        except Exception:
            return -1

    def _map_put(self, mc, msg):
        with tolerated():
            pmap = get_private_field(mc, "playlistMap")
            if pmap is not None:
                pmap.put(msg.getId(), msg)

    def _index_of(self, playlist, msg_id, dialog_id) -> int:
        for i in range(playlist.size()):
            m = playlist.get(i)
            if m is not None and m.getId() == msg_id and m.getDialogId() == dialog_id:
                return i
        return -1

    def _playlist_append(self, msg) -> bool:
        mc = self._get_mc()
        if mc is None or msg is None:
            return False
        try:
            if not msg.isMusic():
                return False
            playlist = self._get_playlist(mc)
            if playlist is None:
                return False
            if self._index_of(playlist, msg.getId(), msg.getDialogId()) >= 0:
                return False
            playlist.add(msg)
            self._map_put(mc, msg)
            return True
        except Exception:
            return False

    def _read_order(self):
        shuffle_on = reversed_order = False
        with tolerated():
            SharedConfig = find_class("org.telegram.messenger.SharedConfig")
            if SharedConfig is not None:
                shuffle_on = bool(getattr(SharedConfig, "shuffleMusic", False))
                reversed_order = bool(getattr(SharedConfig, "playOrderReversed", False))
        return shuffle_on, reversed_order

    def _enable_shuffle(self):
        with tolerated():
            SharedConfig = find_class("org.telegram.messenger.SharedConfig")
            if SharedConfig is not None:
                with tolerated():
                    SharedConfig.setPlaybackOrderType(2)
                return bool(getattr(SharedConfig, "shuffleMusic", True))
        return False

    def _enable_reverse(self):
        with tolerated():
            SharedConfig = find_class("org.telegram.messenger.SharedConfig")
            if SharedConfig is not None:
                with tolerated():
                    SharedConfig.setPlaybackOrderType(1)

    def _disable_shuffle(self):
        with tolerated():
            SharedConfig = find_class("org.telegram.messenger.SharedConfig")
            with tolerated():
                SharedConfig.setPlaybackOrderType(0)

    def _resync_current(self, mc, playlist):
        with tolerated():
            shuffle_on, _ = self._read_order()
            if shuffle_on:
                return
            pi = self._playing_index(mc, playlist)
            if pi >= 0:
                self._set_int_field(mc, "currentPlaylistNum", pi)

    def _set_int_field(self, mc, name, value) -> bool:
        candidates = []
        if jint is not None:
            candidates.append(lambda: jint(value))
        with tolerated():
            from java.lang import Integer
            candidates.append(lambda: Integer(value))
        candidates.append(lambda: value)
        for make in candidates:
            try:
                set_private_field(mc, name, make())
                if self._to_int(get_private_field(mc, name)) == value:
                    return True
            except Exception:
                continue
        return False

    def _playing_index(self, mc, playlist) -> int:
        playing = None
        with tolerated():
            playing = mc.getPlayingMessageObject()
        if playing is not None:
            with tolerated():
                i = int(playlist.indexOf(playing))
                if i >= 0:
                    return i
            with tolerated():
                i = self._index_of(playlist, playing.getId(), playing.getDialogId())
                if i >= 0:
                    return i
        cur = self._current_index(mc)
        return cur if 0 <= cur < playlist.size() else -1

    def _playlist_insert_next(self, msg) -> bool:
        mc = self._get_mc()
        if mc is None or msg is None:
            return False
        try:
            if not msg.isMusic():
                return False
            playlist = self._get_playlist(mc)
            if playlist is None:
                return False
            msg_id, dialog_id = msg.getId(), msg.getDialogId()
            p = self._playing_index(mc, playlist)
            if p >= 0:
                c = playlist.get(p)
                if c is not None and c.getId() == msg_id and c.getDialogId() == dialog_id:
                    return False
            shuffle_on, reversed_order = self._read_order()
            existing = self._index_of(playlist, msg_id, dialog_id)
            if existing >= 0:
                playlist.remove(existing)
                with tolerated():
                    pmap = get_private_field(mc, "playlistMap")
                    if pmap is not None:
                        pmap.remove(msg_id)
            p = self._playing_index_after(mc, playlist, p, existing)
            if p < 0:
                insert_at = playlist.size()
            elif reversed_order:
                insert_at = p + 1
            else:
                insert_at = p
            insert_at = max(0, min(insert_at, playlist.size()))
            playlist.add(insert_at, msg)
            self._map_put(mc, msg)
            if not shuffle_on:
                new_p = p + 1 if (p >= 0 and not reversed_order) else p
                if new_p >= 0:
                    self._set_int_field(mc, "currentPlaylistNum", new_p)
            else:
                if not self._shuffle_place(mc, playlist, [msg], True):
                    with tolerated():
                        if hasattr(mc, "buildShuffledPlayList"):
                            mc.buildShuffledPlayList()
            return True
        except Exception:
            return False

    def _playing_index_after(self, mc, playlist, old_p, removed_at) -> int:
        i = self._playing_index(mc, playlist)
        if i >= 0:
            return i
        if old_p >= 0 and removed_at >= 0 and removed_at < old_p:
            return old_p - 1
        return old_p if old_p < playlist.size() else -1

    def _playlist_remove_by_id(self, mc, playlist, msg_id, dialog_id) -> bool:
        try:
            i = self._index_of(playlist, msg_id, dialog_id)
            if i < 0:
                return False
            playlist.remove(i)
            with tolerated():
                pmap = get_private_field(mc, "playlistMap")
                if pmap is not None:
                    pmap.remove(msg_id)
            with tolerated():
                if self._read_order()[0]:
                    self._rebuild_shuffle(mc, playlist)
                    return True
                cur = self._current_index(mc)
                if cur > i:
                    self._set_int_field(mc, "currentPlaylistNum", cur - 1)
                elif cur == i and playlist.size() > 0:
                    self._set_int_field(mc, "currentPlaylistNum", min(i, playlist.size() - 1))
            return True
        except Exception:
            return False

    def _play_external_rebuild(self, msg):
        mc = self._get_mc()
        if mc is None or msg is None:
            self._bulletin(strings("player_not_available"), error=True)
            return
        try:
            self._allow_remote = True
            try:
                mc.playMessage(msg)
            finally:
                self._allow_remote = False
        except Exception:
            self._bulletin(strings("could_not_rebuild_the_queue"), error=True)

    def _show_tap_behavior_menu(self, msg):
        try:
            frag = get_last_fragment()
            act = frag.getParentActivity() if frag is not None else None
            if act is None:
                self._bulletin(strings("queue_kept_unchanged_couldnt_open_the"), error=True)
                return
            options = [
          (strings("play_this_track_next"), "", False, lambda: self._do_play_next(msg)),
          (strings("add_this_track_to_the_end"), "", False, lambda: self._do_add_to_queue(msg)),
          None,
          (strings("replace_the_queue"), "", False, lambda: self._play_external_rebuild(msg)),
          ]
            _ActionSheet(self, act).show_sheet(
          strings("lock_queue_is_enabled"),
          strings("new_queue_generation_requested_what_should"),
          options,
          )
        except Exception:
            self._bulletin(strings("queue_kept_unchanged_couldnt_open_the"), error=True)

    def _make_profile_name_hook(self):
        plugin = self
        class ProfileNameHook(MethodHook):
            def before_hooked_method(self, param):
                with tolerated():
                    msg = param.args[0] if param.args else None
                    if msg is None or getattr(plugin, "_lib_bypass", False):
                        return
                    frag = get_last_fragment()
                    if plugin._profile_activity_user_id(frag, msg):
                        mc = plugin._get_mc()
                        pl = plugin._get_playlist(mc) if mc is not None else None
                        if pl is not None and plugin._queue_scope_key is not None and bool(pl.contains(msg)):
                            return
                        plugin._name_queue(msg, frag, 0, None)
        return ProfileNameHook()

    def _make_outside_queue_play_hook(self):
        plugin = self
        class OutsideQueuePlayHook(MethodHook):
            def before_hooked_method(self, param):
                with tolerated():
                    if not param.args or getattr(plugin, "_allow_remote", False):
                        return
                    msg = param.args[0]
                    if msg is None or not msg.isMusic():
                        return
                    if not plugin.get_setting("lock_queue", False):
                        return
                    mode = plugin.get_setting("locked_queue_behavior", 2)
                    try:
                        mode = int(mode)
                    except Exception:
                        mode = 2
                    if mode not in (0, 1, 2):
                        mode = 2
                    mc = plugin._get_mc()
                    pl = plugin._get_playlist(mc) if mc is not None else None
                    if pl is None or pl.size() == 0:
                        return
                    if plugin._index_of(pl, int(msg.getId()), int(msg.getDialogId())) >= 0:
                        return
                    if mode == 0:
                        param.setResult(False)
                        if not plugin._queue_next(msg):
                            plugin._bulletin(strings("queue_is_locked_but_this_track_2"), error=True)
                        else:
                            plugin._bulletin(strings("added_to_play_next"))
                    elif mode == 1:
                        param.setResult(False)
                        if not plugin._playlist_append(msg):
                            plugin._bulletin(strings("queue_is_locked_but_this_track"), error=True)
                        else:
                            plugin._bulletin(strings("added_to_the_end_of_the"))
                    elif mode == 2:
                        param.setResult(False)
                        run_on_ui_thread(lambda: plugin._show_tap_behavior_menu(msg))
        return OutsideQueuePlayHook()

    def _install_transfer_open_hook(self):
        AU = find_class("org.telegram.messenger.AndroidUtilities")
        if AU is None:
            return
        plugin = self
        class TransferOpenHook(MethodHook):
            def before_hooked_method(self, param):
                with tolerated():
                    for a in list(param.args or []):
                        if a is None or "MessageObject" not in str(a.getClass().getName()):
                            continue
                        nm = plugin._msg_file_name(a).lower()
                        is_db = nm.endswith(plugin._XFER_EXTS)
                        if not is_db or a.getDocument() is None:
                            return
                        try:
                            rt = str(param.method.getReturnType().getName())
                        except Exception:
                            rt = "boolean"
                        param.setResult(True if rt == "boolean" else None)
                        run_on_ui_thread(lambda m=a: plugin._xfer_from_message(m))
                        return
        unhooks = self.hook_all_methods(AU, "openForView", TransferOpenHook())
        if unhooks:
            self._hooks.extend(unhooks if isinstance(unhooks, list) else [unhooks])

    def _install_hooks(self):
        MediaController = find_class("org.telegram.messenger.MediaController")
        if MediaController is None:
            return
        tap_unhooks = self.hook_all_methods(
       MediaController, "playMessage", self._make_outside_queue_play_hook()
       )
        if tap_unhooks:
            self._hooks.extend(tap_unhooks if isinstance(tap_unhooks, list) else [tap_unhooks])
        tap_unhooks = self.hook_all_methods(
       MediaController, "playMessage", self._make_profile_name_hook()
       )
        if tap_unhooks:
            self._hooks.extend(tap_unhooks if isinstance(tap_unhooks, list) else [tap_unhooks])
        unhooks = self.hook_all_methods(
       MediaController, "setPlaylist", self._make_set_playlist_hook()
       )
        if unhooks:
            self._hooks.extend(unhooks if isinstance(unhooks, list) else [unhooks])
        with tolerated():
            unhooks = self.hook_all_methods(
          MediaController, "loadMoreMusic", self._make_load_more_hook()
          )
            if unhooks:
                self._hooks.extend(unhooks if isinstance(unhooks, list) else [unhooks])
        with tolerated():
            unhooks = self.hook_all_methods(
          MediaController, "cleanupPlayer", self._make_cleanup_hook()
          )
            if unhooks:
                self._hooks.extend(unhooks if isinstance(unhooks, list) else [unhooks])

    def _drop_last_queue_data(self):
        if self.get_setting("live_queue_v1", ""):
            self.set_setting("live_queue_v1", "")
        d = self._lib_data()
        pls = d.get("playlists", [])
        keep = [pl for pl in pls if not (isinstance(pl, dict) and pl.get("id") == "last_queue")]
        if len(keep) != len(pls):
            d["playlists"] = keep
            self._lib_save()
