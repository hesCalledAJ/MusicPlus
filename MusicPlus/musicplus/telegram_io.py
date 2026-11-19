import collections
import json
import os
import threading
import time
from .compat import jarray, jbyte, jclass, run_on_ui_thread
from .safe import tolerated


class _MusicFetcher:
    PAGE = 100
    CAP = 10000
    def __init__(self, plugin, account, dialog_id, topic_id, on_progress, on_done, query="", want=None, min_id=0, on_batch=None, batch_on_ui=True, cap=None):
        self.p = plugin
        self.cap = min(int(cap), self.CAP) if cap else self.CAP
        self.on_batch = on_batch
        self.batch_on_ui = bool(batch_on_ui)
        self.min_id = int(min_id or 0)
        self.want = set(int(x) for x in want) if want else None
        self.acc = account
        self.dialog_id = dialog_id
        self.topic_id = topic_id
        self.query = str(query or "").strip()
        self.on_progress = on_progress
        self.on_done = on_done
        self.tracks = []
        self.seen = set()
        self.total = 0
        self.cancelled = False
        self._last_offset = None
        self._finished = False
    def start(self):
        self._send(0)
    def cancel(self):
        self.cancelled = True
    def stop_with_partial(self):
        if self._finished:
            return
        self.cancelled = True
        self._finish(None)
    def _ui(self, fn):
        try:
            run_on_ui_thread(fn)
        except Exception:
            fn()
    def _send(self, offset_id):
        from .sheets import _jc, _request_delegate
        try:
            TL = _jc("org.telegram.tgnet.TLRPC$TL_messages_search")
            Flt = _jc("org.telegram.tgnet.TLRPC$TL_inputMessagesFilterMusic")
            MCtl = _jc("org.telegram.messenger.MessagesController")
            CM = _jc("org.telegram.tgnet.ConnectionsManager")
            req = TL()
            req.q = self.query
            req.filter = Flt()
            req.limit = self.PAGE
            req.offset_id = int(offset_id)
            if self.min_id:
                req.min_id = self.min_id
            req.peer = MCtl.getInstance(self.acc).getInputPeer(self.dialog_id)
            if self.topic_id and int(self.topic_id) != 1:
                req.flags = int(req.flags) | 2
                req.top_msg_id = int(self.topic_id)
            self._last_offset = offset_id
            CM.getInstance(self.acc).sendRequest(req, _request_delegate(self._on_response))
        except Exception as e:
            self._finish(f"request failed ({e})")
    def _on_response(self, res, err):
        if self.cancelled or self._finished:
            return
        try:
            threading.Thread(target=self._process_response, args=(res, err), daemon=True, name="smq-music-page").start()
        except Exception:
            self._process_response(res, err)
    def _process_response(self, res, err):
        from .sheets import _jc
        if self.cancelled or self._finished:
            return
        try:
            if err is not None:
                self._finish(str(getattr(err, "text", "error")))
                return
            msgs = getattr(res, "messages", None)
            if msgs is None:
                self._finish(None)
                return
            with tolerated():
                MCtl = _jc("org.telegram.messenger.MessagesController")
                inst = MCtl.getInstance(self.acc)
                inst.putUsers(res.users, False)
                inst.putChats(res.chats, False)
            MO = _jc("org.telegram.messenger.MessageObject")
            n = int(msgs.size())
            min_id = None
            page_tracks = []
            for i in range(n):
                if i % 12 == 11:
                    time.sleep(0.003)
                tl = msgs.get(i)
                mid = int(tl.id)
                if min_id is None or mid < min_id:
                    min_id = mid
                if mid in self.seen:
                    continue
                with tolerated():
                    tl.dialog_id = self.dialog_id
                with tolerated():
                    mo = MO(self.acc, tl, False, True)
                    if mo.isMusic():
                        self.seen.add(mid)
                        self.tracks.append(mo)
                        page_tracks.append(mo)
            with tolerated():
                self.total = max(self.total, int(res.count))
            cnt, tot = len(self.tracks), self.total
            now = time.monotonic()
            if now - getattr(self, "_prog_at", 0.0) >= 0.5:
                self._prog_at = now
                self._ui(lambda: self.on_progress(cnt, tot))
            if page_tracks and self.on_batch is not None:
                with tolerated():
                    batch = list(page_tracks)
                    if self.batch_on_ui:
                        self._ui(lambda b=batch, c=cnt, t=tot: self.on_batch(b, c, t))
                    else:
                        self.on_batch(batch, cnt, tot)
            exhausted = n == 0 or min_id is None or min_id == self._last_offset
            done = exhausted or len(self.tracks) >= self.cap
            if self.want is not None and self.want <= self.seen:
                done = True
            if self.total <= 0 and n < self.PAGE:
                done = True
            if self.min_id and min_id is not None and min_id <= self.min_id:
                done = True
            if done:
                self._finish(None)
            else:
                self._send(min_id)
        except Exception as e:
            self._finish(f"processing failed ({e})")
    def _finish(self, error):
        if self._finished:
            return
        self._finished = True
        with tolerated():
            self.tracks.sort(key=lambda m: int(m.getId()))
        tracks, cancelled = self.tracks, self.cancelled
        self._ui(lambda: self.on_done(tracks, error, cancelled))


