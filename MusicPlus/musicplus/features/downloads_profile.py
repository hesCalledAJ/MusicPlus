import json
import re
import threading
import time
from ..compat import (
 ArrayList,
 MethodHook,
 find_class,
 get_last_fragment,
 get_private_field,
 jclass,
 run_on_ui_thread,
)
from ..meta import (
 _PLUGIN_ID,
 _PLUGIN_NAME,
 _PLUGIN_VERSION,
 _UPDATE_CHANNEL,
 _UPDATE_MSG_ID,
 _UPDATE_NAME,
)
from elyx import strings
from ..helpers import _pm_list, _tl_resolve
from ..compat import jarray, jbyte
from ..android import _proxy
from ..editor import _QueueEditor
from ..sheets import _jc, _request_delegate
from ..native_sheets import _ProgressSheet
from .. import reflect
from .. import availability as _avail
from ..safe import report_exception, tolerated


class _PluginDownloadsProfile:

    @staticmethod
    def _unavailable(m) -> bool:
        return _avail.unavailable(m)

    def _cancel_downloads(self, msgs):
        msgs = self._dl_norm(msgs)
        canc = self._dl_cancelled_set()
        n = 0
        FL = find_class("org.telegram.messenger.FileLoader")
        for m in msgs:
            with tolerated():
                k = self._msg_key(m)
                if k is not None:
                    canc.add(k)
                if self._is_loading(m):
                    loader = FL.getInstance(int(m.currentAccount))
                    try:
                        loader.cancelLoadFile(m.getDocument())
                    except Exception:
                        loader.cancelLoadFile(str(FL.getAttachFileName(m.getDocument())))
                    n += 1
        self._bulletin(strings("cancelled_n_downloads", n) if n else strings("nothing_was_downloading"))

    def _start_batched(self, msgs, size=8, gap=250):
        msgs = list(msgs)
        canc = self._dl_cancelled_set()
        def step(i):
            for m in msgs[i:i + size]:
                with tolerated():
                    if self._msg_key(m) in canc:
                        continue
                self._start_download(m)
            if i + size < len(msgs):
                self._post(lambda: step(i + size), gap)
        step(0)

    def _download_tracks(self, msgs):
        msgs = self._dl_norm(msgs)
        if not msgs:
            self._bulletin(strings("no_available_tracks_to_download"), error=True)
            return
        todo = []
        gone = 0
        for m in msgs:
            try:
                if self._is_downloaded(m):
                    continue
                if self._unavailable(m):
                    gone += 1
                elif not self._is_loading(m):
                    todo.append(m)
            except Exception:
                todo.append(m)
        if gone and not todo and not any(self._is_loading(m) for m in msgs):
            self._bulletin(strings("no_available_tracks_to_download"), error=True)
            return
        if not todo:
            self._bulletin(strings("already_downloading") if any(self._is_loading(m) for m in msgs) else (strings("already_downloaded") if len(msgs) == 1 else strings("all_of_them_are_already_downloaded")))
            return
        canc = self._dl_cancelled_set()
        for m in todo:
            canc.discard(self._msg_key(m))
        self._start_batched(todo)
        self._bulletin(strings("downloading_n_tracks", len(todo)) + (" · " + strings("n_unavailable", gone) if gone else ""))

    def _save_to_music(self, msgs):
        msgs = self._dl_norm(msgs)
        if not msgs:
            return
        if len(msgs) > 100:
            self._bulletin(strings("save_up_to_100_tracks_at"), error=True)
            return
        pending = [m for m in msgs if not self._is_downloaded(m) and not self._unavailable(m)]
        msgs = [m for m in msgs if not self._unavailable(m)]
        if not msgs:
            self._bulletin(strings("no_available_tracks_to_save"), error=True)
            return
        if not pending:
            self._music_save_all(msgs)
            return
        canc = self._dl_cancelled_set()
        for m in pending:
            canc.discard(self._msg_key(m))
        n = len(pending)
        self._bulletin(strings("downloading_n_tracks_will_save_to", n))
        job = {"msgs": msgs, "pending": pending, "queue": list(pending), "started": set(),
       "t0": time.time(), "kick": time.time()}
        self._music_wait(job)

    def _music_wait(self, job):
        with tolerated():
            job["pending"] = [m for m in job["pending"] if not self._is_downloaded(m)]
            if not job["pending"]:
                self._music_save_all(job["msgs"])
                return
            canc = self._dl_cancelled_set()
            if any(self._msg_key(m) in canc for m in job["pending"]):
                self._bulletin(strings("cancelled_saving_to_music"))
                return
            now = time.time()
            if now - job["t0"] > 900:
                ready = [m for m in job["msgs"] if self._is_downloaded(m)]
                self._bulletin(strings("gave_up_waiting_for_n_download", len(job['pending'])), error=True)
                if ready:
                    self._music_save_all(ready)
                return
            q = job["queue"]
            batch, job["queue"] = q[:10], q[10:]
            for m in batch:
                job["started"].add(self._msg_key(m))
                self._start_download(m)
            if now - job["kick"] > 6:
                job["kick"] = now
                for m in job["pending"]:
                    if self._msg_key(m) in job["started"] and not self._is_loading(m):
                        self._start_download(m)
            self._post(lambda: self._music_wait(job), 800)

    def _toast_ui(self, text, error=False):
        def _t():
            with tolerated():
                ctx = find_class("org.telegram.messenger.ApplicationLoader").applicationContext
                jclass("android.widget.Toast").makeText(ctx, str(text), 1 if error else 0).show()
        try:
            run_on_ui_thread(_t)
        except Exception:
            _t()

    def _music_save_all(self, msgs):
        total = len(msgs)
        st = {"ok": 0, "bad": 0, "done": False, "err": ""}
        def finish(force=False):
            if st["done"]:
                return
            if not force and st["ok"] + st["bad"] < total:
                return
            st["done"] = True
            ok, bad = st["ok"], st["bad"] + max(0, total - st["ok"] - st["bad"])
            if ok and not bad:
                self._toast_ui(strings("saved_to_music") if ok == 1 else strings("saved_n_tracks_to_music", ok))
            elif ok:
                self._toast_ui(strings("saved_n_tracks_n_failed", ok, bad), True)
            else:
                why = st["err"].strip()
                self._bulletin(strings("couldnt_save_to_music") + (f" ({why})" if why else ""), error=True)
                self._toast_ui(strings("couldnt_save_to_music") + (f" ({why})" if why else ""), True)
        def report(ok, err=""):
            def _u():
                if ok:
                    st["ok"] += 1
                else:
                    st["bad"] += 1
                    st["err"] = err or st["err"]
                finish()
            try:
                run_on_ui_thread(_u)
            except Exception:
                _u()
        for m in msgs:
            self._save_music_file(m, report)
        self._post(lambda: finish(True), 25000)

    def _msg_local_file(self, msg):
        FL = find_class("org.telegram.messenger.FileLoader")
        acc = int(msg.currentAccount)
        doc = msg.getDocument()
        cands = []
        for fn in (lambda: FL.getInstance(acc).getPathToMessage(msg.messageOwner),
       lambda: FL.getPathToAttach(doc),
       lambda: FL.getPathToAttach(doc, True),
       lambda: jclass("java.io.File")(str(msg.messageOwner.attachPath))):
            with tolerated():
                cands.append(fn())
        for f in cands:
            with tolerated():
                if f is not None and bool(f.exists()) and int(f.length()) > 0:
                    return f
        return None

    def _save_music_file(self, msg, report):
        err = ""
        try:
            f = self._msg_local_file(msg)
            if f is None:
                report(False, "file not found on device")
                return
            doc = msg.getDocument()
            title, artist = "", ""
            with tolerated():
                title, artist = _QueueEditor._title_of(msg), _QueueEditor._author_of(msg)
            name = str(msg.getFileName() or "").strip()
            if "." not in name:
                base = (f"{artist} - {title}" if artist and title else title or "audio")
                base = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in base).strip()[:100] or "audio"
                name = base + ".mp3"
            mime = str(getattr(doc, "mime_type", "") or "")
            if not mime.startswith("audio/"):
                mime = "audio/mpeg"
            path = str(f.getAbsolutePath())
            self._save_music_via_telegram(path, name, mime, report)
            return
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        report(False, err[:90])

    def _save_music_via_telegram(self, path, name, mime, report):
        try:
            MC = find_class("org.telegram.messenger.MediaController")
            ctx = None
            try:
                frag = get_last_fragment()
                ctx = frag.getParentActivity() if frag is not None else None
            except Exception:
                ctx = None
            if ctx is None:
                ctx = find_class("org.telegram.messenger.ApplicationLoader").applicationContext
            cb = _proxy("org.telegram.messenger.Utilities$Callback", "run")(
          lambda uri=None: report(uri is not None, strings("telegram_couldnt_save_the_file")))
            MC.saveFile(path, ctx, 3, name, mime, cb)
        except Exception as e:
            report(False, f"{type(e).__name__}: {e}"[:90])

    def _profile_playlist_sheet(self, act, name, get_items, count=None):
        def go():
            get_items(lambda its: self._profile_apply(act, its, "replace", name))
        self._pp_confirm_replace(act, go)

    def _pp_confirm_replace(self, act, on_yes):
        msg = ("This list will replace your current profile playlist.\n\n"
               "To keep your current list, use \"Add to\" instead: it appends to it.")
        def build_telegram(a):
            b = _jc("org.telegram.ui.ActionBar.AlertDialog$Builder")(a)
            click = _proxy("org.telegram.ui.ActionBar.AlertDialog$OnButtonClickListener", "onClick")
            b.setTitle(strings("setting_profile_playlist"))
            b.setMessage(msg)
            b.setPositiveButton(strings("continue"), click(lambda d, w: on_yes()))
            b.setNegativeButton(strings("cancel"), click(lambda d, w: None))
            return b.create()
        def build_android(a):
            b = jclass("android.app.AlertDialog$Builder")(a)
            click = _proxy("android.content.DialogInterface$OnClickListener", "onClick")
            b.setTitle(strings("setting_profile_playlist"))
            b.setMessage(msg)
            b.setPositiveButton(strings("continue"), click(lambda d, w: on_yes()))
            b.setNegativeButton(strings("cancel"), click(lambda d, w: None))
            return b.create()
        def show():
            for build in (build_telegram, build_android):
                try:
                    build(act).show()
                    return
                except Exception:
                    continue
            on_yes()
        try:
            run_on_ui_thread(show)
        except Exception:
            show()

    @staticmethod
    def _pm_pair(title, artist):
        def norm(x):
            return re.sub(r"[\W_]+", "", str(x or "").lower(), flags=re.UNICODE)
        t, a = norm(title), norm(str(artist or "").split(",")[0])
        return (t, a) if t and a and t != "audio" else None

    @staticmethod
    def _pm_doc_meta(doc):
        with tolerated():
            for a in _pm_list(getattr(doc, "attributes", None)):
                if "Audio" in type(a).__name__ or hasattr(a, "performer"):
                    return str(getattr(a, "title", "") or ""), str(getattr(a, "performer", "") or "")
        return "", ""

    def _profile_notify(self, text, error=False):
        if not error:
            with tolerated():
                editor = getattr(self, "_editor", None)
                dialog = getattr(editor, "dialog", None) if editor is not None else None
                if dialog is not None and bool(dialog.isShowing()):
                    def _t():
                        with tolerated():
                            ctx = find_class("org.telegram.messenger.ApplicationLoader").applicationContext
                            jclass("android.widget.Toast").makeText(ctx, str(text), 1).show()
                    try:
                        run_on_ui_thread(_t)
                    except Exception:
                        _t()
                    return
        self._bulletin(text, error=error)

    def _profile_apply(self, act, items, mode, name):
        items = list(items or [])
        msgs = [m for m in items if m is not None]
        missing = len(items) - len(msgs)
        if not msgs:
            self._bulletin(strings("no_tracks_available_to_set"), error=True)
            return
        if self.__dict__.get("_profile_busy"):
            self._pp_log("%s ignored: another profile update is still running" % mode)
            self._bulletin("Already updating your profile music…", error=True)
            return
        self._profile_busy = True
        title = strings("setting_profile_playlist") if mode == "replace" else strings("adding_to_profile_music")
        st = {"stop": False, "done": False, "sheet": None, "text": strings("starting")}
        def set_text(t):
            st["text"] = t
            def _u():
                sh = st["sheet"]
                if sh is not None and not st["done"]:
                    sh.set_text(t)
            try:
                run_on_ui_thread(_u)
            except Exception:
                _u()
        def cancel():
            st["stop"] = True
        def show_loader():
            if st["done"] or st["sheet"] is not None:
                return
            with tolerated():
                sh = _ProgressSheet(self, act)
                sh.show_progress(title, cancel, force=True)
                sh.set_text(st["text"])
                st["sheet"] = sh
        try:
            run_on_ui_thread(show_loader)
        except Exception:
            show_loader()
        def finish(text, error):
            def _u():
                self._profile_busy = False
                st["done"] = True
                sh = st["sheet"]
                if sh is not None:
                    sh.close()
                self._profile_notify(text, error)
                with tolerated():
                    self._pp_pull(True)
            try:
                run_on_ui_thread(_u)
            except Exception:
                _u()
        def work():
            try:
                res = self._profile_run(msgs, mode, lambda: st["stop"], set_text)
                text, error = self._profile_message(res, mode, missing)
                if res.get("missing") or res.get("failed"):
                    self._pp_log("RESULT: " + text)
                    run_on_ui_thread(lambda: self._pp_show_log("Profile music: " + text[:60], force=True))
                finish(text, error)
            except Exception:
                finish(strings("couldnt_update_profile_music"), True)
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _profile_message(res, mode, missing=0):
        def n(x, w="track"):
            return f"{x} {w}{'' if x == 1 else 's'}"
        if res.get("error"):
            return strings("couldnt_update_profile_music_n", res['error']), True
        saved, already, failed = res["saved"], res["already"], res["failed"]
        if res["cancelled"]:
            head = strings("stopped_after_n", n(saved))
        elif res["limit"]:
            head = strings("profile_music_is_full_saved_n", n(saved))
        elif mode == "replace":
            head = strings("profile_playlist_set_n", n(saved))
        elif saved:
            head = strings("added_n_to_profile_music", n(saved))
        else:
            head = strings("nothing_new_to_add")
        extra = []
        if res["removed"]:
            extra.append(strings("removed_n_2", res['removed']))
        if already:
            extra.append(strings("n_already_there", already))
        if failed:
            extra.append(strings("n_failed", failed))
        if res.get("missing"):
            extra.append("Telegram didn't keep %d" % res["missing"])
        if missing:
            extra.append(strings("n_unavailable", missing))
        if res.get("kept_old"):
            extra.append(strings("kept_your_old_tracks"))
        bad = bool(failed or res.get("missing") or res["limit"] or res["cancelled"] or (not saved and not already))
        return head + (" · " + ", ".join(extra) if extra else ""), bad

    def _profile_run(self, msgs, mode, stopped, progress):
        acc = self._chat_account(None, msgs)
        res = {"saved": 0, "already": 0, "failed": 0, "removed": 0, "limit": False,
       "cancelled": False, "error": None, "kept_old": False}
        targets, ids, pairs = [], set(), set()
        for m in msgs:
            try:
                doc = m.getDocument()
                did = int(doc.id)
            except Exception:
                continue
            pair = self._pm_pair(_QueueEditor._title_of(m), _QueueEditor._author_of(m))
            if did in ids or (pair and pair in pairs):
                continue
            ids.add(did)
            if pair:
                pairs.add(pair)
            self._pm_remember_src(doc, m)
            targets.append({"doc": doc, "id": did, "pair": pair})
        if not targets:
            res["error"] = strings("no_audio_files")
            return res
        progress(strings("reading_your_profile_music"))
        current, err = self._pm_current(acc, stopped)
        if err == "CANCELLED":
            res["cancelled"] = True
            return res
        if err and mode == "replace":
            res["error"] = err[:40]
            return res
        cur_ids = {int(d.id) for d in current}
        cur_pairs = set()
        for d in current:
            pr = self._pm_pair(*self._pm_doc_meta(d))
            if pr:
                cur_pairs.add(pr)
        if mode == "add":
            fresh = [t for t in targets if t["id"] not in cur_ids and not (t["pair"] and t["pair"] in cur_pairs)]
            res["already"] = len(targets) - len(fresh)
            targets = fresh
        progress(strings("starting"))
        self._pm_refresh_bulk(acc, [t["doc"] for t in targets], stopped)
        extras = [d for d in current if int(d.id) not in ids] if mode == "replace" else []
        extras_removed = False
        saved_ids = set()
        total = len(targets)
        prev = None
        for i, t in enumerate(targets, 1):
            if stopped():
                res["cancelled"] = True
                break
            progress(strings("saving_n_of_n", i, total))
            ok, err = self._pm_save(acc, t["doc"], prev, stopped, progress)
            self._pp_log("%s #%d/%d id=%s ok=%s err=%s" % (mode, i, total, t["id"], ok, err))
            if not ok and err and "LIMIT" in err.upper() and extras and not extras_removed:
                progress(strings("making_room"))
                res["removed"] += self._pm_unsave_many(acc, extras, stopped, progress)
                extras_removed = True
                ok, err = self._pm_save(acc, t["doc"], prev, stopped, progress)
            if ok:
                res["saved"] += 1
                saved_ids.add(t["id"])
                prev = t["doc"]
            elif err == "CANCELLED":
                res["cancelled"] = True
                break
            elif err and "LIMIT" in err.upper():
                res["limit"] = True
                break
            else:
                res["failed"] += 1
            time.sleep(0.4)
        if mode == "replace" and extras and not extras_removed:
            if res["cancelled"] or res["limit"] or not res["saved"]:
                res["kept_old"] = True
            else:
                res["removed"] += self._pm_unsave_many(acc, extras, stopped, progress)
        if saved_ids and not res["cancelled"]:
            progress("Checking…")
            now, e2 = self._pm_current(acc, lambda: False)
            if not e2:
                have = {int(d.id) for d in now}
                miss = saved_ids - have
                self._pp_log("VERIFY: said saved=%d, profile now has %d docs, of ours %d, missing=%d" % (
                    len(saved_ids), len(have), len(saved_ids & have), len(miss)))
                res["missing"] = len(miss)
        return res

    def _pm_current(self, acc, stopped):
        try:
            input_user = find_class("org.telegram.tgnet.TLRPC$TL_inputUserSelf")()
        except Exception as e:
            return [], f"self user input unavailable: {e}"
        try:
            return self._pm_get_saved_music(acc, input_user, stopped, lambda _t: None), None
        except Exception as e:
            return [], str(e)

    def _pm_get_saved_music(self, acc, input_user, stopped, progress):
        cls = _tl_resolve("TL_users_getSavedMusic", "TL_getSavedMusic", "TL_account_getSavedMusic", "getSavedMusic")
        if cls is None:
            raise RuntimeError("users.getSavedMusic API not found")
        docs, offset, limit = [], 0, 40
        with tolerated():
            lg = getattr(self, "_pp_log", None)
            if lg:
                lg("getSavedMusic class=%s" % cls.getName() if hasattr(cls, "getName") else "getSavedMusic class=%r" % (cls,))
        while True:
            if stopped():
                raise RuntimeError("CANCELLED")
            req = cls()
            req.id = input_user
            req.offset = int(offset)
            req.limit = int(limit)
            req.hash = 0
            resp, err = self._pm_rpc(acc, req, stopped, progress=progress)
            if err:
                raise RuntimeError(err)
            page = _pm_list(getattr(resp, "documents", None))
            if not page:
                break
            raw_n = len(page)
            seen_ids = {int(d.id) for d in docs}
            page = [d for d in page if int(d.id) not in seen_ids]
            if not page:
                break
            docs.extend(page)
            count = int(getattr(resp, "count", 0) or 0)
            progress(strings("reading_profile_music_n_tracks", len(docs)))
            if (count and len(docs) >= count) or raw_n < limit:
                break
            offset += raw_n
        return docs

    def _pm_input_user(self, user_id, access_hash, acc=0):
        uid, h = int(user_id), int(access_hash or 0)
        if uid == self._me(int(acc)):
            return find_class("org.telegram.tgnet.TLRPC$TL_inputUserSelf")()
        if h == 0:
            with tolerated():
                MC = find_class("org.telegram.messenger.MessagesController").getInstance(int(acc))
                user = MC.getUser(jclass("java.lang.Long").valueOf(uid))
                if user is not None:
                    h = int(getattr(user, "access_hash", 0) or 0)
        if not h:
            raise RuntimeError("user access hash unavailable; open their profile again and save it")
        inp = find_class("org.telegram.tgnet.TLRPC$TL_inputUser")()
        inp.user_id = uid
        inp.access_hash = h
        return inp

    def _pm_synthetic_music_message(self, acc, user_id, doc, index=0):
        TL = find_class("org.telegram.tgnet.TLRPC$TL_message")
        tl = TL()
        try:
            doc_id = int(doc.id)
        except Exception:
            doc_id = index + 1
        mid = int(doc_id % 2147483647)
        if mid <= 0:
            mid = index + 1
        tl.id = mid
        tl.date = int(time.time())
        tl.message = ""
        with tolerated():
            tl.flags = int(getattr(tl, "flags", 0) or 0) | 768
        peer = find_class("org.telegram.tgnet.TLRPC$TL_peerUser")()
        peer.user_id = int(user_id)
        tl.peer_id = peer
        with tolerated():
            from_peer = find_class("org.telegram.tgnet.TLRPC$TL_peerUser")()
            from_peer.user_id = int(user_id)
            tl.from_id = from_peer
        media = find_class("org.telegram.tgnet.TLRPC$TL_messageMediaDocument")()
        media.document = doc
        tl.media = media
        tl.dialog_id = int(user_id)
        MO = find_class("org.telegram.messenger.MessageObject")
        mo = MO(int(acc), tl, False, True)
        with tolerated():
            self.__dict__.setdefault("_pm_synth_keys", set()).add((int(tl.id), int(user_id)))
        return mo

    def _pm_is_synth(self, m):
        with tolerated():
            did, mid = int(m.getDialogId()), int(m.getId())
            if (mid, did) in self.__dict__.get("_pm_synth_keys", ()):
                return True
            doc = m.getDocument()
            if doc is not None and did > 0 and mid > 0 and mid == int(doc.id) % 2147483647:
                self.__dict__.setdefault("_pm_synth_keys", set()).add((mid, did))
                return True
        return False

    @staticmethod
    def _pm_input_doc(doc):
        d = find_class("org.telegram.tgnet.TLRPC$TL_inputDocument")()
        d.id = doc.id
        d.access_hash = doc.access_hash
        fr = None
        with tolerated():
            fr = doc.file_reference
        d.file_reference = fr if fr is not None else jarray(jbyte)([])
        return d

    def _pm_src_map(self):
        m = self.__dict__.get("_pm_doc_src")
        if m is None:
            m = {}
            with tolerated():
                for k, v in json.loads(self.get_setting("pp_src_v1", "") or "{}").items():
                    m[int(k)] = (int(v[0]), int(v[1]))
            self._pm_doc_src = m
        return m

    def _pm_src_get(self, doc_id):
        return self._pm_src_map().get(int(doc_id))

    def _pm_remember_src(self, doc, msg):
        with tolerated():
            did, mid = int(msg.getDialogId()), int(msg.getId())
            if did == 0 or self._pm_is_synth(msg):
                return
            m = self._pm_src_map()
            if m.get(int(doc.id)) == (did, mid):
                return
            m[int(doc.id)] = (did, mid)
            if not self.__dict__.get("_pm_src_timer"):
                self._pm_src_timer = True
                def flush():
                    self._pm_src_timer = False
                    with tolerated():
                        self.set_setting("pp_src_v1", json.dumps({str(k): list(v) for k, v in self._pm_src_map().items()},
                                                                 separators=(",", ":")))
                self._post(flush, 2000)

    def _pm_refresh_bulk(self, acc, docs, stopped):
        fm = self._pm_fresh_map = {}
        groups = {}
        for d in docs:
            src = self._pm_src_get(d.id)
            if src and src[0] != 0:
                groups.setdefault(int(src[0]), {})[int(src[1])] = int(d.id)
        lg = getattr(self, "_pp_log", lambda _m: None)
        n_ok = 0
        for did, mids in groups.items():
            items = list(mids.items())
            for k in range(0, len(items), 100):
                if stopped():
                    return n_ok
                chunk = items[k:k + 100]
                try:
                    MCtl = _jc("org.telegram.messenger.MessagesController").getInstance(int(acc))
                    if did < 0:
                        chat = MCtl.getChat(-did)
                        if chat is None:
                            continue
                        channel = bool(_jc("org.telegram.messenger.ChatObject").isChannel(chat))
                    else:
                        channel = False
                    if channel:
                        req = _jc("org.telegram.tgnet.TLRPC$TL_channels_getMessages")()
                        ic = MCtl.getInputChannel(-did)
                        if ic is None:
                            continue
                        req.channel = ic
                    else:
                        req = _jc("org.telegram.tgnet.TLRPC$TL_messages_getMessages")()
                    for mid, _doc in chunk:
                        req.id.add(jclass("java.lang.Integer")(int(mid)))
                    res, err = self._pm_rpc(acc, req, stopped, timeout=15.0, retries=1)
                    if err is not None or res is None:
                        lg("bulk refresh chat %s failed: %s" % (did, err))
                        continue
                    lst = res.messages
                    for i in range(int(lst.size())):
                        m = lst.get(i)
                        want = mids.get(int(m.id))
                        nd = getattr(getattr(m, "media", None), "document", None)
                        if want is not None and nd is not None and int(nd.id) == want:
                            fm[want] = nd
                            n_ok += 1
                except Exception as e:
                    lg("bulk refresh chat %s error: %s" % (did, str(e)[:80]))
        lg("bulk refresh: %d of %d documents refreshed from %d chats" % (n_ok, len(docs), len(groups)))
        return n_ok

    def _pm_fresh_doc(self, acc, doc):
        with tolerated():
            cur, err = self._pm_current(acc, lambda: False)
            if not err:
                for d in cur:
                    if int(d.id) == int(doc.id):
                        return d
        src = self._pm_src_get(doc.id)
        if not src or src[0] == 0:
            return None
        did, mid = src
        with tolerated():
            MCtl = _jc("org.telegram.messenger.MessagesController").getInstance(int(acc))
            if did < 0:
                chat = MCtl.getChat(-did)
                if chat is None:
                    return None
                channel = bool(_jc("org.telegram.messenger.ChatObject").isChannel(chat))
            else:
                channel = False
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
            res, err = self._pm_rpc(acc, req, lambda: False, timeout=15.0, retries=1)
            if err is not None or res is None:
                return None
            lst = res.messages
            for i in range(int(lst.size())):
                m = lst.get(i)
                if int(m.id) != mid:
                    continue
                nd = getattr(getattr(m, "media", None), "document", None)
                if nd is not None and int(nd.id) == int(doc.id):
                    return nd
        return None

    def _pm_doc_desc(self, doc):
        if doc is None:
            return "None"
        out = []
        with tolerated():
            out.append("id=%s" % int(doc.id))
            out.append("hash=%s" % ("set" if int(getattr(doc, "access_hash", 0) or 0) else "ZERO"))
            out.append("ref=%d" % len(getattr(doc, "file_reference", None) or ()))
            out.append("mime=%s" % getattr(doc, "mime_type", "?"))
            out.append("size=%s" % int(getattr(doc, "size", 0) or 0))
            out.append("dc=%s" % getattr(doc, "dc_id", "?"))
            out.append("attrs=" + ",".join(type(a).__name__.replace("TL_documentAttribute", "") for a in _pm_list(getattr(doc, "attributes", None))))
            for a in _pm_list(getattr(doc, "attributes", None)):
                if hasattr(a, "voice"):
                    out.append("voice=%s" % bool(a.voice))
            out.append("src=%s" % (self._pm_src_get(doc.id),))
        return " ".join(out)

    def _pm_save(self, acc, doc, after_doc, stopped, progress):
        lg = getattr(self, "_pp_log", None) or (lambda _m: None)
        fm = self.__dict__.get("_pm_fresh_map") or {}
        doc = fm.get(int(doc.id), doc)
        if after_doc is not None:
            after_doc = fm.get(int(after_doc.id), after_doc)
        ok, err = self._pm_save_once(acc, doc, after_doc, stopped, progress)
        up = str(err or "").upper()
        if not ok and ("FILE_REFERENCE" in up or "DOCUMENT_INVALID" in up):
            lg("save refused (%s): doc[%s] after[%s]" % (err, self._pm_doc_desc(doc), self._pm_doc_desc(after_doc)))
            fresh = self._pm_fresh_doc(acc, doc)
            fresh_after = self._pm_fresh_doc(acc, after_doc) if after_doc is not None else None
            lg("refreshed: doc=%s after=%s" % ("new copy" if fresh is not None else "no copy found",
                                              "new copy" if fresh_after is not None else ("-" if after_doc is None else "no copy found")))
            if fresh is None:
                lg("final: %s | no fresh copy of the song, not retrying | doc[%s]" % (err, self._pm_doc_desc(doc)))
                return False, err
            fresh, fresh_after = fresh, fresh_after or after_doc
            ok, err = self._pm_save_once(acc, fresh, fresh_after, stopped, progress)
            if not ok and "DOCUMENT_INVALID" in str(err or "").upper() and fresh_after is not None:
                lg("still %s: trying without the 'after' song" % err)
                ok, err = self._pm_save_once(acc, fresh, None, stopped, progress)
                lg("  -> without after: ok=%s err=%s" % (ok, err))
            if not ok:
                lg("final: %s | doc[%s]" % (err, self._pm_doc_desc(fresh)))
        return ok, err

    def _pm_save_once(self, acc, doc, after_doc, stopped, progress):
        cls = _tl_resolve("TL_account_saveMusic")
        if cls is None:
            return False, "saveMusic not found"
        req = cls()
        req.unsave = False
        req.id = self._pm_input_doc(doc)
        flags = 0
        if after_doc is not None:
            with tolerated():
                req.after_id = self._pm_input_doc(after_doc)
                flags |= 2
        req.flags = flags
        resp, err = self._pm_rpc(acc, req, stopped, timeout=45.0, retries=0, progress=progress)
        if err is None and self._pm_bool_result(resp) is True:
            return True, None
        if err is None and after_doc is not None and not stopped():
            retry = cls()
            retry.unsave = False
            retry.id = self._pm_input_doc(doc)
            retry.flags = 0
            retry_resp, retry_err = self._pm_rpc(acc, retry, stopped, timeout=45.0, retries=0, progress=progress)
            if retry_err is None and self._pm_bool_result(retry_resp) is True:
                return True, None
            if retry_err:
                return False, retry_err
            return False, "SERVER_FALSE"
        if err is None:
            return False, "SERVER_FALSE"
        return False, err

    @staticmethod
    def _pm_bool_result(resp):
        if resp is None:
            return None
        try:
            name = str(resp.getClass().getSimpleName()).lower()
        except Exception:
            name = type(resp).__name__.lower()
        if "boolfalse" in name:
            return False
        if "booltrue" in name:
            return True
        with tolerated():
            value = getattr(resp, "value", None)
            if value is not None:
                return bool(value)
        return None

    def _pm_unsave_many(self, acc, docs, stopped, progress):
        cls = _tl_resolve("TL_account_saveMusic")
        if cls is None:
            return 0
        removed = 0
        for i, d in enumerate(docs, 1):
            if stopped():
                break
            progress(strings("removing_old_tracks_n_of_n", i, len(docs)))
            req = cls()
            req.unsave = True
            req.flags = 1
            req.id = self._pm_input_doc(d)
            resp, err = self._pm_rpc(acc, req, stopped, timeout=30.0, retries=2, progress=progress)
            lg = getattr(self, "_pp_log", None)
            if lg:
                lg("REMOVE from profile (unsave=true) %d/%d id=%s -> err=%s" % (i, len(docs), int(d.id), err))
            if err is None and self._pm_bool_result(resp) is True:
                removed += 1
            time.sleep(0.2)
        return removed

    @staticmethod
    def _ver_tuple(v):
        return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4])

    def _update_schedule(self, force=False):
        if not force and not self.get_setting("update_check", True):
            return
        if not force and time.time() - float(self.get_setting("update_last", 0) or 0) < 21600:
            return
        threading.Thread(target=self._update_run, args=(force,), daemon=True).start()

    @staticmethod
    def _update_link(msg, text, span):
        s16 = lambda i: len(text[:i].encode("utf-16-le")) // 2
        a, b = s16(span[0]), s16(span[1])
        ents = getattr(msg, "entities", None)
        if ents is None:
            return None
        u16 = text.encode("utf-16-le")
        best = None
        for i in range(int(ents.size())):
            e = ents.get(i)
            off, ln = int(getattr(e, "offset", 0)), int(getattr(e, "length", 0))
            if off >= b or off + ln <= a:
                continue
            url = str(getattr(e, "url", "") or "")
            if not url and "Url" in str(e.getClass().getSimpleName()):
                url = u16[off * 2:(off + ln) * 2].decode("utf-16-le", "ignore")
            if url.strip():
                best = url.strip()
                break
        if best and "://" not in best:
            best = "https://" + best
        return best

    def _update_dialog(self, message, url=None):
        def show():
            def open_update():
                self._open_link(url or f"https://t.me/{_UPDATE_CHANNEL}/{_UPDATE_MSG_ID}")
            def build_telegram(act):
                builder = _jc("org.telegram.ui.ActionBar.AlertDialog$Builder")(act)
                click = _proxy("org.telegram.ui.ActionBar.AlertDialog$OnButtonClickListener", "onClick")
                builder.setTitle("Music +")
                builder.setMessage(str(message))
                builder.setPositiveButton(strings("view_update"), click(lambda dialog, which: open_update()))
                builder.setNegativeButton(strings("close"), click(lambda dialog, which: None))
                return builder.create()
            def build_android(act):
                builder = jclass("android.app.AlertDialog$Builder")(act)
                click = _proxy("android.content.DialogInterface$OnClickListener", "onClick")
                builder.setTitle("Music +")
                builder.setMessage(str(message))
                builder.setPositiveButton(strings("view_update"), click(lambda dialog, which: open_update()))
                builder.setNegativeButton(strings("close"), click(lambda dialog, which: None))
                return builder.create()
            with tolerated():
                fragment = get_last_fragment()
                act = fragment.getParentActivity() if fragment is not None else None
                if act is None:
                    return
                for build in (build_telegram, build_android):
                    try:
                        build(act).show()
                        return
                    except Exception:
                        continue
        try:
            run_on_ui_thread(show)
        except Exception:
            show()

    def _update_run(self, force=False):
        if getattr(self, "_update_busy", False):
            return
        self._update_busy = True
        try:
            if not force:
                ed = getattr(self, "_editor", None)
                if ed is None or not ed.dialog.isShowing():
                    return
            acc = int(find_class("org.telegram.messenger.UserConfig").selectedAccount)
            stop = lambda: False
            req = _jc("org.telegram.tgnet.TLRPC$TL_contacts_resolveUsername")()
            req.username = _UPDATE_CHANNEL
            res, err = self._pm_rpc(acc, req, stop, timeout=15.0, retries=1)
            if err is not None or res is None:
                return
            MCtl = _jc("org.telegram.messenger.MessagesController").getInstance(acc)
            MCtl.putChats(res.chats, False)
            MCtl.putUsers(res.users, False)
            channel_id = int(res.peer.channel_id)
            req = _jc("org.telegram.tgnet.TLRPC$TL_messages_getHistory")()
            req.peer = MCtl.getInputPeer(-channel_id)
            req.offset_id = _UPDATE_MSG_ID + 1
            req.add_offset = -1
            req.limit = 3
            req.max_id = 0
            req.min_id = 0
            req.offset_date = 0
            req.hash = 0
            res, err = self._pm_rpc(acc, req, stop, timeout=15.0, retries=1)
            if err is not None or res is None or int(res.messages.size()) == 0:
                return
            self.set_setting("update_last", time.time())
            text = ""
            for i in range(int(res.messages.size())):
                msg = res.messages.get(i)
                if int(getattr(msg, "id", 0)) == _UPDATE_MSG_ID:
                    text = str(getattr(msg, "message", "") or "")
                    break
            if not text:
                return
            m = re.search(r"^\s*" + re.escape(_UPDATE_NAME) + r"\s*[:：]\s*v?(\d+(?:\.\d+)*)", text, re.M | re.I)
            if not m:
                return
            link = None
            with tolerated():
                link = self._update_link(msg, text, m.span(1))
            latest = self._ver_tuple(m.group(1))
            label = ".".join(str(x) for x in latest)
            current = ".".join(str(x) for x in self._ver_tuple(_PLUGIN_VERSION))
            if latest <= self._ver_tuple(_PLUGIN_VERSION):
                if force:
                    self._update_dialog(strings("youre_up_to_date_current_version", current))
                return
            if not force and str(self.get_setting("update_seen", "")) == label:
                return
            self.set_setting("update_seen", label)
            self._update_dialog(strings("newer_version_is_available_v_n", label, current), link)
        except Exception:
            pass
        finally:
            self._update_busy = False

    def _queue_prep(self, items, state):
        keys, desc = state.get("keys"), state.get("desc")
        if keys is None or desc is None:
            return None
        fresh, newkeys = [], []
        n = 0
        for m in items:
            if m is None:
                continue
            n += 1
            if n % 40 == 0:
                time.sleep(0.002)
            k = self._msg_key(m)
            if k is not None and k not in keys:
                keys.add(k)
                newkeys.append(k)
                fresh.append(m)
        fids = [int(m.getId()) for m in fresh]
        order = sorted(range(len(fresh)), key=lambda i: fids[i], reverse=bool(desc))
        fresh, fids = [fresh[i] for i in order], [fids[i] for i in order]
        fa = ArrayList()
        hm = None
        with tolerated():
            hm = _jc("java.util.HashMap")()
        for m, i in zip(fresh, fids):
            fa.add(m)
            if hm is not None:
                with tolerated():
                    hm.put(i, m)
        return {"fresh": fresh, "fids": fids, "fa": fa, "hm": hm, "keys": newkeys}

    def _queue_insert_sorted(self, items, state, final=False, prep=None):
        mc = self._get_mc()
        pl = self._get_playlist(mc) if mc is not None else None
        if pl is None:
            return False
        shuffle_on, rev = self._read_order()
        n = int(pl.size())
        raw = ids = None
        cache = state.get("raw")
        if cache is not None and n and len(cache[0]) == n:
            with tolerated():
                if int(pl.get(0).getId()) == cache[1][0] and int(pl.get(n - 1).getId()) == cache[1][-1]:
                    raw, ids = cache
        if raw is None:
            raw = [pl.get(i) for i in range(n)]
            ids = [int(m.getId()) for m in raw]
            state["keys"] = None
        if state.get("keys") is None:
            state["desc"] = self._playback_descending(raw if rev else raw[::-1], rev) == rev
            state["keys"] = {self._msg_key(m) for m in raw if m is not None}
        keys, desc = state["keys"], state["desc"]
        fresh, hm, fa = [], None, None
        if prep is not None:
            fresh, fids, fa, hm = prep["fresh"], prep["fids"], prep["fa"], prep["hm"]
            keys.update(prep["keys"])
        else:
            for m in items:
                if m is None:
                    continue
                k = self._msg_key(m)
                if k is not None and k not in keys:
                    keys.add(k)
                    fresh.append(m)
        if fresh:
            if prep is None:
                fresh.sort(key=lambda m: int(m.getId()), reverse=bool(desc))
                fids = [int(m.getId()) for m in fresh]
            if not raw:
                tail, head = True, False
            elif desc:
                tail, head = min(ids) >= max(fids), max(ids) < min(fids)
            else:
                tail, head = max(ids) <= min(fids), min(ids) > max(fids)
            if fa is None:
                fa = ArrayList()
                for m in fresh:
                    fa.add(m)
            if tail or head:
                if tail:
                    pl.addAll(fa)
                    raw, ids = raw + fresh, ids + fids
                else:
                    pl.addAll(0, fa)
                    raw, ids = fresh + raw, fids + ids
            else:
                merged, mids = [], []
                i = j = 0
                while i < len(raw) and j < len(fresh):
                    take_old = ids[i] >= fids[j] if desc else ids[i] <= fids[j]
                    if take_old:
                        merged.append(raw[i])
                        mids.append(ids[i])
                        i += 1
                    else:
                        merged.append(fresh[j])
                        mids.append(fids[j])
                        j += 1
                merged.extend(raw[i:])
                mids.extend(ids[i:])
                merged.extend(fresh[j:])
                mids.extend(fids[j:])
                arr = ArrayList()
                for m in merged:
                    arr.add(m)
                pl.clear()
                try:
                    pl.addAll(arr)
                except Exception:
                    pl.clear()
                    for m in merged:
                        pl.add(m)
                raw, ids = merged, mids
            state["raw"] = (raw, ids)
            pmap = None
            with tolerated():
                pmap = get_private_field(mc, "playlistMap")
            done_map = False
            if pmap is not None and hm is not None:
                with tolerated():
                    pmap.putAll(hm)
                    done_map = True
            if not done_map:
                for m in fresh:
                    if pmap is not None:
                        with tolerated():
                            pmap.put(m.getId(), m)
                    else:
                        self._map_put(mc, m)
            if final or not shuffle_on:
                self._finish_bulk_edit(mc, pl)
        else:
            state["raw"] = (raw, ids)
            if final:
                self._finish_bulk_edit(mc, pl)
        return True

    _PM_TRANSIENT = ("TIMEOUT", "-503", "-500", "INTERNAL", "RPC_CALL_FAIL", "RPC_MCGET_FAIL", "NETWORK", "CONNECTION")

    def _pm_rpc(self, acc, req, stopped, timeout=10.0, retries=2, progress=None, on_result=None):
        CM = find_class("org.telegram.tgnet.ConnectionsManager")
        for attempt in range(retries + 1):
            if stopped():
                return None, "CANCELLED"
            box, ev = {"r": None, "e": None}, threading.Event()
            def cb(res, err, _b=box, _ev=ev):
                if err is not None:
                    _b["e"] = str(getattr(err, "text", None) or err)
                else:
                    _b["r"] = res
                    if on_result is not None:
                        try:
                            _b["x"] = on_result(res)
                        except Exception as exc:
                            report_exception(exc)
                _ev.set()
            t_rpc = time.monotonic()
            rname = "?"
            with tolerated():
                rname = str(req.getClass().getSimpleName())
            lg = getattr(self, "_pp_log", None)
            if lg:
                lg("rpc %s try %d/%d (limit %ss)%s" % (rname, attempt + 1, retries + 1, timeout,
                   " off=%s" % getattr(req, "offset", "") if hasattr(req, "offset") else ""))
            try:
                sd = find_class("org.telegram.tgnet.SerializedData")()
                req.serializeToStream(sd)
            except Exception as e:
                if lg:
                    lg("  rpc %s SERIALIZE FAILED: %s" % (rname, str(e)[:200]))
                return None, "SERIALIZE: " + str(e)[:80]
            token = None
            try:
                token = CM.getInstance(int(acc)).sendRequest(req, _request_delegate(cb))
            except Exception as e:
                return None, f"EXC: {str(e)[:80]}"
            if not ev.wait(timeout):
                if lg:
                    lg("  rpc %s TIMEOUT after %.1fs, no answer (Telegram silently waits out flood limits when saving too fast)" % (rname, time.monotonic() - t_rpc))
                with tolerated():
                    if token is not None:
                        CM.getInstance(int(acc)).cancelRequest(int(token), True)
                if attempt < min(retries, 1) and not stopped():
                    time.sleep(0.5)
                    continue
                return None, "TIMEOUT"
            err = box["e"]
            if lg:
                lg("  rpc %s answered in %dms: %s" % (rname, (time.monotonic() - t_rpc) * 1000, err or "ok"))
            if err is not None and attempt < retries and any(x in err.upper() for x in self._PM_TRANSIENT):
                time.sleep(1.0 + attempt)
                continue
            if err is None:
                if on_result is not None:
                    return box.get("x"), None
                return box["r"], None
            m = re.search(r"FLOOD_WAIT_(\d+)", err)
            if m and attempt < retries:
                secs = min(int(m.group(1)) + 1, 120)
                end = time.time() + secs
                while time.time() < end:
                    if stopped():
                        return None, "CANCELLED"
                    if progress is not None:
                        progress(strings("telegram_asks_to_wait_n_s", int(end - time.time()) + 1))
                    time.sleep(0.5)
                continue
            return None, err
        return None, "RETRIES"

    def _view_artist_in_library(self, artist, message=None, _attempt=0):
        name = str(artist or "").strip()
        if not name:
            self._bulletin(strings("artist_name_unavailable"), error=True)
            return
        def open_artist():
            editor = getattr(self, "_editor", None)
            if editor is None:
                if _attempt == 0:
                    self._open_queue_editor()
                if _attempt < 16:
                    self._post(lambda: self._view_artist_in_library(name, message, _attempt + 1), 250)
                else:
                    self._bulletin(strings("open_music_to_view_this_artist"), error=True)
                return
            try:
                key = editor._lib_ensure_artist(name, message)
                if not key:
                    self._bulletin(strings("artist_name_unavailable"), error=True)
                    return
                if getattr(editor, "lib_search_active", False):
                    editor._set_library_search(False, clear=True, rerender=False)
                editor._set_tab("library")
                editor._lib_go("artist", key)
            except Exception:
                self._bulletin(strings("couldnt_open_artist_in_library"), error=True)
        try:
            run_on_ui_thread(open_artist)
        except Exception:
            open_artist()

    def _open_artist_music_search(self, artist):
        try:
            query = str(artist or "").strip()
            if not query:
                self._bulletin(strings("artist_name_unavailable"), error=True)
                return
            frag = get_last_fragment()
            if frag is None:
                self._bulletin(strings("cant_open_telegram_search_here"), error=True)
                return
            music_type = 3
            inj = getattr(self, "_tabinj", None)
            if inj is not None and getattr(self, "_tab_active", False) and inj.owns():
                inj.open_chats_search(query, music_type)
                return
            DA = find_class("org.telegram.ui.DialogsActivity")
            if reflect.jcls("org.telegram.ui.DialogsActivity").isInstance(frag) and not bool(frag.onlyDialogsAdapter()):
                frag.setShowSearch(query, music_type)
                return
            search = DA(None)
            search.setSearchString(query)
            search.setInitialSearchType(music_type)
            frag.presentFragment(search, False, False)
        except Exception:
            self._bulletin(strings("couldnt_open_artist_search"), error=True)

    def _open_plugin_settings(self):
        def begin():
            editor = getattr(self, "_editor", None)
            if editor is not None:
                with tolerated():
                    if editor.dialog is not None and bool(editor.dialog.isShowing()):
                        editor.dialog.dismiss()
                        self._post(self._present_plugin_settings, 220)
                        return
            self._present_plugin_settings()
        try:
            run_on_ui_thread(begin)
        except Exception:
            begin()

    def _present_plugin_settings(self):
        try:
            from com.exteragram.messenger.plugins import PluginsController
            from com.exteragram.messenger.plugins.ui import PluginSettingsActivity
            fragment = get_last_fragment()
            if fragment is None:
                raise RuntimeError("No active Telegram fragment")
            controller = PluginsController.getInstance()
            registry = controller.plugins
            installed = None
            with tolerated():
                installed = registry.get(_PLUGIN_ID)
            if installed is None:
                with tolerated():
                    installed = registry.get(getattr(self, "id", _PLUGIN_ID))
            if installed is None:
                try:
                    values = registry.values().toArray()
                except Exception:
                    values = []
                for candidate in values:
                    try:
                        candidate_id = str(getattr(candidate, "id", ""))
                        candidate_name = str(getattr(candidate, "name", ""))
                        if candidate_id == _PLUGIN_ID or candidate_name == _PLUGIN_NAME:
                            installed = candidate
                            break
                    except Exception:
                        continue
            if installed is None:
                raise RuntimeError("Music + is not registered with the plugin controller")
            fragment.presentFragment(PluginSettingsActivity(installed))
        except Exception:
            self._bulletin(strings("couldnt_open_music_settings"), error=True)

    def _open_tg_player(self):
        frag = get_last_fragment()
        act = frag.getParentActivity() if frag is not None else None
        AP = find_class("org.telegram.ui.Components.AudioPlayerAlert")
        alert = None
        self._native_once = True
        self._post(lambda: setattr(self, "_native_once", False), 2500)
        for args in ((act, None), (act,)):
            with tolerated():
                alert = AP(*args)
                break
        if alert is None:
            self._bulletin(strings("couldnt_open_telegrams_player"), error=True)
            return
        try:
            if frag is not None:
                frag.showDialog(alert)
            else:
                alert.show()
        except Exception:
            self._bulletin(strings("couldnt_open_telegrams_player"), error=True)

    def _is_downloaded(self, m) -> bool:
        want = 0
        with tolerated():
            doc = m.getDocument()
            want = int(doc.size) if doc is not None else 0
        def _complete(f) -> bool:
            try:
                if f is None or not bool(f.exists()):
                    return False
                n = int(f.length())
                return n > 0 and (want <= 0 or n >= want)
            except Exception:
                return False
        with tolerated():
            FileLoader = find_class("org.telegram.messenger.FileLoader")
            f = FileLoader.getInstance(int(m.currentAccount)).getPathToMessage(m.messageOwner)
            if _complete(f):
                return True
        with tolerated():
            path = m.messageOwner.attachPath
            if path and str(path).strip():
                return _complete(jclass("java.io.File")(str(path)))
        return False

    def _reverse_queue(self):
        mc = self._get_mc()
        if mc is None:
            return None
        shuffle_on, rev = self._prepare_editable_order()
        pl = self._get_playlist(mc)
        if pl is None or pl.size() < 2:
            return None
        logical_rev = bool(rev and not shuffle_on)
        raw = [pl.get(i) for i in range(pl.size())]
        snapshot = list(raw)
        logical = raw if logical_rev else raw[::-1]
        updated = logical[::-1]
        stored = updated if logical_rev else updated[::-1]
        for i, msg in enumerate(stored):
            pl.set(i, msg)
        if shuffle_on:
            pass
        else:
            self._resync_current(mc, pl)
        return snapshot

    def _offline_target(self, target):
        try:
            if not target.isMusic() or getattr(self, "_allow_remote", False):
                return None
            if self._is_downloaded(target):
                return None
            mc = self._get_mc()
            pl = self._get_playlist(mc) if mc is not None else None
            playing = self._playing_key(mc) if mc is not None else None
            if pl is None or playing is None:
                return None
            shuffle_on, rev = self._read_order()
            if shuffle_on:
                sp = get_private_field(mc, "shuffledPlaylist")
                L = [sp.get(i) for i in range(sp.size())] if sp is not None else []
            else:
                raw = [pl.get(i) for i in range(pl.size())]
                L = raw if rev else raw[::-1]
            keys = [self._msg_key(m) if m is not None else None for m in L]
            if playing not in keys or self._msg_key(target) not in keys:
                return None
            pidx, tidx = keys.index(playing), keys.index(self._msg_key(target))
            if abs(tidx - pidx) != 1:
                return None
            step = tidx - pidx
            j = tidx
            while 0 <= j < len(L):
                if L[j] is not None and self._is_downloaded(L[j]):
                    return L[j]
                j += step
            return False
        except Exception:
            return None

    def _install_playfail_hook(self):
        MediaController = find_class("org.telegram.messenger.MediaController")
        if MediaController is None:
            return
        plugin = self
        class PlayFailHook(MethodHook):
            def after_hooked_method(self, param):
                with tolerated():
                    if not param.args or param.args[0] is None:
                        return
                    target = param.args[0]
                    if not target.isMusic() or plugin._is_downloaded(target):
                        return
                    failed = False
                    with tolerated():
                        failed = param.getResult() is False
                    plugin._schedule_deleted_check(target, 0.5 if failed else 6.0)
        unhooks = self.hook_all_methods(MediaController, "playMessage", PlayFailHook())
        if unhooks:
            self._hooks.extend(unhooks if isinstance(unhooks, list) else [unhooks])
