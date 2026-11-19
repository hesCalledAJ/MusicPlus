import collections
import json
import os
import struct
import threading
import time
from .compat import find_class
from .telegram_io import _ChatIndex, _TLCodec
from .safe import tolerated
from . import availability as _avail


class _TrackStore:
    MAGIC = b"SMQ1"
    VERSION = 1
    MAX_BYTES = 256 * 1024 * 1024
    IDX_CAP = 8
    def __init__(self, plugin):
        self.p = plugin
        self._dir_path = None
        self._lock = threading.RLock()
        self._wlock = threading.Lock()
        self._idx = collections.OrderedDict()
        self._by_dialog = None
        self._en = (0.0, True)
        self.broken = False
    def enabled(self):
        now = time.monotonic()
        if now - self._en[0] > 2.0:
            try:
                on = bool(self.p.get_setting("persist_track_cache", True))
            except Exception:
                on = False
            self._en = (now, on)
        return self._en[1] and not self.broken
    def _dir(self):
        if self._dir_path is None:
            ctx = find_class("org.telegram.messenger.ApplicationLoader").applicationContext
            path = os.path.join(str(ctx.getFilesDir().getAbsolutePath()), "smq_tracks")
            os.makedirs(path, exist_ok=True)
            self._dir_path = path
        return self._dir_path
    @staticmethod
    def _name(key):
        return "c_%d_%d.smq" % (int(key[0]), int(key[1]))
    @staticmethod
    def _parse(name):
        with tolerated():
            if name.startswith("c_") and name.endswith(".smq"):
                a, b = name[2:-4].rsplit("_", 1)
                return (int(a), int(b))
        return None
    @staticmethod
    def _remove(path):
        with tolerated():
            os.remove(path)
    def keys(self):
        try:
            return [k for k in (self._parse(n) for n in os.listdir(self._dir())) if k]
        except Exception:
            return []
    def _dialogs(self):
        with self._lock:
            if self._by_dialog is None:
                m = {}
                for k in self.keys():
                    m.setdefault(k[0], []).append(k)
                self._by_dialog = m
            return self._by_dialog
    def load_index(self, key):
        key = (int(key[0]), int(key[1]))
        with self._lock:
            idx = self._idx.get(key)
            if idx is not None:
                self._idx.move_to_end(key)
                return idx
        path = os.path.join(self._dir(), self._name(key))
        try:
            with open(path, "rb") as fh:
                fh.seek(-8, os.SEEK_END)
                tail = fh.read(8)
                if tail[4:] != self.MAGIC:
                    raise ValueError("bad magic")
                hl = struct.unpack("<I", tail[:4])[0]
                fh.seek(-8 - hl, os.SEEK_END)
                head = json.loads(fh.read(hl).decode("utf-8"))
            if int(head.get("v", 0)) != self.VERSION:
                raise ValueError("schema %s" % head.get("v"))
        except FileNotFoundError:
            return None
        except Exception:
            self._remove(path)
            with self._lock:
                self._by_dialog = None
            return None
        idx = _ChatIndex(key, path, int(head.get("acc", 0)), float(head.get("ts", 0)),
       int(head.get("layer", 0)), head.get("rows") or [])
        with self._lock:
            self._idx[key] = idx
            while len(self._idx) > self.IDX_CAP:
                self._idx.popitem(last=False)
        return idx
    @staticmethod
    def _row(m):
        from .editor import _QueueEditor
        try:
            try:
                dur = int(m.getDuration())
            except Exception:
                dur = 0
            return {"i": int(m.getId()), "d": int(m.getDialogId()),
          "t": _QueueEditor._title_of(m), "a": _QueueEditor._author_of(m), "s": dur}
        except Exception:
            return None
    def save(self, key, objs, acc):
        key = (int(key[0]), int(key[1]))
        path = os.path.join(self._dir(), self._name(key))
        tmp = path + ".tmp"
        rows, pos = [], 0
        with self._wlock:
            try:
                with open(tmp, "wb") as fh:
                    for m in objs:
                        blob = _TLCodec.dump(m)
                        row = self._row(m) if blob else None
                        if row is None:
                            continue
                        row["o"], row["l"] = pos, len(blob)
                        fh.write(blob)
                        pos += len(blob)
                        rows.append(row)
                    if not rows:
                        raise RuntimeError("nothing serialisable")
                    ts = time.time()
                    head = json.dumps({"v": self.VERSION, "layer": _TLCodec.layer(), "acc": int(acc),
                "ts": ts, "key": list(key), "rows": rows},
                separators=(",", ":")).encode("utf-8")
                    fh.write(head)
                    fh.write(struct.pack("<I", len(head)))
                    fh.write(self.MAGIC)
                    fh.flush()
                    with tolerated():
                        os.fsync(fh.fileno())
                os.replace(tmp, path)
            except Exception:
                self._remove(tmp)
                if not rows and objs:
                    self.broken = True
                return None
            idx = _ChatIndex(key, path, int(acc), ts, _TLCodec.layer(), rows)
            with self._lock:
                self._idx[key] = idx
                self._idx.move_to_end(key)
                while len(self._idx) > self.IDX_CAP:
                    self._idx.popitem(last=False)
                self._by_dialog = None
            self._prune()
            return idx
    def append(self, key, objs, acc):
        key = (int(key[0]), int(key[1]))
        idx = self.load_index(key)
        if idx is None:
            return None
        path = os.path.join(self._dir(), self._name(key))
        tmp = path + ".tmp"
        have = {int(r["i"]) for r in idx.rows}
        new_rows = []
        with self._wlock:
            try:
                end = max((int(r["o"]) + int(r["l"]) for r in idx.rows), default=0)
                with open(path, "rb") as src, open(tmp, "wb") as fh:
                    left = end
                    while left > 0:
                        chunk = src.read(min(1 << 20, left))
                        if not chunk:
                            raise RuntimeError("short read")
                        fh.write(chunk)
                        left -= len(chunk)
                    pos = end
                    for m in objs:
                        try:
                            if int(m.getId()) in have:
                                continue
                        except Exception:
                            continue
                        blob = _TLCodec.dump(m)
                        row = self._row(m) if blob else None
                        if row is None:
                            continue
                        row["o"], row["l"] = pos, len(blob)
                        fh.write(blob)
                        pos += len(blob)
                        new_rows.append(row)
                    rows = sorted(new_rows, key=lambda r: -int(r["i"])) + list(idx.rows)
                    ts = time.time()
                    head = json.dumps({"v": self.VERSION, "layer": _TLCodec.layer(), "acc": int(acc),
                "ts": ts, "key": list(key), "rows": rows},
                separators=(",", ":")).encode("utf-8")
                    fh.write(head)
                    fh.write(struct.pack("<I", len(head)))
                    fh.write(self.MAGIC)
                    fh.flush()
                    with tolerated():
                        os.fsync(fh.fileno())
                os.replace(tmp, path)
            except Exception:
                self._remove(tmp)
                return None
            new_idx = _ChatIndex(key, path, int(acc), ts, _TLCodec.layer(), rows)
            with self._lock:
                self._idx[key] = new_idx
                self._idx.move_to_end(key)
                self._by_dialog = None
            return new_idx
    def hydrate(self, idx, row):
        try:
            with open(idx.path, "rb") as fh:
                fh.seek(int(row["o"]))
                blob = fh.read(int(row["l"]))
            if not blob:
                return None
            return _TLCodec.load(idx.acc, int(row["d"]), blob)
        except Exception:
            return None
    def find(self, mid, dialog_id):
        for key in list(self._dialogs().get(int(dialog_id), ())):
            idx = self.load_index(key)
            if idx is not None:
                row = idx.row_for(mid)
                if row is not None:
                    return idx, row
        return None
    def drop(self, key):
        key = (int(key[0]), int(key[1]))
        with self._wlock:
            with self._lock:
                self._idx.pop(key, None)
                self._by_dialog = None
            self._remove(os.path.join(self._dir(), self._name(key)))
    def clear(self):
        freed = 0
        with self._wlock:
            with self._lock:
                self._idx.clear()
                self._by_dialog = None
            with tolerated():
                d = self._dir()
                for n in os.listdir(d):
                    if n.endswith(".smq") or n.endswith(".tmp"):
                        fp = os.path.join(d, n)
                        with tolerated():
                            freed += os.path.getsize(fp)
                        self._remove(fp)
        return freed
    def _prune(self):
        with tolerated():
            d = self._dir()
            files, total = [], 0
            for n in os.listdir(d):
                if n.endswith(".smq"):
                    fp = os.path.join(d, n)
                    st = os.stat(fp)
                    files.append((st.st_mtime, st.st_size, fp))
                    total += st.st_size
            files.sort()
            while total > self.MAX_BYTES and len(files) > 1:
                _, size, fp = files.pop(0)
                self._remove(fp)
                total -= size
                k = self._parse(os.path.basename(fp))
                with self._lock:
                    if k:
                        self._idx.pop(k, None)
                    self._by_dialog = None


