import json
import time

from ..compat import MethodHook, find_class, get_private_field, jclass, jfloat, run_on_ui_thread
from ..crossfade import _XfHook, _xf_widest
from ..safe import tolerated
from elyx import strings

_PB_RETRY_MS = (0, 250, 800, 2000)
_TIMEOUTS = (0, 5, 8, 12, 15)
_CONNECTING_GRACE = 8.0
_SCAN_LIMIT = 64


class _PluginPlaybackFx:
    def _install_playback_fx(self):
        with tolerated():
            self._install_download_hooks()
        with tolerated():
            self._net_events_install()
        m = _xf_widest("playMessage")
        if m is None:
            return
        r = self.hook_method(m, _XfHook(self._fx_before_play, self._fx_after_play))
        if r:
            self._hooks.append(r)

    _PB_OVR = "pb_track_fx"
    _PB_OVR_MAX = 500

    def _pb_global(self):
        try:
            spd = float(self.get_setting("pb_speed", 1.0))
        except Exception:
            spd = 1.0
        try:
            semi = int(self.get_setting("pb_pitch", 0))
        except Exception:
            semi = 0
        return spd, semi

    def _pb_ovr_all(self):
        try:
            d = json.loads(self.get_setting(self._PB_OVR, "") or "{}")
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _pb_track_id(self):
        with tolerated():
            mc = self._get_mc()
            k = self._playing_key(mc) if mc is not None else None
            if k:
                return "%d:%d" % (int(k[0]), int(k[1]))
        return None

    def _pb_track_only(self):
        k = self._pb_track_id()
        return k is not None and k in self._pb_ovr_all()

    def _pb_settings(self):
        k = self._pb_track_id()
        if k is not None:
            o = self._pb_ovr_all().get(k)
            if isinstance(o, (list, tuple)) and len(o) == 2:
                try:
                    return float(o[0]), int(o[1])
                except Exception:
                    pass
        return self._pb_global()

    def _pb_store(self, speed=None, pitch=None):
        k = self._pb_track_id()
        if k is not None:
            d = self._pb_ovr_all()
            if k in d:
                s, p = self._pb_settings()
                d[k] = [round(float(s if speed is None else speed), 2), int(round(p if pitch is None else pitch))]
                self.set_setting(self._PB_OVR, json.dumps(d, separators=(",", ":")))
                return
        base = getattr(self, "_pb_base", None)
        if k is not None and (base is None or base[0] != k):
            g = self._pb_global()
            self._pb_base = (k, g[0], g[1])
        if speed is not None:
            self.set_setting("pb_speed", round(float(speed), 2))
        if pitch is not None:
            self.set_setting("pb_pitch", int(round(pitch)))

    def _pb_set_track_only(self, on):
        k = self._pb_track_id()
        if k is None:
            return
        d = self._pb_ovr_all()
        if on:
            s, p = self._pb_settings()
            d.pop(k, None)
            d[k] = [round(float(s), 2), int(p)]
            while len(d) > self._PB_OVR_MAX:
                d.pop(next(iter(d)))
            base = getattr(self, "_pb_base", None)
            if base is not None and base[0] == k:
                self.set_setting("pb_speed", round(float(base[1]), 2))
                self.set_setting("pb_pitch", int(base[2]))
            self._pb_base = None
        else:
            d.pop(k, None)
        self.set_setting(self._PB_OVR, json.dumps(d, separators=(",", ":")))

    def _pb_apply_now(self, force=True):
        spd, semi = self._pb_settings()
        with tolerated():
            self._eq_sync()
        xf = getattr(self, "_xf", None)
        pl = xf.get("audioPlayer") if xf is not None else None
        if pl is None:
            return
        tag = (str(pl.hashCode()), spd, semi)
        if not force and getattr(self, "_pb_tag", None) == tag:
            return
        self._pb_tag = tag
        fl = (lambda v: jfloat(v)) if jfloat is not None else (lambda v: v)
        try:
            self._get_mc().setPlaybackSpeed(True, fl(spd))
        except Exception:
            with tolerated():
                pl.setPlaybackSpeed(fl(spd))
        with tolerated():
            f = pl.getClass().getDeclaredField("player")
            f.setAccessible(True)
            ex = f.get(pl)
            PP = None
            for cn in ("com.google.android.exoplayer2.PlaybackParameters",
                       "androidx.media3.common.PlaybackParameters"):
                try:
                    PP = find_class(cn) or jclass(cn)
                    break
                except Exception:
                    PP = None
            if ex is not None and PP is not None:
                ex.setPlaybackParameters(PP(fl(spd), fl(2.0 ** (semi / 12.0))))

    def _pb_burst(self):
        for d in _PB_RETRY_MS:
            run_on_ui_thread(lambda: self._pb_apply_now(True), d)

    def _stream_on(self) -> bool:
        try:
            return bool(getattr(find_class("org.telegram.messenger.SharedConfig"), "streamMedia", False))
        except Exception:
            return False

    def _track_ready(self, m) -> bool:
        if m is None:
            return False
        try:
            if not m.isMusic():
                return False
        except Exception:
            return False
        if self._is_downloaded(m):
            return True
        if self._unavailable(m):
            return False
        return self._stream_on() and not self._is_loading(m)

    def _logical_queue(self, mc):
        pl = self._get_playlist(mc)
        if pl is None:
            return []
        shuffle_on, rev = self._read_order()
        if shuffle_on:
            from ..compat import get_private_field
            sp = get_private_field(mc, "shuffledPlaylist")
            return [sp.get(i) for i in range(sp.size())] if sp is not None else []
        raw = [pl.get(i) for i in range(pl.size())]
        return raw if rev else raw[::-1]

    def _next_ready(self, mc, start_idx, step):
        L = self._logical_queue(mc)
        n = len(L)
        if n < 2 or not 0 <= start_idx < n:
            return None
        wrap = False
        with tolerated():
            wrap = int(getattr(find_class("org.telegram.messenger.SharedConfig"), "repeatMode", 0)) == 1
        j = start_idx
        for _ in range(min(n - 1, _SCAN_LIMIT)):
            j += step
            if not 0 <= j < n:
                if not wrap:
                    return None
                j %= n
            if j == start_idx:
                return None
            if self._track_ready(L[j]):
                return L[j]
        return None

    def _stall_timeout(self) -> float:
        try:
            i = int(self.get_setting("stall_timeout_v5", 3))
        except Exception:
            i = 3
        return float(_TIMEOUTS[i if 0 <= i < len(_TIMEOUTS) else 3])

    def _fx_before_play(self, param):
        mc = self._get_mc()
        self._sg_prev = self._playing_key(mc) if mc is not None else None

    def _fx_after_play(self, param):
        with tolerated():
            self._rs_note()
        self._pb_burst()
        with tolerated():
            self._stall_arm(param)
        with tolerated():
            self._preload_prune()

    def _stall_arm(self, param):
        grace = self._stall_timeout()
        if not param.args or getattr(self, "_sg_busy", False):
            return
        target = param.args[0]
        if target is not None and self._unavailable(target):
            grace = 0.5
        if grace <= 0:
            return
        if target is None or self._is_downloaded(target) or (not target.isMusic() and not self._unavailable(target)):
            return
        if getattr(self, "_allow_remote", False):
            return
        mc = self._get_mc()
        L = self._logical_queue(mc)
        tk = self._msg_key(target)
        keys = [self._msg_key(m) if m is not None else None for m in L]
        if tk not in keys:
            return
        tidx = keys.index(tk)
        prev = getattr(self, "_sg_prev", None)
        if prev is None or prev not in keys:
            step = 1
        else:
            d = tidx - keys.index(prev)
            if abs(d) != 1:
                return
            step = 1 if d > 0 else -1
        self._sg_token = int(getattr(self, "_sg_token", 0)) + 1
        tok = self._sg_token
        t0 = time.monotonic()
        with tolerated():
            xf = getattr(self, "_xf", None)
            if xf is not None:
                t0 += xf.switch_delay()
        run_on_ui_thread(lambda: self._stall_tick(tok, tk, target, step, t0, grace, False), 300)

    def _still_loading(self, mc, target) -> bool:
        xf = getattr(self, "_xf", None)
        if xf is None:
            return False
        if xf.getn("downloadingCurrentMessage", False, "b"):
            return not self._is_downloaded(target)
        if self._is_downloaded(target):
            return False
        with tolerated():
            if bool(mc.isMessagePaused()):
                return False
        pl = xf.get("audioPlayer")
        if pl is None:
            return True
        with tolerated():
            if bool(pl.isBuffering()):
                return True
        with tolerated():
            return int(pl.getCurrentPosition()) <= 0
        return False

    def _stall_tick(self, tok, tk, target, step, t0, grace, warned):
        if tok != getattr(self, "_sg_token", 0):
            return
        mc = self._get_mc()
        if mc is None or self._playing_key(mc) != tk:
            return
        if not self._still_loading(mc, target):
            return
        if time.monotonic() - t0 < (0.5 if self._net_down() else grace):
            run_on_ui_thread(lambda: self._stall_tick(tok, tk, target, step, t0, grace, warned), 250)
            return
        L = self._logical_queue(mc)
        keys = [self._msg_key(m) if m is not None else None for m in L]
        cand = self._next_ready(mc, keys.index(tk), step) if tk in keys else None
        if cand is None:
            if not warned:
                self._bulletin(strings("waiting_for_track_to_load"))
            run_on_ui_thread(lambda: self._stall_tick(tok, tk, target, step, t0, grace, True), 1000)
            return
        title = ""
        with tolerated():
            title = str(target.getMusicTitle())
        self._sg_busy = True
        try:
            mc.playMessage(cand)
            self._resync_current(mc, self._get_playlist(mc))
        finally:
            self._sg_busy = False
        self._bulletin(strings("skipped_loading_track", title) if title else strings("skipped_loading_track_plain"))

    def _native_next(self):
        mc = self._get_mc()
        shuffle_on, rev = self._read_order()
        lst = get_private_field(mc, "shuffledPlaylist" if shuffle_on else "playlist")
        if lst is None or int(lst.size()) < 2:
            return None
        cur = int(get_private_field(mc, "currentPlaylistNum"))
        n = cur + 1 if rev else cur - 1
        if n >= int(lst.size()):
            n = 0
        elif n < 0:
            n = int(lst.size()) - 1
        return lst.get(n)

    def _cancel_load(self, m):
        FL = find_class("org.telegram.messenger.FileLoader")
        loader = FL.getInstance(int(m.currentAccount))
        try:
            loader.cancelLoadFile(m.getDocument())
        except Exception:
            loader.cancelLoadFile(str(FL.getAttachFileName(m.getDocument())))

    def _install_download_hooks(self):
        MC = find_class("org.telegram.messenger.MediaController")
        if MC is None:
            return
        plugin = self
        self._preloaded = {}
        class PreloadGate(MethodHook):
            def before_hooked_method(self, param):
                with tolerated():
                    if not plugin.get_setting("preload_next_track", True):
                        param.setResult(None)
                        plugin._pre_snap = None
                        return
                    m = plugin._native_next()
                    if m is not None and plugin._unavailable(m):
                        param.setResult(None)
                        plugin._pre_snap = None
                        return
                    plugin._pre_snap = (m, plugin._is_downloaded(m) or plugin._is_loading(m)) if m is not None else None
            def after_hooked_method(self, param):
                with tolerated():
                    snap, plugin._pre_snap = getattr(plugin, "_pre_snap", None), None
                    if snap and not snap[1] and plugin._is_loading(snap[0]):
                        k = plugin._msg_key(snap[0])
                        if k is not None:
                            plugin._preloaded[k] = snap[0]
        u = self.hook_all_methods(MC, "checkIsNextMusicFileDownloaded", PreloadGate())
        if u:
            self._hooks.extend(u if isinstance(u, list) else [u])
        class CleanupKeep(MethodHook):
            def before_hooked_method(self, param):
                plugin._keep_dl = None
                with tolerated():
                    if plugin.get_setting("cancel_skipped_download", True):
                        return
                    xf = getattr(plugin, "_xf", None)
                    if xf is not None and xf.getn("downloadingCurrentMessage", False, "b"):
                        plugin._keep_dl = plugin._get_mc().getPlayingMessageObject()
            def after_hooked_method(self, param):
                m, plugin._keep_dl = getattr(plugin, "_keep_dl", None), None
                if m is not None:
                    with tolerated():
                        plugin._start_download(m)
        u = self.hook_all_methods(MC, "cleanupPlayer", CleanupKeep())
        if u:
            self._hooks.extend(u if isinstance(u, list) else [u])

    def _preload_prune(self):
        pre = getattr(self, "_preloaded", None)
        if not pre:
            return
        cancel = True
        mc = self._get_mc()
        keep = set()
        pk = self._playing_key(mc) if mc is not None else None
        if pk is not None:
            keep.add(pk)
        nxt = self._native_next()
        if nxt is not None:
            keep.add(self._msg_key(nxt))
        for k, m in list(pre.items()):
            if self._is_downloaded(m) or not self._is_loading(m):
                pre.pop(k, None)
            elif k not in keep:
                if cancel:
                    with tolerated():
                        self._cancel_load(m)
                pre.pop(k, None)

    def _net_events_install(self):
        from ..android import _proxy
        NC = find_class("org.telegram.messenger.NotificationCenter")
        L = _proxy("org.telegram.messenger.NotificationCenter$NotificationCenterDelegate", "didReceivedNotification")
        self._net_ev = (NC, int(NC.didUpdateConnectionState), L(self._net_on_event))
        for i in range(int(find_class("org.telegram.messenger.UserConfig").MAX_ACCOUNT_COUNT)):
            with tolerated():
                NC.getInstance(i).addObserver(self._net_ev[2], self._net_ev[1])

    def _net_events_teardown(self):
        ev = getattr(self, "_net_ev", None)
        self._net_ev = None
        if ev is None:
            return
        for i in range(int(find_class("org.telegram.messenger.UserConfig").MAX_ACCOUNT_COUNT)):
            with tolerated():
                ev[0].getInstance(i).removeObserver(ev[2], ev[1])

    def _net_on_event(self, *a):
        if self._offline_mode() != 2:
            return
        self._net_cache = None
        run_on_ui_thread(self._net_refresh)
        run_on_ui_thread(self._net_refresh, int(_CONNECTING_GRACE * 1000) + 300)

    def _net_refresh(self):
        self._net_cache = None
        ed = getattr(self, "_editor", None)
        if ed is None:
            return
        with tolerated():
            ed._update_offline_icon()
            pi = ed._playing_pos()
            for i in list(ed.row_refs):
                ed._style_row(i, pi)

    def _net_down(self) -> bool:
        now = time.monotonic()
        c = getattr(self, "_net_cache", None)
        if c is not None and now - c[0] < 1.0:
            return c[1]
        down = False
        try:
            CM = find_class("org.telegram.tgnet.ConnectionsManager")
            acc = int(find_class("org.telegram.messenger.UserConfig").selectedAccount)
            st = int(CM.getInstance(acc).getConnectionState())
            if st == int(CM.ConnectionStateWaitingForNetwork):
                down = True
            elif st in (int(CM.ConnectionStateConnecting), int(CM.ConnectionStateConnectingToProxy)):
                since = getattr(self, "_net_conn_since", None)
                if since is None:
                    self._net_conn_since = since = now
                down = now - since >= _CONNECTING_GRACE
            else:
                self._net_conn_since = None
        except Exception:
            down = False
        self._net_cache = (now, down)
        return down

    def _offline_mode(self) -> int:
        v = self.get_setting("offline_mode_v2", None)
        if v is None:
            return 1 if self.get_setting("offline_mode", False) else 2
        try:
            return int(v) if int(v) in (0, 1, 2) else 2
        except Exception:
            return 2

    def _offline_set(self, v: int):
        self.set_setting("offline_mode_v2", int(v))
        self._net_cache = None

    def _offline_active(self) -> bool:
        mode = self._offline_mode()
        if mode == 1:
            return True
        if mode == 2:
            try:
                return self._net_down()
            except Exception:
                return False
        return False
