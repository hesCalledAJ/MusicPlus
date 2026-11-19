import collections
import json
import re
import time

from ..compat import find_class, jclass, run_on_ui_thread
from ..safe import tolerated
from elyx import strings

PID = "profile"
_LOG = collections.deque(maxlen=400)
_LOG_T0 = [time.monotonic()]


class _PluginProfileSync:
    _pp_last = None
    _pp_busy = False
    _pp_pull_busy = False
    _pp_pull_t = 0.0
    _pp_quiet = False
    _pp_again = False

    def _pp_log(self, msg):
        self._pp_act_t = time.monotonic()
        _LOG.append(time.strftime("%H:%M:%S") + ".%03d %s" % (int((time.time() % 1) * 1000), str(msg)[:420]))

    def _pp_state_line(self):
        pl = self._pp_pl()
        return ("STATE last=%s local=%s busy=%s pull_busy=%s again=%s failed=%s retries=%s timer=%s resolver(active=%s flags=%d pf_active=%s pf_wait=%d)" % (
            None if self._pp_last is None else len(self._pp_last), None if pl is None else len(pl["tracks"]),
            self._pp_busy, self._pp_pull_busy, self._pp_again, bool(self.__dict__.get("_pp_failed")),
            self.__dict__.get("_pp_retries", 0), bool(self.__dict__.get("_pp_timer")),
            getattr(self._resolver, "active", "?"), len(getattr(self._resolver, "flags", ())),
            getattr(self._resolver, "pf_active", "?"), len(getattr(self._resolver, "pf_wait", ()))))

    def _pp_show_log(self, title, force=False):
        now = time.monotonic()
        if not force and now - self.__dict__.get("_pp_log_shown", -99.0) < 20.0:
            return
        self._pp_log_shown = now
        self._pp_log(self._pp_state_line())
        with tolerated():
            from .. import crashlog
            crashlog.show_log(title, "\n".join(_LOG))

    def _pp_btn_set(self, busy, text=None):
        def ui():
            with tolerated():
                self._pp_btn_busy = bool(busy)
                b = self.__dict__.get("_pp_btn")
                if b is not None:
                    self._pp_btn_fill(b, busy, text)
        try:
            run_on_ui_thread(ui)
        except Exception:
            ui()

    def _pp_btn_fill(self, b, busy, text=None):
        root, host, label, ed = b
        host.removeAllViews()
        FLP = jclass("android.widget.FrameLayout$LayoutParams")
        if busy:
            pb = jclass("android.widget.ProgressBar")(ed.act)
            with tolerated():
                pb.setIndeterminateTintList(jclass("android.content.res.ColorStateList").valueOf(ed.c_text))
            pb.setPadding(ed.dp(9), ed.dp(9), ed.dp(9), ed.dp(9))
            host.addView(pb, FLP(-1, -1))
            with tolerated():
                tv = jclass("android.widget.TextView")(ed.act)
                tv.setGravity(17)
                tv.setTextSize(2, 7.0)
                tv.setTypeface(None, 1)
                tv.setTextColor(ed.c_text)
                tv.setIncludeFontPadding(False)
                last = ed.__dict__.get("_sync_pct_last")
                tv.setText("%d%%" % last if last is not None else "")
                host.addView(tv, FLP(-1, -1))
                ed._sync_pct_tv = tv
        else:
            host.addView(ed._glyph_icon(("msg_retry", "ic_refresh", "msg_reset"), ed.c_text, pad=8, size=22, bold=True), FLP(-1, -1))
        if label is not None:
            label.setText(text or ("Syncing" if busy else "Sync"))
        root.setEnabled(not busy)

    def _pp_loader_show(self, text=None):
        self._pp_btn_set(True, "Syncing")
        self._pp_loader_t = time.monotonic()
        t0 = self._pp_loader_t
        def ceiling():
            if self.__dict__.get("_pp_btn_busy") and self.__dict__.get("_pp_loader_t") == t0:
                self._pp_log("sync button auto-reset after 90s")
                self._pp_btn_set(False)
        self._post(ceiling, 90000)

    def _pp_loader_text(self, text):
        m = re.search(r"(\d+)/(\d+)", str(text or ""))
        self._pp_btn_set(True, "Syncing")
        if m and int(m.group(2)):
            ed = getattr(self, "_editor", None)
            if ed is not None:
                pct = min(99, int(100 * int(m.group(1)) / int(m.group(2))))
                run_on_ui_thread(lambda: ed._sync_pct_set(pct))

    def _pp_loader_hide(self):
        self._pp_btn_set(False)

    def _pp_pl(self, create=False):
        d = self._lib_data()
        for pl in d["playlists"]:
            if pl.get("id") == PID:
                return pl
        if not create:
            return None
        pl = {"id": PID, "name": "Profile Playlist", "tracks": [], "created": int(time.time())}
        at = 0
        for i, x in enumerate(d["playlists"]):
            if x.get("id") == "downloaded" or str(x.get("name", "")).strip().lower() == "liked songs":
                at = max(at, i + 1)
        d["playlists"].insert(at, pl)
        self._pp_quiet = True
        try:
            self._lib_save()
        finally:
            self._pp_quiet = False
        return pl

    def _pp_set_last(self, keys):
        self._pp_last = keys
        self._pp_seen = keys
        with tolerated():
            self.set_setting("pp_base_v1", json.dumps([list(k) for k in keys], separators=(",", ":")))

    def _pp_initial_sync(self, attempt=0):
        def go():
            with tolerated():
                pl = self._pp_pl(True)
                if attempt == 0 and self._pp_last is None:
                    base = None
                    with tolerated():
                        raw = self.get_setting("pp_base_v1", "")
                        base = tuple((int(a), int(b)) for a, b in json.loads(raw)) if raw else None
                    if base is not None and pl is not None and self._pp_keys(pl) != base:
                        self._pp_last = base
                def done():
                    if self._pp_last is None and attempt < 4:
                        self._pp_initial_sync(attempt + 1)
                self._pp_pull(True, done)
        self._post(go, 3000 if attempt == 0 else 6000 * attempt)

    @staticmethod
    def _pp_keys(pl):
        return tuple((int(t["i"]), int(t["d"])) for t in pl["tracks"])


    def _pp_changed(self):
        pl = self._pp_pl()
        if pl is None:
            return
        seen_k = self._pp_keys(pl)
        prev_k = self.__dict__.get("_pp_seen")
        self._pp_seen = seen_k
        if self._pp_quiet:
            return
        if prev_k is not None and seen_k == prev_k:
            return
        if self._pp_last is None:
            if self.__dict__.get("_pp_pending") is None and pl["tracks"]:
                self._pp_log("EDIT while not synced yet (initial pull never succeeded): connecting first, then pushing")
                self._pp_pending = [dict(t) for t in pl["tracks"]]
                self._pp_loader_show("Connecting to Telegram…")
                self._pp_pull(True)
            return
        if self._pp_keys(pl) == self._pp_last:
            return
        if self._pp_keys(pl) == self.__dict__.get("_pp_failed"):
            self._pp_log("EDIT ignored: same edit already failed (open the playlist to retry)")
            return
        now_k, was_k = set(self._pp_keys(pl)), set(self._pp_last or ())
        who = ""
        with tolerated():
            import traceback
            who = " < ".join(f.name for f in reversed(traceback.extract_stack(limit=8)[:-2]))
        self._pp_log("EDIT detected: local=%d last=%d (removed %d, added %d) by %s -> scheduling push" % (
            len(pl["tracks"]), len(self._pp_last), len(was_k - now_k), len(now_k - was_k), who[:160]))
        self._pp_loader_show("Saving to your profile…")
        self._pp_schedule()

    def _pp_schedule(self):
        if self.__dict__.get("_pp_timer"):
            return
        self._pp_timer = True
        def fire():
            self._pp_timer = False
            with tolerated():
                self._pp_push()
        self._post(fire, 250)

    def _pp_push(self):
        if self._pp_busy:
            self._pp_again = True
            return
        pl = self._pp_pl()
        if pl is None or self._pp_last is None:
            return
        tracks = [dict(t) for t in pl["tracks"]]
        keys = self._pp_keys(pl)
        if keys == self._pp_last:
            return
        self._pp_busy = True
        self._pp_log("PUSH start: local=%d tracks, last=%d" % (len(keys), len(self._pp_last or ())))
        acc = int(self._chat_account(None, None) or 0)
        need = [t for t in tracks if not t.get("pd") and dict.get(self._msg_cache, (int(t["i"]), int(t["d"]))) is None]

        fin_once = {"v": False}
        def finish(res):
            if fin_once["v"]:
                return
            fin_once["v"] = True
            self._pp_busy = False
            self._pp_loader_hide()
            self._pp_log("PUSH end: ok=%s err=%s" % (res.get("ok"), res.get("err")))
            if res.get("ok"):
                self._pp_retries = 0
                self.__dict__.pop("_pp_failed", None)
                self._pp_set_last(keys)
                self._pp_expect = set(res.get("placed") or ())
                parts = []
                if res.get("saved_n"):
                    parts.append("Saved %d to your profile" % res["saved_n"])
                if res.get("skipped"):
                    nm = ", ".join(res.get("names", [])[:3])
                    why = "not accepted as music" if "DOCUMENT_INVALID" in res.get("why", "") else res.get("why", "")
                    parts.append("couldn't save %s (%s)" % (nm or strings("n_failed", res["skipped"]), why))
                if parts:
                    self._profile_notify(" · ".join(parts), bool(res.get("skipped")))
                self._post(lambda: self._pp_pull(True), 3500)
            else:
                err = str(res.get("err") or "").upper()
                n = int(self.__dict__.get("_pp_retries", 0))
                transient = any(x in err for x in ("TIMEOUT", "EXC", "NETWORK", "CONNECTION", "INTERNAL", "-5", "FLOOD",
                                                   "NOT LOADED", "RETRIES"))
                if transient and n < 1:
                    self._pp_retries = n + 1
                    self._pp_loader_show("Retrying…"); self._post(self._pp_schedule, 800)
                else:
                    self._pp_retries = 0
                    self._pp_failed = keys
                    self._pp_failed_t = time.monotonic()
                    self._profile_notify(strings("profile_sync_failed", str(res.get("err") or "")[:40]), True)
                    self._pp_discard = True
                    self._pp_log("rolling local playlist back to Telegram's copy")
                    self._pp_pull(True)
                    self._pp_show_log("Profile playlist sync failed: " + str(res.get("err") or "")[:60])
            if self._pp_again:
                self._pp_again = False
                self._pp_schedule()

        def work():
            res = {"ok": False, "err": None}
            try:
                stopped = lambda: fin_once["v"]
                t0 = time.monotonic()
                remote, err = self._pm_current(acc, stopped)
                self._pp_log("fetched remote list: %d docs, err=%s, %dms" % (len(remote or ()), err, (time.monotonic() - t0) * 1000))
                if err:
                    raise RuntimeError(err)
                by_id = {int(d.id): d for d in remote}
                stale_ids = set()
                desired, seen = [], set()
                for t in tracks:
                    doc = by_id.get(int(t["pd"])) if t.get("pd") else None
                    m = None
                    if doc is None:
                        m = dict.get(self._msg_cache, (int(t["i"]), int(t["d"])))
                        doc = m.getDocument() if m is not None else None
                    if doc is None or int(doc.id) in seen:
                        continue
                    if m is not None:
                        self._pm_remember_src(doc, m)
                    seen.add(int(doc.id))
                    desired.append(doc)
                if tracks and not desired:
                    raise RuntimeError("tracks not loaded yet")
                to_refresh = [d for d in desired if int(d.id) not in by_id]
                self._pm_refresh_bulk(acc, to_refresh, stopped)
                fm = self.__dict__.get("_pm_fresh_map") or {}
                stale_ids = {int(d.id) for d in to_refresh if int(d.id) not in fm}
                if stale_ids:
                    self._pp_log("unrefreshable (will be skipped): %s" % sorted(stale_ids)[:8])
                want = {int(d.id) for d in desired}
                self._pp_log("plan: desired=%d resolved (of %d local), unresolved=%d" % (len(desired), len(tracks), len(tracks) - len(desired)))
                gone = [d for d in remote if int(d.id) not in want]
                self._pp_log("unsave %d: %s" % (len(gone), [int(d.id) for d in gone][:6]))
                if gone:
                    self._pm_unsave_many(acc, gone, stopped, lambda _t: None)
                cur = [int(d.id) for d in remote if int(d.id) in want]
                placed, failed, saved_n = [], [], 0
                fallback = False
                for d in desired:
                    did, i = int(d.id), len(placed)
                    if i < len(cur) and cur[i] == did:
                        placed.append(d)
                        continue
                    if stale_ids and did in stale_ids:
                        self._pp_log("skip id=%s: source message unreachable (stale file reference)" % did)
                        failed.append("FILE_REFERENCE_EXPIRED")
                        with tolerated():
                            res.setdefault("names", []).append(self._pm_doc_meta(d)[0] or str(did))
                        continue
                    after = placed[-1] if placed else None
                    if len(desired) > 1:
                        self._pp_loader_text("Saving %d/%d…" % (len(placed) + len(failed) + 1, len(desired)))
                    self._pp_log("save #%d id=%s after=%s" % (i, did, int(after.id) if after is not None else None))
                    ok, err = self._pm_save(acc, d, after, stopped, lambda _t: None)
                    self._pp_log("  -> ok=%s err=%s" % (ok, err))
                    if not ok:
                        failed.append(err or "SERVER_FALSE")
                        with tolerated():
                            res.setdefault("names", []).append(self._pm_doc_meta(d)[0] or str(did))
                        continue
                    if did in cur:
                        cur.remove(did)
                    cur.insert(i, did)
                    placed.append(d)
                    saved_n += 1
                    time.sleep(0.4)
                    if saved_n == 1:
                        time.sleep(1.5)
                        rem2, e2 = self._pm_current(acc, stopped)
                        ids2 = [int(x.id) for x in (rem2 or ())]
                        self._pp_log("CHECK after 1st save: Telegram has %d docs, saved doc present=%s, err=%s" % (len(ids2), did in ids2, e2))
                        if not e2 and did not in ids2:
                            self._pp_log("server accepted but ignored after_id save; switching to top-insert mode (reverse order, no after_id)")
                            fallback = True
                            break
                if fallback:
                    placed, failed, saved_n = [], [], 0
                    todo = [d for d in desired if not (stale_ids and int(d.id) in stale_ids)]
                    for k, d in enumerate(reversed(todo), 1):
                        self._pp_loader_text("Saving %d/%d…" % (k, len(todo)))
                        ok, err = self._pm_save(acc, d, None, stopped, lambda _t: None)
                        self._pp_log("save(top) id=%s -> ok=%s err=%s" % (int(d.id), ok, err))
                        if ok:
                            placed.insert(0, d)
                            saved_n += 1
                        else:
                            failed.append(err or "SERVER_FALSE")
                        time.sleep(0.4)
                    failed += ["FILE_REFERENCE_EXPIRED"] * len(stale_ids)
                if failed and not saved_n:
                    raise RuntimeError(failed[0])
                self._pp_tell_telegram(acc, placed, gone)
                res["saved_n"] = saved_n
                res["skipped"] = len(failed) + (len(tracks) - len(desired))
                res["placed"] = [int(d.id) for d in placed]
                res["why"] = failed[0] if failed else ""
                res["ok"] = True
            except Exception as e:
                res["err"] = str(e)
                if not isinstance(e, RuntimeError):
                    import traceback
                    for ln in traceback.format_exc().strip().split("\n")[-6:]:
                        self._pp_log("EXC " + ln.strip())
            run_on_ui_thread(lambda: finish(res))

        def start():
            import threading
            threading.Thread(target=work, daemon=True, name="smq-profile-push").start()

        go_once = {"v": False}
        def start_once():
            if go_once["v"]:
                return
            go_once["v"] = True
            start()
        self._pp_act_t = time.monotonic()
        def stuck():
            if fin_once["v"]:
                return
            idle = time.monotonic() - self.__dict__.get("_pp_act_t", 0.0)
            if idle < 60.0:
                self._post(stuck, 5000)
                return
            self._pp_log("PUSH STUCK: no progress for %ds -> forcing failure" % idle)
            finish({"ok": False, "err": "STUCK"})
        self._post(stuck, 20000)
        if need:
            self._pp_log("waiting for %d tracks to load from their chats" % len(need))
            self._post(lambda: (self._pp_log("track loading took >6s, continuing without waiting") if not go_once["v"] else None) or start_once(), 6000)
            self._resolver.request_tracks(need, silent=True, on_done=start_once)
        else:
            start_once()

    def _pp_tell_telegram(self, acc, desired, gone):
        with tolerated():
            MC = find_class("org.telegram.messenger.MessagesController").getInstance(int(acc))
            ids = MC.getSavedMusicIds()
            for d in gone:
                ids.update(int(d.id), False)
            for d in desired:
                ids.update(int(d.id), True)
        with tolerated():
            def upd():
                with tolerated():
                    SML = jclass("org.telegram.messenger.MessagesController$SavedMusicList")
                    lst = SML(int(acc), int(self._me(acc)))
                    if desired:
                        lst.list.add(lst.toMessageObject(desired[0]))
                    lst.updateFirstMusic()
            run_on_ui_thread(upd)


    def _pp_pull(self, force=False, done=None, min_gap=20.0, manual=False):
        pl = self._pp_pl(True)
        now = time.monotonic()
        if self._pp_pull_busy or self._pp_busy:
            if done is not None:
                with tolerated():
                    done()
            return
        if not force and now - self._pp_pull_t < min_gap:
            return
        discard = bool(self.__dict__.pop("_pp_discard", False))
        if discard:
            self.__dict__.pop("_pp_failed", None)
        if not discard and self._pp_last is not None and self._pp_keys(pl) != self._pp_last:
            if self._pp_keys(pl) == self.__dict__.get("_pp_failed") and \
                    time.monotonic() - self.__dict__.get("_pp_failed_t", 0.0) > 30.0:
                self.__dict__.pop("_pp_failed", None)
            self._pp_schedule()
            if done is not None:
                with tolerated():
                    done()
            return
        self._pp_pull_busy = True
        acc = int(self._chat_account(None, None) or 0)
        def work():
            docs, err, msgs = None, None, []
            try:
                t0 = time.monotonic()
                docs, err = self._pm_current(acc, lambda: False)
                self._pp_log("PULL: %d docs, err=%s, %dms" % (len(docs or ()), err, (time.monotonic() - t0) * 1000))
                me = self._me(acc)
                if not err:
                    for i, doc in enumerate(docs):
                        m = None
                        with tolerated():
                            m = self._pm_synthetic_music_message(acc, me, doc, i)
                            if m is not None and not bool(m.isMusic()):
                                m = None
                        ah = 0
                        with tolerated():
                            ah = int(doc.access_hash)
                        msgs.append((m, int(doc.id), ah))
            except Exception as e:
                err = str(e)
            run_on_ui_thread(lambda: apply(docs, err, msgs, me if not err else 0))
        def apply(docs, err, msgs, me):
            self._pp_pull_busy = False
            if err or docs is None:
                self._pp_log("PULL failed: %s" % err)
                if self.__dict__.pop("_pp_pending", None):
                    self._pp_log("dropping the unsynced local edit (Telegram unreachable)")
                    pl2 = self._pp_pl(True)
                    pl2["tracks"] = []
                    self._pp_quiet = True
                    try:
                        self._lib_save()
                    finally:
                        self._pp_quiet = False
                if not self._pp_busy:
                    self._pp_loader_hide()
                if manual:
                    self._profile_notify("Sync failed: " + str(err)[:60], True)
                else:
                    self._pp_show_log("Profile playlist pull failed: " + str(err)[:60])
                if done is not None:
                    with tolerated():
                        done()
                return
            self._pp_pull_t = time.monotonic()
            if not discard and self._pp_last is not None and self._pp_keys(self._pp_pl(True)) != self._pp_last:
                self._pp_log("PULL result dropped: you edited the playlist while it was loading; sending your edit instead")
                self._pp_schedule()
                if done is not None:
                    with tolerated():
                        done()
                return
            old = {int(t["pd"]): t for t in self._pp_pl(True)["tracks"] if t.get("pd")}
            tracks = []
            for m, pd, ah in msgs:
                t = None
                if m is not None:
                    k = self._msg_key(m)
                    if k is not None:
                        self._msg_cache[k] = m
                        with tolerated():
                            self._msg_missing.discard(k)
                            self._resolver.gone.pop(k, None)
                            self._resolver.failed.discard(k)
                        t = self._lib_track(m)
                if t is None:
                    t = old.get(pd)
                    if t is None:
                        continue
                    t = dict(t)
                t["pd"] = pd
                t["pf"] = int(me)
                if ah:
                    t["ph"] = ah
                src = self._pm_src_get(pd)
                if src:
                    t["ps"] = list(src)
                elif old.get(pd) and old[pd].get("ps"):
                    t["ps"] = old[pd]["ps"]
                tracks.append(t)
            keys = tuple((t["i"], t["d"]) for t in tracks)
            cur = self._pp_pl(True)
            changed = (self._pp_keys(cur) != keys or any(not t.get("pd") for t in cur["tracks"])
                       or [t.get("ps") for t in cur["tracks"]] != [t.get("ps") for t in tracks])
            exp = self.__dict__.pop("_pp_expect", None)
            if exp:
                miss = exp - {pd for _m, pd, _ah in msgs}
                self._pp_log("VERIFY: pushed %d, Telegram now has %d, missing=%d" % (len(exp), len(msgs), len(miss)))
                if miss:
                    self._profile_notify("Telegram said OK but didn't keep %d song(s)" % len(miss), True)
                    self._pp_show_log("Profile sync: Telegram didn't keep the songs", force=True)
            self._pp_set_last(keys)
            if manual:
                self._profile_notify("Synced \u00b7 %d songs" % len(tracks), False)
            pend = self.__dict__.pop("_pp_pending", None)
            if pend:
                have = {(int(t["i"]), int(t["d"])) for t in tracks}
                extra = [dict(t) for t in pend if (int(t["i"]), int(t["d"])) not in have]
                self._pp_log("merging %d locally added tracks into Telegram's %d" % (len(extra), len(tracks)))
                if extra:
                    tracks = tracks + extra
                    changed = True
            if changed:
                cur["tracks"] = tracks
                self._pp_quiet = True
                try:
                    self._lib_save()
                finally:
                    self._pp_quiet = False
                with tolerated():
                    ed = getattr(self, "_editor", None)
                    if ed is not None and ed.lib_state in (("pl", PID), ("home", None), "home"):
                        ed._lib_render()
            if pend and self._pp_keys(self._pp_pl(True)) != self._pp_last:
                self._pp_loader_text("Saving to your profile…")
                self._pp_schedule()
            elif not self._pp_busy and not self.__dict__.get("_pp_timer"):
                self._pp_loader_hide()
            if done is not None:
                with tolerated():
                    done()
        import threading
        threading.Thread(target=work, daemon=True, name="smq-profile-pull").start()