class _SongStore(_TrackStore):
    MAX_BYTES = 64 * 1024 * 1024
    def _dir(self):
        if self._dir_path is None:
            ctx = find_class("org.telegram.messenger.ApplicationLoader").applicationContext
            path = os.path.join(str(ctx.getFilesDir().getAbsolutePath()), "smq_songs")
            os.makedirs(path, exist_ok=True)
            self._dir_path = path
        return self._dir_path
    def add(self, objs):
        by_dlg = {}
        for m in objs:
            with tolerated():
                by_dlg.setdefault(int(m.getDialogId()), []).append(m)
        for dlg, items in by_dlg.items():
            try:
                acc = int(items[0].currentAccount)
            except Exception:
                acc = 0
            key = (dlg, 0)
            if self.load_index(key) is not None:
                self.append(key, items, acc)
            else:
                self.save(key, items, acc)
    def gone_path(self):
        return os.path.join(self._dir(), "gone.json")


class _MessageIndex(collections.OrderedDict):
    CAP = 4000
    def __init__(self, store, extra=None):
        super().__init__()
        self._store = store
        self._extra = extra
        self._rl = threading.RLock()
    def __setitem__(self, k, v):
        with self._rl:
            old = dict.get(self, k)
            if old is not None and v is not None and old is not v:
                with tolerated():
                    if _avail.gone(v) and _avail.has_local_copy(old):
                        self.move_to_end(k)
                        return
            super().__setitem__(k, v)
            with tolerated():
                self.move_to_end(k)
            while len(self) > self.CAP:
                self.popitem(last=False)
    def _load(self, k):
        for st in (self._store, self._extra):
            try:
                if st is None or not st.enabled():
                    continue
                hit = st.find(k[0], k[1])
                if hit is None:
                    continue
                m = st.hydrate(*hit)
                if m is not None:
                    self[k] = m
                    return m
            except Exception:
                continue
        return None
    def get(self, k, default=None):
        v = dict.get(self, k)
        if v is None:
            v = self._load(k)
        return default if v is None else v
    def __getitem__(self, k):
        if dict.__contains__(self, k):
            return dict.__getitem__(self, k)
        v = self._load(k)
        if v is None:
            raise KeyError(k)
        return v
    def __contains__(self, k):
        if dict.__contains__(self, k):
            return True
        for st in (self._store, self._extra):
            with tolerated():
                if st is not None and st.enabled() and st.find(k[0], k[1]) is not None:
                    return True
        return False


