import threading
from collections import OrderedDict

from ..compat import find_class, jclass, run_on_ui_thread
from ..safe import tolerated

_EMB_MAX = 80
_EMB_PX = 256


class _PluginCoverCache:
    def _emb_store(self):
        d = self.__dict__.get("_emb")
        if d is None:
            d = self._emb = OrderedDict()
            self._emb_busy = set()
            self._emb_sem = threading.Semaphore(2)
        return d

    def _info_cover(self, mc, pm):
        info = self._read(mc, "getAudioInfo") if mc is not None else None
        if info is None or pm is None:
            return None
        try:
            t_info = str(info.getTitle() or "").strip().lower()
            t_pm = str(pm.getMusicTitle() or "").strip().lower()
            if t_info and t_pm:
                if t_info != t_pm:
                    return None
            elif abs(int(info.getDuration()) / 1000.0 - float(pm.getDuration())) > 1.5:
                return None
        except Exception:
            return None
        return self._read(info, "getCover")

    def _emb_get(self, k):
        d = self._emb_store()
        v = d.get(k)
        if v is not None:
            d.move_to_end(k)
        return v

    def _emb_put(self, k, bmp):
        d = self._emb_store()
        if bmp is not None and bmp is not False:
            with tolerated():
                w, h = int(bmp.getWidth()), int(bmp.getHeight())
                if max(w, h) > _EMB_PX:
                    r = _EMB_PX / float(max(w, h))
                    bmp = jclass("android.graphics.Bitmap").createScaledBitmap(
                        bmp, max(1, int(w * r)), max(1, int(h * r)), True)
        d[k] = bmp if bmp is not None else False
        d.move_to_end(k)
        from ..helpers import mem_tight
        for _ in range(10 if mem_tight() else 0):
            if len(d) > 10:
                d.popitem(last=False)
        while len(d) > _EMB_MAX:
            d.popitem(last=False)

    def _emb_file(self, m):
        with tolerated():
            FL = find_class("org.telegram.messenger.FileLoader")
            f = FL.getInstance(int(m.currentAccount)).getPathToMessage(m.messageOwner)
            if f is not None and bool(f.exists()):
                return f
        with tolerated():
            path = m.messageOwner.attachPath
            if path and str(path).strip():
                f = jclass("java.io.File")(str(path))
                if bool(f.exists()):
                    return f
        return None

    def _emb_fetch(self, m, done) -> bool:
        d = self._emb_store()
        k = self._msg_key(m)
        if k is None or k in d or k in self._emb_busy or not self._is_downloaded(m):
            return False
        self._emb_busy.add(k)
        def work():
            bmp = None
            read = False
            try:
                with self._emb_sem:
                    f = self._emb_file(m)
                    if f is not None:
                        AI = find_class("org.telegram.messenger.audioinfo.AudioInfo")
                        info = AI.getAudioInfo(f)
                        if info is not None:
                            read = True
                            for getter in ("getSmallCover", "getCover"):
                                try:
                                    b = getattr(info, getter)()
                                except Exception:
                                    b = None
                                if b is not None:
                                    bmp = b
                                    break
            except Exception:
                bmp = None
            def finish():
                self._emb_busy.discard(k)
                if bmp is None and not read:
                    fails = self.__dict__.setdefault("_emb_fails", {})
                    fails[k] = fails.get(k, 0) + 1
                    if fails[k] < 4:
                        return
                self._emb_put(k, bmp)
                with tolerated():
                    done()
            run_on_ui_thread(finish)
        threading.Thread(target=work, daemon=True, name="smq-embcover").start()
        return True
