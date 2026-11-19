import random

from ..compat import run_on_ui_thread
from ..safe import tolerated
from elyx import strings

_MAX_GHOST_ROWS = 200


class _PluginQueueGhosts:
    _qghost = None

    def _lib_play_instant(self, tracks, keys, mode, start, shuffle, name, source_key):
        tmap = dict(zip(keys, tracks))
        cache, missing = self._msg_cache, self._msg_missing
        want = None
        if start is not None:
            want = (int(start[0]), int(start[1]))
            if want not in tmap:
                want = None
        if want is None:
            pool = [k for k in keys if k not in missing]
            if not pool:
                self._queue_expected_count = None
                self._pick_forget()
                self._bulletin(strings("those_tracks_arent_available_any_more"), error=True)
                return
            want = random.choice(pool[:50]) if shuffle else pool[0]
        resolver = self._resolver

        def begin():
            have = [cache.get(k) for k in keys]
            have = [m for m in have if m is not None]
            if not have:
                self._queue_expected_count = None
                self._pick_forget()
                failed = any(k in resolver.failed for k in keys)
                self._bulletin(strings("couldnt_load_those_tracks_check_your") if failed
                               else strings("those_tracks_arent_available_any_more"), error=True)
                return
            anchor = want if cache.get(want) is not None else self._msg_key(have[0])
            self._qghost = None
            self._lib_play_msgs(have, mode, anchor, shuffle, name, source_key=source_key, _jump_tried=True)
            idx = keys.index(anchor) if anchor in keys else 0
            rest = [k for k in keys[idx + 1:] + keys[:idx] if k not in cache and k not in missing]
            gone = sum(1 for k in keys if k in missing)
            if gone:
                self._bulletin(strings("n_tracks_unavailable_deleted_or_too", gone))
            if rest:
                self._qghost = {"order": keys, "pending": {k: tmap[k] for k in rest},
                                "anchor": anchor, "gone": 0}
                resolver.request_tracks([tmap[k] for k in rest])
                self._ghost_ui(False)
            else:
                self._queue_expected_count = None

        if cache.get(want) is None and want not in missing:
            self._bulletin(strings("loading_songs"))
            resolver.request_tracks([tmap[want]], on_done=begin)
        else:
            begin()

    def _ghost_list(self):
        g = self._qghost
        if not g or not g["pending"]:
            return []
        out = []
        for k in g["order"]:
            t = g["pending"].get(k)
            if t is not None:
                out.append((k, t, self._resolver.state(k)))
        return out

    def _ghost_ui(self, inserted):
        def run():
            ed = getattr(self, "_editor", None)
            if ed is None:
                return
            with tolerated():
                if ed.dialog.isShowing():
                    ed._ghost_changed(inserted)
        run_on_ui_thread(run)

    def _ghost_flush(self):
        if not self._qghost:
            return
        run_on_ui_thread(self._ghost_flush_ui)

    def _ghost_flush_ui(self):
        g = self._qghost
        if not g:
            return
        mc = self._get_mc()
        pl = self._get_playlist(mc) if mc is not None else None
        if pl is None or self._index_of(pl, g["anchor"][0], g["anchor"][1]) < 0:
            self._qghost = None
            self._queue_expected_count = None
            self._ghost_ui(True)
            return
        ready = []
        for k in list(g["pending"]):
            st = self._resolver.state(k)
            if st == "ok":
                m = self._msg_cache.get(k)
                g["pending"].pop(k)
                if m is not None and self._is_music(m):
                    ready.append((k, m))
            elif st == "gone":
                g["pending"].pop(k)
                g["gone"] += 1
        if ready:
            self._ghost_insert(mc, pl, g, ready)
        if not g["pending"] or all(self._resolver.state(k) == "failed" for k in g["pending"]):
            self._queue_expected_count = None
        if not g["pending"]:
            if g["gone"]:
                self._bulletin(strings("n_tracks_unavailable_deleted_or_too", g["gone"]))
            self._qghost = None
        self._ghost_ui(bool(ready))

    @staticmethod
    def _is_music(m):
        try:
            return bool(m.isMusic())
        except Exception:
            return False

    def _ghost_insert(self, mc, pl, g, ready):
        shuffle_on, rev = self._read_order()
        raw = [pl.get(i) for i in range(int(pl.size()))]
        L = raw if rev else raw[::-1]
        lkeys = [self._msg_key(x) if x is not None else None for x in L]
        have = set(k for k in lkeys if k is not None)
        pos = {k: i for i, k in enumerate(g["order"])}
        cur = self._current_index(mc)
        for k, m in sorted(ready, key=lambda km: pos.get(km[0], 0)):
            if k in have:
                continue
            oi = pos.get(k, len(g["order"]))
            ins = None
            for j in range(oi - 1, -1, -1):
                if g["order"][j] in have:
                    ins = lkeys.index(g["order"][j]) + 1
                    break
            if ins is None:
                for j in range(oi + 1, len(g["order"])):
                    if g["order"][j] in have:
                        ins = lkeys.index(g["order"][j])
                        break
            if ins is None:
                ins = len(lkeys)
            n = len(lkeys)
            raw_idx = ins if rev else n - ins
            try:
                pl.add(int(raw_idx), m)
            except Exception:
                continue
            lkeys.insert(ins, k)
            have.add(k)
            self._map_put(mc, m)
            if not shuffle_on and raw_idx <= cur:
                cur += 1
        with tolerated():
            if shuffle_on:
                self._shuffle_sync(mc, pl)
            else:
                self._set_int_field(mc, "currentPlaylistNum", cur)