class _LazyTracks:
    def __init__(self, cache, key, idx=None, objs=None):
        self._cache, self.key, self._idx, self._objs = cache, key, idx, objs
    @property
    def rows(self):
        idx = self._idx
        return idx.rows if (idx is not None and self._objs is None) else None
    @property
    def minutes(self):
        idx = self._idx
        return idx.minutes() if (idx is not None and self._objs is None) else None
    def __len__(self):
        objs = self._objs
        if objs is not None:
            return len(objs)
        idx = self._idx
        return len(idx.rows) if idx is not None else 0
    def __bool__(self):
        return len(self) > 0
    def __getitem__(self, n):
        if isinstance(n, slice):
            return [self[i] for i in range(*n.indices(len(self)))]
        objs = self._objs
        if objs is not None:
            return objs[n]
        idx = self._idx
        rows = idx.rows if idx is not None else ()
        if n < 0:
            n += len(rows)
        if n < 0 or n >= len(rows):
            raise IndexError(n)
        row = rows[n]
        k = (int(row["i"]), int(row["d"]))
        msgs = self._cache.p._msg_cache
        m = dict.get(msgs, k)
        if m is None:
            m = self._cache.store.hydrate(idx, row)
            if m is not None:
                msgs[k] = m
        return m
    def __iter__(self):
        for i in range(len(self)):
            try:
                yield self[i]
            except IndexError:
                return
    def __reversed__(self):
        for i in range(len(self) - 1, -1, -1):
            try:
                yield self[i]
            except IndexError:
                return
    def __add__(self, other):
        return list(self) + list(other)
    def __radd__(self, other):
        return list(other) + list(self)


class _ProgressiveChatTracks:
    def __init__(self, base=None, tail=None):
        self.base = base if base is not None else []
        self.tail = tail if tail is not None else []
    def __len__(self):
        return len(self.base) + len(self.tail)
    def __bool__(self):
        return len(self) > 0
    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self[n] for n in range(*i.indices(len(self)))]
        n = int(i)
        base_n = len(self.base)
        if n < 0:
            n += base_n + len(self.tail)
        if n < 0 or n >= base_n + len(self.tail):
            raise IndexError(n)
        return self.base[n] if n < base_n else self.tail[n - base_n]
    def __iter__(self):
        for i in range(len(self)):
            yield self[i]
    @property
    def rows(self):
        return getattr(self.base, "rows", None)