_PERMANENT = frozenset((
    "CHANNEL_PRIVATE", "CHANNEL_INVALID", "CHANNEL_PUBLIC_GROUP_NA", "CHAT_FORBIDDEN", "CHAT_INVALID",
    "PEER_ID_INVALID", "USER_BANNED_IN_CHANNEL", "CHANNEL_BANNED", "INPUT_CHAT_INVALID",
))


def _permanent(err):
    return str(err or "").strip().upper() in _PERMANENT


def _chat_unreachable(chat):
    from . import availability as _avail
    try:
        if _avail._name(chat).lower().endswith("forbidden"):
            return True
        if bool(getattr(chat, "restricted", False)):
            return _avail.restricted_reason(getattr(chat, "restriction_reason", None))
    except Exception:
        pass
    return False


class _MsgResolver:
    BATCH = 100
    MAX_INFLIGHT = 3
    MAX_TRIES = 2
    PROG_KEY = ("resolve", "all")
    def __init__(self, plugin):
        self.p = plugin
        self.queue = collections.OrderedDict()
        self.flags = {}
        self.inflight = {}
        self.retrying = {}
        self.pf_wait = collections.OrderedDict()
        self.pf_active = False
        self.failed = set()
        self.tries = {}
        self.waiters = []
        self.active = 0
        self.total = 0
        self.done = 0
        self.gone = {}
        self.gone_loaded = False
        self.save_buf = []
        self.save_timer = None
        self.save_lock = threading.Lock()
    GONE_TTL = 3 * 86400
    def _load_gone(self):
        if self.gone_loaded:
            return
        self.gone_loaded = True
        with tolerated():
            with open(self.p._sstore.gone_path(), "r") as fh:
                data = json.load(fh)
            now = time.time()
            for s, ts in data.items():
                a, b = s.split(":")
                if now - float(ts) < self.GONE_TTL:
                    self.gone[(int(a), int(b))] = float(ts)
                    self.p._msg_missing.add((int(a), int(b)))
    def _is_gone(self, k):
        if k in self.p._msg_missing:
            return True
        self._load_gone()
        ts = self.gone.get(k)
        if ts is None:
            return False
        if time.time() - ts > self.GONE_TTL:
            self.gone.pop(k, None)
            return False
        return True
    def _mark_gone(self, k):
        self.p._msg_missing.add(k)
        self._load_gone()
        self.gone[k] = time.time()
        self._schedule_save()
    def _schedule_save(self):
        with self.save_lock:
            if self.save_timer is not None:
                return
            t = threading.Timer(1.5, self._flush)
            t.daemon = True
            self.save_timer = t
            t.start()
    def _persist(self, m):
        with tolerated():
            if self.p._sstore.enabled():
                self.save_buf.append(m)
                self._schedule_save()
    def _flush(self):
        with self.save_lock:
            self.save_timer = None
            buf, self.save_buf = self.save_buf, []
        with tolerated():
            if buf:
                self.p._sstore.add(buf)
            if self.gone_loaded:
                data = {"%d:%d" % k: ts for k, ts in list(self.gone.items())}
                tmp = self.p._sstore.gone_path() + ".tmp"
                with open(tmp, "w") as fh:
                    json.dump(data, fh)
                os.replace(tmp, self.p._sstore.gone_path())
    def _ui(self, fn):
        try:
            run_on_ui_thread(fn)
        except Exception:
            fn()
    def state(self, key):
        p = self.p
        k = (int(key[0]), int(key[1]))
        if k in p._msg_cache:
            return "ok"
        if self._is_gone(k):
            return "gone"
        if k in self.flags:
            return "loading"
        if k in self.failed:
            return "failed"
        return "idle"
    def request(self, keys, silent=False, on_done=None):
        self.request_tracks([{"i": int(k[0]), "d": int(k[1])} for k in keys],
       silent=silent, on_done=on_done)
    def retry(self, keys):
        keys = [(int(k[0]), int(k[1])) for k in keys]
        for k in keys:
            self.failed.discard(k)
            self.tries.pop(k, None)
        self.request(keys)
    def request_tracks(self, tracks, silent=False, on_done=None):
        p = self.p
        keys = []
        for t in tracks:
            try:
                k = (int(t["i"]), int(t["d"]))
            except Exception:
                continue
            keys.append(k)
            if k in p._msg_cache:
                continue
            if t.get("lf"):
                lm = p._local_message(t)
                if lm is not None:
                    p._msg_cache[k] = lm
                else:
                    p._msg_missing.add(k)
                continue
            if self._is_gone(k) or k in self.failed:
                continue
            if k in self.flags:
                if not silent and self.flags[k]:
                    self.flags[k] = False
                    self.total += 1
                continue
            self.flags[k] = bool(silent)
            if not silent:
                self.total += 1
            uid = 0
            try:
                uid = int(t.get("pf") or (t["d"] if t.get("pd") else 0) or 0)
            except Exception:
                uid = 0
            if uid:
                self.pf_wait.setdefault(uid, set()).add(k)
            else:
                self.queue[k] = True
        if on_done is not None:
            self.waiters.append((keys, on_done))
        self._progress()
        self._fire()
        self._pump_pf()
        self._pump()
    def _end(self, k):
        silent = self.flags.pop(k, True)
        if not silent:
            self.done += 1
    def _progress(self):
        p = self.p
        if not self.flags:
            self.total = self.done = 0
            p._prog_end(self.PROG_KEY)
        elif self.total > 0:
            p._prog_set(self.PROG_KEY, min(self.done, self.total), self.total)
    def _fire(self):
        if not self.waiters:
            return
        ready = [w for w in self.waiters if all(k not in self.flags for k in w[0])]
        if not ready:
            return
        self.waiters = [w for w in self.waiters if not any(w is r for r in ready)]
        for _keys, cb in ready:
            with tolerated():
                cb()
    def _after(self, changed=True):
        self._progress()
        self._fire()
        self._pump_pf()
        self._pump()
        with tolerated():
            self.p._ghost_flush()
        if changed:
            with tolerated():
                fn = getattr(getattr(self.p, "_editor", None), "_lib_resolver_refresh", None)
                if fn is not None:
                    fn()
    def _pump_pf(self):
        if self.pf_active or not self.pf_wait:
            return
        p = self.p
        uid, ks = self.pf_wait.popitem(last=False)
        self.pf_active = True
        fin = {"v": False}
        def done(msgs):
            if fin["v"]:
                return
            fin["v"] = True
            self.pf_active = False
            for m in msgs or []:
                mk = p._msg_key(m)
                if mk:
                    p._msg_cache[mk] = m
            for k in ks:
                if k not in p._msg_cache:
                    p._msg_missing.add(k)
                self._end(k)
            self._after()
        wd = threading.Timer(60.0, lambda: self._ui(lambda: done([])))
        wd.daemon = True
        wd.start()
        try:
            p._pm_profile_fetch(uid, int(p._chat_account(None, None)), done)
        except Exception:
            done([])
    def _pump(self):
        while self.active < self.MAX_INFLIGHT and self.queue:
            dlg = next(iter(self.queue))[1]
            ks = [k for k in self.queue if k[1] == dlg][:self.BATCH]
            for k in ks:
                self.queue.pop(k, None)
                self.inflight[k] = True
            self.active += 1
            self._send(dlg, [k[0] for k in ks])
    def _archive_then(self, dlg, mids, acc):
        loaded = self.p._archive_load(acc)
        self._ui(lambda: self._send(dlg, mids) if loaded else self._settle(dlg, mids, None))
    def _send(self, dlg, mids):
        from .sheets import _jc, _request_delegate
        p = self.p
        want = set(mids)
        channel = False
        try:
            acc = int(p._chat_account(None, None))
        except Exception:
            acc = 0
        if dlg < 0 and p._archive_unloaded(dlg, acc):
            threading.Thread(target=self._archive_then, args=(dlg, mids, acc), daemon=True).start()
            return
        st = {"done": False}
        def finish(found):
            if st["done"]:
                return
            st["done"] = True
            self._settle(dlg, mids, found)
        def bad():
            self._ui(lambda: finish(None))
        def watchdog():
            self._ui(lambda: finish(None))
        def on_resp(res, err):
            try:
                if st["done"]:
                    return
                if err is not None and _permanent(getattr(err, "text", "")):
                    self._ui(lambda: finish({}))
                    return
                if err is not None or res is None:
                    bad()
                    return
                with tolerated():
                    inst = _jc("org.telegram.messenger.MessagesController").getInstance(acc)
                    inst.putUsers(res.users, False)
                    inst.putChats(res.chats, False)
                MO = _jc("org.telegram.messenger.MessageObject")
                found = {}
                lst = res.messages
                for i in range(int(lst.size())):
                    tl = lst.get(i)
                    with tolerated():
                        mid = int(tl.id)
                        if mid not in want:
                            continue
                        if str(tl.getClass().getSimpleName()) == "TL_messageEmpty":
                            continue
                        if not channel:
                            try:
                                did = int(MO.getDialogId(tl))
                            except Exception:
                                did = 0
                            if did and did != dlg:
                                continue
                        tl.dialog_id = dlg
                        mo = MO(acc, tl, False, True)
                        try:
                            ok = bool(mo.isMusic())
                        except Exception:
                            ok = True
                        if ok:
                            found[mid] = mo
                self._ui(lambda: finish(found))
            except Exception:
                bad()
        with tolerated():
            wd = threading.Timer(20.0, watchdog)
            wd.daemon = True
            wd.start()
        try:
            MCtl = _jc("org.telegram.messenger.MessagesController").getInstance(acc)
            if dlg < 0:
                chat = MCtl.getChat(-dlg)
                if chat is None:
                    bad()
                    return
                if _chat_unreachable(chat):
                    self._ui(lambda: finish({}))
                    return
                channel = bool(_jc("org.telegram.messenger.ChatObject").isChannel(chat))
            if channel:
                req = _jc("org.telegram.tgnet.TLRPC$TL_channels_getMessages")()
                ic = MCtl.getInputChannel(-dlg)
                if ic is None:
                    bad()
                    return
                req.channel = ic
            else:
                req = _jc("org.telegram.tgnet.TLRPC$TL_messages_getMessages")()
            for mid in mids:
                try:
                    im = _jc("org.telegram.tgnet.TLRPC$TL_inputMessageID")()
                    im.id = int(mid)
                    req.id.add(im)
                except Exception:
                    req.id.add(jclass("java.lang.Integer")(int(mid)))
            _jc("org.telegram.tgnet.ConnectionsManager").getInstance(acc).sendRequest(
          req, _request_delegate(on_resp))
        except Exception:
            bad()
    def _fallback(self, dlg, mids):
        p = self.p
        want = set(mids)
        st = {"done": False}
        def done(found, err, cancelled):
            if st["done"]:
                return
            st["done"] = True
            for m in found or []:
                mk = p._msg_key(m)
                if mk:
                    p._msg_cache[mk] = m
                    if p._msg_cache.get(mk) is m:
                        self._persist(m)
            for mid in mids:
                k = (mid, dlg)
                self.inflight.pop(k, None)
                if k in p._msg_cache:
                    self.tries.pop(k, None)
                elif _permanent(err):
                    self._mark_gone(k)
                elif err or cancelled:
                    self.failed.add(k)
                else:
                    self._mark_gone(k)
                self._end(k)
            self._after()
        def timeout():
            self._ui(lambda: done([], "timeout", True))
        try:
            tm = threading.Timer(90.0, timeout)
            tm.daemon = True
            tm.start()
            _MusicFetcher(p, int(p._chat_account(None, None)), dlg, 0,
          lambda c, total: None, done, want=want).start()
        except Exception:
            done([], "error", True)
    def _settle(self, dlg, mids, found):
        p = self.p
        self.active = max(0, self.active - 1)
        again = []
        fb = []
        for mid in mids:
            k = (mid, dlg)
            self.inflight.pop(k, None)
            if found is not None:
                m = found.get(mid)
                if m is not None:
                    p._msg_cache[p._msg_key(m) or k] = m
                    if p._msg_cache.get(p._msg_key(m) or k) is m:
                        self._persist(m)
                else:
                    self._mark_gone(k)
                self.tries.pop(k, None)
                self._end(k)
            else:
                n = self.tries.get(k, 0) + 1
                self.tries[k] = n
                if n < self.MAX_TRIES:
                    self.retrying[k] = True
                    again.append(k)
                else:
                    self.inflight[k] = True
                    fb.append(mid)
        if fb:
            self._fallback(dlg, fb)
        if again:
            delay = 1.5 * max(self.tries[k] for k in again)
            def requeue():
                for k in again:
                    if self.retrying.pop(k, None):
                        self.queue[k] = True
                self._pump()
            timer = threading.Timer(delay, lambda: self._ui(requeue))
            timer.daemon = True
            timer.start()
        self._after()


