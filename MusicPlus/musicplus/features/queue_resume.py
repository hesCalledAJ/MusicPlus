import json
import os
import struct
import threading
import time

from ..compat import ArrayList, find_class, jclass, run_on_ui_thread
from ..safe import tolerated
from ..telegram_io import _TLCodec

_MAGIC = b"SMR1"
_CAP = 100
_BEFORE = 30
_EDGE = 8
_SAVE_DELAY_S = 3.0
_NOTE_EVERY_S = 5.0


class _PluginQueueResume:
    _rs_alive = False
    _rs_meta = None
    _rs_job = None
    _rs_timer = None
    _rs_lock = threading.Lock()
    _rs_loading = False
    _rs_want_play = False
    _rs_last_pos = None
    _rs_avail = (0.0, False)
    _closed = None

    def _rs_hold_closed(self):
        if not self._rs_enabled():
            return
        mc = self._get_mc()
        pm = mc.getPlayingMessageObject() if mc is not None else None
        pl = self._get_playlist(mc) if mc is not None else None
        if pm is None or pl is None or not bool(pm.isMusic()) or int(pl.size()) == 0:
            return
        key = self._msg_key(pm)
        if key is None:
            return
        self._closed = {"msgs": [pl.get(i) for i in range(int(pl.size()))], "first": pm, "key": key,
                        "frac": float(pm.audioProgress), "origin": self._origin_pack(),
                        "pos": {"k": [int(key[0]), int(key[1])], "p": float(pm.audioProgress),
                                "ms": int(pm.audioProgressMs), "s": int(pm.audioProgressSec)}}
        self._rs_write_pos(pm, key)

    def _rs_reopen_closed(self, play=True, done=None):
        c = self._closed
        if not c:
            return False
        mc = self._get_mc()
        pl = self._get_playlist(mc) if mc is not None else None
        if mc is None or (pl is not None and int(pl.size()) > 0) or mc.getPlayingMessageObject() is not None:
            self._closed = None
            return False
        ok = False
        src = c.get("origin") or [None, None]
        def origin_back():
            with tolerated():
                self._origin_set(src[0], src[1], cover=None, owned=None)
        try:
            self._origin_pin_until = time.monotonic() + 4.0
            origin_back()
            first = c["first"]
            self._rs_load_paused(mc, c["msgs"], first, c.get("pos"), None)
            self._rs_attach_saved_list(mc, src, c["msgs"], int(first.currentAccount))
            origin_back()
            self._closed = None
            self._rs_meta = None
            ok = True
            if play:
                prev_r = bool(getattr(self, "_allow_remote", False))
                self._allow_remote = True
                try:
                    mc.playMessage(first)
                finally:
                    self._allow_remote = prev_r
                origin_back()
        except Exception:
            self._bulletin(self._rs_fail_text(), error=True)
        finally:
            with tolerated():
                self._rs_refresh_minis()
            if done is not None:
                with tolerated():
                    done()
        return ok


    def _rs_enabled(self):
        return bool(self.get_setting("resume_queue", True))

    def _rs_start(self):
        if self._rs_alive:
            return
        self._rs_alive = True
        def loop():
            while self._rs_alive:
                time.sleep(_NOTE_EVERY_S)
                if self._rs_alive:
                    try:
                        run_on_ui_thread(self._rs_note)
                    except Exception:
                        pass
        threading.Thread(target=loop, daemon=True, name="smq-resume-tick").start()

    def _rs_stop(self):
        self._rs_alive = False

    def _rs_path(self, name):
        ctx = find_class("org.telegram.messenger.ApplicationLoader").applicationContext
        return os.path.join(str(ctx.getFilesDir().getAbsolutePath()), name)


    def _rs_note(self):
        if not self._rs_enabled():
            return
        mc = self._get_mc()
        pm = mc.getPlayingMessageObject() if mc is not None else None
        if pm is None or not bool(pm.isMusic()):
            return
        pl = self._get_playlist(mc)
        n = int(pl.size()) if pl is not None else 0
        key = self._msg_key(pm)
        if n == 0 or key is None:
            return
        self._rs_write_pos(pm, key)
        sig = (n, int(pl.get(0).getId()), int(pl.get(n - 1).getId()))
        meta = self._rs_meta
        need = meta is None or key not in meta["keys"]
        if not need and meta["sig"] != sig:
            need = getattr(self, "_topic_hydration_scope", None) is None
        if not need:
            j = meta["keys"].index(key)
            need = (j >= len(meta["keys"]) - _EDGE and meta["end"] < n) or (j < _EDGE and meta["start"] > 0)
        if not need:
            return
        cp = None
        try:
            cp = ArrayList(pl)
        except Exception:
            return
        job = {"copy": cp, "pm": pm, "key": key, "sig": sig, "origin": self._origin_pack(),
               "pu": self._saved_music_uid()}
        with self._rs_lock:
            self._rs_job = job
            if self._rs_timer is not None:
                return
            t = threading.Timer(_SAVE_DELAY_S, self._rs_work)
            t.daemon = True
            self._rs_timer = t
            t.start()

    def _rs_write_pos(self, pm, key):
        pos = {"k": [int(key[0]), int(key[1])], "p": float(pm.audioProgress),
               "ms": int(pm.audioProgressMs), "s": int(pm.audioProgressSec)}
        if pos == self._rs_last_pos:
            return
        self._rs_last_pos = pos
        with tolerated():
            path = self._rs_path("smq_resume_pos.json")
            with open(path + ".tmp", "w") as fh:
                json.dump(pos, fh)
            os.replace(path + ".tmp", path)

    def _rs_work(self):
        with self._rs_lock:
            job, self._rs_job, self._rs_timer = self._rs_job, None, None
        if job is not None:
            with tolerated():
                self._rs_save(job)

    def _rs_save(self, job):
        cp, pm = job["copy"], job["pm"]
        n = int(cp.size())
        idx = int(cp.indexOf(pm))
        if idx < 0:
            for i in range(n):
                if self._msg_key(cp.get(i)) == job["key"]:
                    idx = i
                    break
        if idx < 0:
            return
        start = max(0, min(idx - _BEFORE, n - _CAP))
        end = min(n, start + _CAP)
        rows, blobs = [], []
        for c, i in enumerate(range(start, end)):
            m = cp.get(i)
            blob = _TLCodec.dump(m) if m is not None else None
            if blob:
                rows.append({"i": int(m.getId()), "d": int(m.getDialogId()), "l": len(blob)})
                blobs.append(blob)
            if c % 10 == 9:
                time.sleep(0.005)
        if not rows:
            return
        head = json.dumps({"acc": int(pm.currentAccount), "rows": rows, "cur": list(job["key"]),
                           "src": job["origin"], "pu": job.get("pu", 0)}, separators=(",", ":")).encode("utf-8")
        path = self._rs_path("smq_resume.bin")
        with open(path + ".tmp", "wb") as fh:
            fh.write(_MAGIC)
            fh.write(struct.pack("<I", len(head)))
            fh.write(head)
            for b in blobs:
                fh.write(b)
            fh.flush()
            with tolerated():
                os.fsync(fh.fileno())
        os.replace(path + ".tmp", path)
        self._rs_avail = (0.0, False)
        self._rs_meta = {"keys": [(r["i"], r["d"]) for r in rows], "sig": job["sig"], "start": start, "end": end}


    def _resume_available(self):
        if not self._rs_enabled():
            return False
        t, v = self._rs_avail
        now = time.monotonic()
        if now - t < 2.0:
            return v
        try:
            v = os.path.getsize(self._rs_path("smq_resume.bin")) > 16
        except Exception:
            v = False
        self._rs_avail = (now, v)
        return v

    def _rs_boot(self, delay_ms=900):
        def go():
            with tolerated():
                if not self._rs_enabled() or not self._resume_available():
                    return
                if not bool(self.get_setting("resume_show_bar", True)):
                    return
                mc = self._get_mc()
                pl = self._get_playlist(mc) if mc is not None else None
                if mc is None or (pl is not None and int(pl.size()) > 0) or mc.getPlayingMessageObject() is not None:
                    return
                self._resume_restore(play=False)
        try:
            self._post(go, delay_ms)
        except Exception:
            pass

    def _resume_restore(self, play=False, done=None):
        if self._rs_loading:
            if play:
                self._rs_want_play = True
            if done is not None:
                self.__dict__.setdefault("_rs_waiters", []).append(done)
            return True
        if not self._resume_available():
            return False
        self._rs_loading = True
        if done is not None:
            self.__dict__.setdefault("_rs_waiters", []).append(done)
        def work():
            res = None
            with tolerated():
                res = self._rs_read()
            run_on_ui_thread(lambda: self._rs_apply(res, play, done))
        threading.Thread(target=work, daemon=True, name="smq-resume-load").start()
        return True

    def _rs_read(self):
        with open(self._rs_path("smq_resume.bin"), "rb") as fh:
            if fh.read(4) != _MAGIC:
                return None
            hl = struct.unpack("<I", fh.read(4))[0]
            head = json.loads(fh.read(hl).decode("utf-8"))
            msgs = []
            for c, r in enumerate(head["rows"]):
                blob = fh.read(int(r["l"]))
                m = _TLCodec.load(int(head["acc"]), int(r["d"]), blob) if blob else None
                if m is not None:
                    with tolerated():
                        m.checkMediaExistance()
                    msgs.append(m)
                if c % 10 == 9:
                    time.sleep(0.005)
        pos = None
        with tolerated():
            with open(self._rs_path("smq_resume_pos.json"), "r") as fh:
                pos = json.load(fh)
        cur = tuple(head.get("cur") or ())
        info = None
        with tolerated():
            first = next((m for m in msgs if self._msg_key(m) == cur), None)
            if first is not None:
                File = jclass("java.io.File")
                ap = first.messageOwner.attachPath
                f = File(ap) if ap else None
                if f is None or not f.exists():
                    f = jclass("org.telegram.messenger.FileLoader").getInstance(int(first.currentAccount)).getPathToMessage(first.messageOwner)
                if f is not None and f.exists():
                    info = jclass("org.telegram.messenger.audioinfo.AudioInfo").getAudioInfo(f)
        return {"msgs": msgs, "cur": cur, "src": head.get("src"), "pos": pos, "info": info, "pu": head.get("pu", 0)}

    def _rs_apply(self, res, play, done):
        self._rs_loading = False
        play = bool(play or self._rs_want_play)
        self._rs_want_play = False
        waiters = self.__dict__.pop("_rs_waiters", None) or []
        if done is not None:
            waiters.append(done)
        try:
            if not res or not res["msgs"]:
                return
            mc = self._get_mc()
            pl = self._get_playlist(mc) if mc is not None else None
            if mc is None or (pl is not None and int(pl.size()) > 0) or mc.getPlayingMessageObject() is not None:
                return
            msgs = res["msgs"]
            first = next((m for m in msgs if self._msg_key(m) == res["cur"]), msgs[0])
            src = res.get("src") or [None, None]
            if not src[1]:
                with tolerated():
                    did = int(first.getDialogId())
                    if did:
                        src = [src[0], [did, 0, ""]]
            if res.get("pu"):
                src = [src[0], ["profile_music", int(res["pu"])]]
            self._origin_pin_until = time.monotonic() + 4.0
            def _origin_back():
                with tolerated():
                    self._origin_set(src[0], src[1], cover=None, owned=None)
            _origin_back()
            self._rs_load_paused(mc, msgs, first, res.get("pos"), res.get("info"))
            self._rs_attach_saved_list(mc, src, msgs, int(first.currentAccount))
            self._closed = None
            _origin_back()
            pl = self._get_playlist(mc)
            n = int(pl.size())
            self._rs_meta = {"keys": [self._msg_key(m) for m in msgs],
                             "sig": (n, int(pl.get(0).getId()), int(pl.get(n - 1).getId())),
                             "start": 0, "end": len(msgs)}
            if play:
                prev_r = bool(getattr(self, "_allow_remote", False))
                self._allow_remote = True
                try:
                    mc.playMessage(first)
                finally:
                    self._allow_remote = prev_r
                _origin_back()
        except Exception:
            self._bulletin(self._rs_fail_text(), error=True)
        finally:
            with tolerated():
                self._rs_refresh_minis()
            for fn in waiters:
                with tolerated():
                    fn()

    def _rs_attach_saved_list(self, mc, src, msgs, acc):
        sc = src[1] if src else None
        if not (isinstance(sc, (list, tuple)) and len(sc) >= 2 and sc[0] == "profile_music"):
            return
        with tolerated():
            from ..compat import set_private_field
            SML = jclass("org.telegram.messenger.MessagesController$SavedMusicList")
            lst = SML(int(acc), int(sc[1]))
            for m in msgs:
                lst.list.add(m)
            lst.totalCount = len(msgs)
            lst.endReached = True
            set_private_field(mc, "currentSavedMusicList", lst)

    def _rs_refresh_minis(self):
        mr = getattr(self, "_mini_rows", None)
        if mr is None:
            return
        for row in list(mr.rows.values()):
            with tolerated():
                row.update()

    def _rs_call(self, mc, name):
        m = mc.getClass().getDeclaredMethod(name)
        m.setAccessible(True)
        m.invoke(mc)

    def _rs_load_paused(self, mc, msgs, first, pos, info):
        from ..compat import get_private_field, jclass
        acc = int(first.currentAccount)
        mid = int(first.getId())
        if pos and tuple(pos.get("k") or ()) == self._msg_key(first):
            first.forceSeekTo = float(pos["p"])
            first.audioProgress = float(pos["p"])
            first.audioProgressMs = int(pos["ms"])
            first.audioProgressSec = int(pos["s"])
        progress = float(first.audioProgress)
        lst = [m for m in msgs]
        if not any(m is first for m in lst):
            lst.insert(0, first)
        for name in ("downloadingCurrentMessage", "loadingPlaylist", "forceLoopCurrentPlaylist"):
            with tolerated():
                self._rs_set_bool(mc, name, False)
        with tolerated():
            ends = get_private_field(mc, "playlistEndReached")
            ends[0] = False
            ends[1] = False
        with tolerated():
            ids = [int(m.getId()) for m in lst if int(m.getId()) > 0]
            mx = get_private_field(mc, "playlistMaxId")
            mx[0] = min(ids) if ids else 2147483647
            mx[1] = 2147483647
        from ..compat import set_private_field
        set_private_field(mc, "playingMessageObject", first)
        self._rs_set_bool(mc, "isPaused", True)
        al = ArrayList()
        for m in lst:
            al.add(m)
        cur = get_private_field(mc, "playlist")
        cur.clear()
        cur.addAll(al)
        pmap = get_private_field(mc, "playlistMap")
        pmap.clear()
        for m in lst:
            self._map_put(mc, m)
        with tolerated():
            self._rs_call(mc, "sortPlaylist")
        idx = int(get_private_field(mc, "playlist").indexOf(first))
        self._set_int_field(mc, "currentPlaylistNum", max(0, idx))
        shuffle_on, _rev = self._read_order()
        if shuffle_on:
            with tolerated():
                self._rs_call(mc, "buildShuffledPlayList")
        with tolerated():
            self._set_int_field(mc, "playlistClassGuid",
                                int(jclass("org.telegram.tgnet.ConnectionsManager").generateClassGuid()))
        if info is not None:
            with tolerated():
                set_private_field(mc, "audioInfo", info)
        NC = jclass("org.telegram.messenger.NotificationCenter")
        nc = NC.getInstance(acc)
        Obj = jclass("java.lang.Object")
        from ..compat import jarray
        from ..compat import jint, jfloat
        def bi(v):
            return jint(int(v)) if jint else jclass("java.lang.Integer")(int(v))
        def bf(v):
            return jfloat(float(v)) if jfloat else jclass("java.lang.Float")(float(v))
        def post(event, *vals):
            with tolerated():
                nc.postNotificationName(int(event), jarray(Obj)(list(vals)))
        post(NC.messagePlayingDidReset, bi(mid), bool(False))
        post(NC.messagePlayingProgressDidChanged, bi(mid), bf(progress))
        post(NC.messagePlayingPlayStateChanged, bi(mid))
        post(NC.moreMusicDidLoad, bi(len(lst)))
        if len(lst) <= 1 and mid > 0:
            with tolerated():
                jclass("org.telegram.messenger.MediaDataController").getInstance(acc).loadMusic(
                    int(first.getDialogId()), mid, mid)

    def _rs_set_bool(self, mc, name, value):
        from ..compat import get_private_field, set_private_field
        for make in (lambda: bool(value), lambda: __import__("java.lang", fromlist=["Boolean"]).Boolean(bool(value))):
            try:
                set_private_field(mc, name, make())
                if bool(get_private_field(mc, name)) == bool(value):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _rs_fail_text():
        from elyx import strings
        return strings("couldnt_resume_the_queue")