class _IndexedTrackView:
    def __init__(self, base, indices):
        self.base = base
        self.indices = indices if indices is not None else []
    def __len__(self):
        return len(self.indices)
    def __bool__(self):
        return len(self.indices) > 0
    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self[n] for n in range(*i.indices(len(self)))]
        n = int(i)
        if n < 0:
            n += len(self.indices)
        if n < 0 or n >= len(self.indices):
            raise IndexError(n)
        return self.base[int(self.indices[n])]
    def __iter__(self):
        for i in range(len(self.indices)):
            yield self[i]
    @property
    def rows(self):
        rows = getattr(self.base, "rows", None)
        if rows is None:
            return None
        try:
            return [rows[int(i)] for i in self.indices if 0 <= int(i) < len(rows)]
        except Exception:
            return None


class _TrackCache:
    MEM_CAP = 6
    def __init__(self, plugin, store):
        self.p, self.store = plugin, store
        self._mem = collections.OrderedDict()
        self._off = set()
        self._gen = {}
        self._lock = threading.RLock()
        self._layer = None
    @staticmethod
    def _k(key):
        return (int(key[0]), int(key[1]))
    def _layer_ok(self, idx):
        if self._layer is None:
            self._layer = _TLCodec.layer()
        return not self._layer or not idx.layer or idx.layer == self._layer
    def _trim(self):
        for k in list(self._mem):
            if len(self._mem) <= self.MEM_CAP:
                break
            if self._mem[k]._objs is None:
                del self._mem[k]
    def get(self, key, default=None):
        key = self._k(key)
        with self._lock:
            lz = self._mem.get(key)
            if lz is not None:
                self._mem.move_to_end(key)
                return lz
            if key in self._off or not self.store.enabled():
                return default
        idx = self.store.load_index(key)
        if idx is None or not self._layer_ok(idx):
            return default
        lz = _LazyTracks(self, key, idx=idx)
        with self._lock:
            self._mem[key] = lz
            self._trim()
        self.p.__dict__.setdefault("_lib_fresh", {}).setdefault(("c",) + key, idx.ts)
        return lz
    def __getitem__(self, key):
        v = self.get(key)
        if v is None:
            raise KeyError(key)
        return v
    def __setitem__(self, key, msgs):
        key = self._k(key)
        if isinstance(msgs, _LazyTracks):
            with self._lock:
                self._off.discard(key)
                self._mem[key] = msgs
            return
        objs = [m for m in (msgs or []) if m is not None]
        lz = _LazyTracks(self, key, objs=objs)
        with self._lock:
            self._off.discard(key)
            gen = self._gen[key] = self._gen.get(key, 0) + 1
            self._mem[key] = lz
            self._mem.move_to_end(key)
            self._trim()
        if objs and self.store.enabled():
            threading.Thread(target=self._persist, args=(key, lz, objs, gen),
          daemon=True, name="smq-track-save").start()
    def _persist(self, key, lz, objs, gen):
        with tolerated():
            if self._gen.get(key) != gen:
                return
            try:
                acc = int(objs[0].currentAccount)
            except Exception:
                try:
                    acc = int(find_class("org.telegram.messenger.UserConfig").selectedAccount)
                except Exception:
                    acc = 0
            idx = self.store.save(key, objs, acc)
            if idx is None or self._gen.get(key) != gen:
                return
            if len(idx.rows) == len(objs):
                lz._idx = idx
                lz._objs = None
    def pop(self, key, default=None):
        key = self._k(key)
        with self._lock:
            lz = self._mem.pop(key, None)
            self._off.add(key)
            self._gen[key] = self._gen.get(key, 0) + 1
        return default if lz is None else lz
    def revive(self, key):
        key = self._k(key)
        with self._lock:
            self._off.discard(key)
        return self.get(key)
    def forget(self, key):
        self.pop(key)
        self.store.drop(self._k(key))
    def __contains__(self, key):
        try:
            return self.get(key) is not None
        except Exception:
            return False
    def keys(self):
        with self._lock:
            ks = set(self._mem)
            off = set(self._off)
        if self.store.enabled():
            ks.update(self.store.keys())
        return sorted(k for k in ks if k not in off)
    def __iter__(self):
        return iter(self.keys())
    def __len__(self):
        return len(self.keys())
    def values(self):
        return [v for v in (self.get(k) for k in self.keys()) if v is not None]
    def items(self):
        return [(k, v) for k, v in ((k, self.get(k)) for k in self.keys()) if v is not None]
    def clear(self):
        with self._lock:
            self._mem.clear()
            self._off.clear()
            self._gen.clear()