class _TLCodec:
    _mode = None
    _layer = None
    @classmethod
    def layer(cls):
        from .sheets import _jc
        if cls._layer is None:
            try:
                cls._layer = int(_jc("org.telegram.tgnet.TLRPC").LAYER)
            except Exception:
                cls._layer = 0
        return cls._layer
    @staticmethod
    def dump(m):
        from .sheets import _jc
        try:
            with tolerated():
                o = m.messageOwner
                if o.message is None:
                    o.message = ""
                fl = int(o.flags)
                if o.from_id is not None:
                    fl |= 256
                if o.media is not None:
                    fl |= 512
                    if getattr(o.media, "document", None) is not None:
                        o.media.flags = int(o.media.flags) | 1
                o.flags = fl
            sd = _jc("org.telegram.tgnet.SerializedData")()
            m.messageOwner.serializeToStream(sd)
            arr = sd.toByteArray()
            try:
                return bytes(arr)
            except Exception:
                return bytes((b & 255) for b in arr)
        except Exception:
            return None
    @classmethod
    def load(cls, acc, dialog_id, blob):
        from .sheets import _jc
        try:
            SD = _jc("org.telegram.tgnet.SerializedData")
            makers = (
          lambda b: b,
          lambda b: jarray(jbyte)(b),
          lambda b: jarray(jbyte)([x - 256 if x > 127 else x for x in b]),
          )
            order = ([cls._mode] if cls._mode is not None else []) + \
          [i for i in range(3) if i != cls._mode]
            sd = None
            for i in order:
                try:
                    sd = SD(makers[i](blob))
                    cls._mode = i
                    break
                except Exception:
                    continue
            if sd is None:
                return None
            tl = _jc("org.telegram.tgnet.TLRPC$Message").TLdeserialize(sd, sd.readInt32(False), False)
            if tl is None:
                return None
            tl.dialog_id = int(dialog_id)
            return _jc("org.telegram.messenger.MessageObject")(int(acc), tl, False, True)
        except Exception:
            return None


class _ChatIndex:
    __slots__ = ("key", "path", "acc", "ts", "layer", "rows", "_by_id", "_min")
    def __init__(self, key, path, acc, ts, layer, rows):
        self.key, self.path, self.acc, self.ts, self.layer, self.rows = key, path, acc, ts, layer, rows
        self._by_id = None
        self._min = None
    def row_for(self, mid):
        if self._by_id is None:
            self._by_id = {int(r["i"]): r for r in self.rows}
        return self._by_id.get(int(mid))
    def minutes(self):
        if self._min is None:
            total = sum(max(0, int(r.get("s", 0) or 0)) for r in self.rows)
            self._min = max(1, int(round(total / 60.0))) if total else 0
        return self._min
