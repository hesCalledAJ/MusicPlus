import random
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from ..android import _proxy
from ..compat import (
    ArrayList,
    find_class,
    get_last_fragment,
    jclass,
    run_on_ui_thread,
)
from ..constants import ARCHIVE_BATCH, ARCHIVE_USERNAME
from ..native_sheets import _ProgressSheet
from ..safe import report_exception, tolerated
from ..sheets import _jc
from elyx import strings

_FATAL = (
    "CHAT_WRITE_FORBIDDEN",
    "CHAT_ADMIN_REQUIRED",
    "USER_BANNED_IN_CHANNEL",
    "USER_NOT_PARTICIPANT",
    "CHANNEL_PRIVATE",
    "CANCELLED",
)

_MC = "org.telegram.messenger.MessagesController"


def _key(track: Dict[str, Any]) -> Tuple[int, int]:
    return int(track["i"]), int(track["d"])


class _PluginArchiveShare:
    def _archive_account(self) -> int:
        return int(find_class("org.telegram.messenger.UserConfig").selectedAccount)

    def _archive_confirm(self, on_yes) -> None:
        message = strings("archive_forward_consent", ARCHIVE_USERNAME)

        def build_telegram(act):
            builder = _jc("org.telegram.ui.ActionBar.AlertDialog$Builder")(act)
            click = _proxy("org.telegram.ui.ActionBar.AlertDialog$OnButtonClickListener", "onClick")
            builder.setTitle("Music +")
            builder.setMessage(message)
            builder.setPositiveButton(strings("proceed"), click(lambda dialog, which: on_yes()))
            builder.setNegativeButton(strings("cancel"), click(lambda dialog, which: None))
            return builder.create()

        def build_android(act):
            builder = jclass("android.app.AlertDialog$Builder")(act)
            click = _proxy("android.content.DialogInterface$OnClickListener", "onClick")
            builder.setTitle("Music +")
            builder.setMessage(message)
            builder.setPositiveButton(strings("proceed"), click(lambda dialog, which: on_yes()))
            builder.setNegativeButton(strings("cancel"), click(lambda dialog, which: None))
            return builder.create()

        def show():
            fragment = get_last_fragment()
            act = fragment.getParentActivity() if fragment is not None else None
            if act is None:
                return
            for build in (build_telegram, build_android):
                with tolerated():
                    build(act).show()
                    return

        run_on_ui_thread(show)

    def _archive_share(self, name: str, tracks: List[Dict[str, Any]]) -> None:
        self._archive_confirm(lambda: self._archive_start(name, tracks))

    def _archive_start(self, name: str, tracks: List[Dict[str, Any]]) -> None:
        fragment = get_last_fragment()
        act = fragment.getParentActivity() if fragment is not None else None
        state = {"cancelled": False}
        pkey = ("archive", id(state))
        sheet = _ProgressSheet(self, act) if act is not None else None

        def push(text: str, done: int, total: int) -> None:
            def apply():
                if sheet is not None:
                    sheet.set_text(text)
                self._prog_set(pkey, done, total)
            run_on_ui_thread(apply)

        def finish(doc: Optional[dict], message: Optional[str] = None, error: bool = False) -> None:
            def apply():
                if sheet is not None:
                    sheet.close()
                self._prog_end(pkey)
                if message:
                    self._bulletin(message, error=error)
                if doc is not None:
                    self._xfer_send(doc, "Playlist", ".mppl")
            run_on_ui_thread(apply)

        def cancel() -> None:
            state["cancelled"] = True
            self._prog_end(pkey)

        if sheet is not None:
            sheet.show_progress(strings("forwarding_to_archive", ARCHIVE_USERNAME), cancel, force=True)
        self._prog_set(pkey, 0, 0)
        threading.Thread(
            target=self._archive_run,
            args=(name, tracks, state, push, finish),
            daemon=True,
            name="smq-archive",
        ).start()

    def _archive_lookup(self, acc: int, stopped) -> Tuple[Any, int, Optional[str]]:
        req = _jc("org.telegram.tgnet.TLRPC$TL_contacts_resolveUsername")()
        req.username = ARCHIVE_USERNAME
        res, err = self._pm_rpc(acc, req, stopped, timeout=15.0, retries=1)
        if err is not None or res is None:
            return None, 0, err or "EMPTY"
        controller = _jc(_MC).getInstance(acc)
        controller.putChats(res.chats, False)
        controller.putUsers(res.users, False)
        peer_id = int(getattr(res.peer, "channel_id", 0) or getattr(res.peer, "chat_id", 0) or 0)
        chat = controller.getChat(peer_id) if peer_id else None
        if chat is None:
            return None, 0, "NOT_FOUND"
        self.set_setting("archive_dialog", -peer_id)
        return chat, -peer_id, None

    def _archive_load(self, acc: int) -> bool:
        chat, _dialog, _err = self._archive_lookup(acc, lambda: False)
        return chat is not None

    def _archive_unloaded(self, dialog: int, acc: int) -> bool:
        if dialog != int(self.get_setting("archive_dialog", 0) or 0):
            return False
        return _jc(_MC).getInstance(acc).getChat(-dialog) is None

    def _archive_prime(self) -> None:
        def work():
            if self._archive_load(self._archive_account()):
                run_on_ui_thread(self._request_library_refresh)
        threading.Thread(target=work, daemon=True, name="smq-archive-prime").start()

    @staticmethod
    def _archive_new_ids(res: Any, rids: List[int]) -> List[Optional[int]]:
        updates = getattr(res, "updates", None)
        by_rid: Dict[int, int] = {}
        order: List[int] = []
        if updates is not None:
            for update in list(updates.toArray()):
                kind = str(update.getClass().getSimpleName())
                if kind == "TL_updateMessageID":
                    by_rid[int(update.random_id)] = int(update.id)
                elif kind in ("TL_updateNewChannelMessage", "TL_updateNewMessage"):
                    order.append(int(update.message.id))
        ids: List[Optional[int]] = [by_rid.get(r) for r in rids]
        missing = [k for k, v in enumerate(ids) if v is None]
        if missing:
            claimed = set(by_rid.values())
            rest = [x for x in order if x not in claimed]
            if len(rest) == len(missing):
                for k, x in zip(missing, rest):
                    ids[k] = x
        _PluginArchiveShare._dbg = f"r{len(rids)} u{len(by_rid)} m{len(order)}"
        return ids

    def _archive_forward_chunk(self, acc, dialog, source, chunk, stopped, progress):
        controller = _jc(_MC).getInstance(acc)
        Integer, Long = jclass("java.lang.Integer"), jclass("java.lang.Long")
        req = _jc("org.telegram.tgnet.TLRPC$TL_messages_forwardMessages")()
        req.from_peer = controller.getInputPeer(source)
        req.to_peer = controller.getInputPeer(dialog)
        req.silent = True
        req.drop_author = True
        req.drop_media_captions = True
        req.id = ArrayList()
        req.random_id = ArrayList()
        rids = []
        for track in chunk:
            rid = random.getrandbits(62) or 1
            rids.append(rid)
            req.id.add(Integer(int(track["i"])))
            req.random_id.add(Long(rid))
        def on_result(res):
            ids = self._archive_new_ids(res, rids)
            with tolerated():
                controller.processUpdates(res, False)
            return ids

        ids, err = self._pm_rpc(acc, req, stopped, timeout=40.0, retries=3, progress=progress, on_result=on_result)
        if err is not None:
            return None, err
        if ids is None:
            return [None] * len(rids), None
        return ids, None

    def _archive_forward(self, acc, dialog, jobs, stopped, push):
        groups: Dict[int, List[Dict[str, Any]]] = {}
        seen = set()
        for track in jobs:
            k = _key(track)
            if k in seen:
                continue
            seen.add(k)
            groups.setdefault(k[1], []).append(track)
        total = len(seen)
        mapping: Dict[Tuple[int, int], int] = {}
        count = {"n": 0}

        def progress(text):
            push(text, count["n"], total)

        errs: Dict[str, int] = {}
        self._share_errs = errs

        def run(source, chunk):
            if stopped():
                return "CANCELLED"
            ids, err = self._archive_forward_chunk(acc, dialog, source, chunk, stopped, progress)
            if err is not None:
                if any(code in err for code in _FATAL):
                    return err
                if len(chunk) > 1 and "RESTRICTED" not in err:
                    mid = len(chunk) // 2
                    return run(source, chunk[:mid]) or run(source, chunk[mid:])
                errs[err[:40]] = errs.get(err[:40], 0) + len(chunk)
                count["n"] += len(chunk)
                push(strings("forwarded_n_of_n_tracks", count["n"], total), count["n"], total)
                return None
            for track, new_id in zip(chunk, ids):
                if new_id is not None:
                    mapping[_key(track)] = int(new_id)
                else:
                    key = "NO_ID " + str(getattr(_PluginArchiveShare, "_dbg", ""))
                    errs[key] = errs.get(key, 0) + 1
            count["n"] += len(chunk)
            push(strings("forwarded_n_of_n_tracks", count["n"], total), count["n"], total)
            return None

        for source, items in groups.items():
            for start in range(0, len(items), ARCHIVE_BATCH):
                fatal = run(source, items[start:start + ARCHIVE_BATCH])
                if fatal:
                    return mapping, fatal
        return mapping, None

    def _archive_compose(self, name, tracks, mapping, dialog):
        out: List[Dict[str, Any]] = []
        skipped = 0
        for track in tracks:
            if track.get("pf") or int(track["d"]) == dialog:
                out.append(track)
            elif _key(track) in mapping:
                moved = dict(track)
                moved["i"] = mapping[_key(track)]
                moved["d"] = dialog
                out.append(moved)
            else:
                skipped += 1
        doc = {
            "musicplus": 1,
            "kind": "playlist",
            "name": name,
            "by": self._xfer_creator(),
            "archive": dialog,
            "tracks": out,
        }
        return doc, skipped

    def _archive_run(self, name, tracks, state, push, finish) -> None:
        try:
            self._archive_job(name, tracks, state, push, finish)
        except Exception as exc:
            report_exception(exc)
            finish(None, strings("archive_forward_failed", f"{type(exc).__name__}: {str(exc)[:120]}"), True)

    def _archive_job(self, name, tracks, state, push, finish) -> None:
        acc = self._archive_account()
        stopped = lambda: bool(state["cancelled"])
        push(strings("archive_resolving", ARCHIVE_USERNAME), 0, 0)
        chat, dialog, err = self._archive_lookup(acc, stopped)
        if stopped():
            finish(None)
            return
        if chat is None:
            finish(None, strings("archive_resolve_failed", ARCHIVE_USERNAME, err), True)
            return
        if bool(getattr(chat, "left", False)):
            self._open_link(f"https://t.me/{ARCHIVE_USERNAME}")
            finish(None, strings("archive_join_first", ARCHIVE_USERNAME), True)
            return
        jobs = [t for t in tracks if not t.get("pf") and int(t["d"]) != dialog]
        push(strings("forwarded_n_of_n_tracks", 0, len(jobs)), 0, len(jobs))
        mapping, err = self._archive_forward(acc, dialog, jobs, stopped, push)
        if stopped():
            finish(None)
            return
        if err is not None:
            finish(None, strings("archive_forward_failed", err), True)
            return
        doc, skipped = self._archive_compose(name, tracks, mapping, dialog)
        if not doc["tracks"]:
            finish(None, strings("archive_forward_failed", "0"), True)
            return
        stats = dict(getattr(self, "_share_stats", None) or {})
        stats.update(out=len(doc["tracks"]), skipped=skipped, errs=dict(getattr(self, "_share_errs", None) or {}), uniq=len({_key(t) for t in tracks}))
        self._share_stats = stats
        finish(doc)

    def _archive_find_sent(self, acc, dialog, name, t0):
        controller = _jc(_MC).getInstance(acc)
        for _ in range(45):
            time.sleep(2.0)
            req = _jc("org.telegram.tgnet.TLRPC$TL_messages_getHistory")()
            req.peer = controller.getInputPeer(dialog)
            req.limit = 15
            res, err = self._pm_rpc(acc, req, lambda: False, timeout=15.0, retries=1)
            if err is not None or res is None:
                continue
            with tolerated():
                controller.putChats(res.chats, False)
                controller.putUsers(res.users, False)
            for msg in list(res.messages.toArray()):
                with tolerated():
                    doc = getattr(getattr(msg, "media", None), "document", None)
                    if doc is None or int(msg.date) < t0 - 30 or int(msg.id) <= 0:
                        continue
                    for attr in list(doc.attributes.toArray()):
                        if str(getattr(attr, "file_name", "") or "") == name:
                            return msg
        return None

    def _archive_link_flow(self, dialog, name, t0):
        acc = self._archive_account()

        def work():
            msg = None
            with tolerated():
                msg = self._archive_find_sent(acc, dialog, name, t0)
            run_on_ui_thread(lambda: self._archive_created_dialog(acc, dialog, msg))
        threading.Thread(target=work, daemon=True, name="smq-archive-link").start()

    def _archive_created_dialog(self, acc, dialog, msg) -> None:
        if msg is None:
            self._bulletin(strings("archive_link_unavailable"), error=True)
            return
        link = f"https://t.me/{ARCHIVE_USERNAME}/{int(msg.id)}"

        def copy():
            done = False
            with tolerated():
                find_class("org.telegram.messenger.AndroidUtilities").addToClipboard(link)
                done = True
            if not done:
                with tolerated():
                    ctx = find_class("org.telegram.messenger.ApplicationLoader").applicationContext
                    cm = ctx.getSystemService("clipboard")
                    cm.setPrimaryClip(jclass("android.content.ClipData").newPlainText("link", link))
            self._bulletin(strings("link_copied"))

        def forward():
            with tolerated():
                msg.dialog_id = dialog
            mo = find_class("org.telegram.messenger.MessageObject")(acc, msg, False, False)
            self._pick_forward(mo, keep_caption=True)

        fragment = get_last_fragment()
        act = fragment.getParentActivity() if fragment is not None else None
        if act is None:
            return
        builder = _jc("org.telegram.ui.ActionBar.AlertDialog$Builder")(act)
        click = _proxy("org.telegram.ui.ActionBar.AlertDialog$OnButtonClickListener", "onClick")
        builder.setTitle("Music +")
        text = strings("playlist_created")
        st = getattr(self, "_share_stats", None) or {}
        if st.get("out") is not None:
            out, raw = int(st["out"]), int(st.get("raw") or st["out"])
            text += "\n\n" + strings("archive_summary", out, raw)
            gone = max(0, raw - out)
            if gone:
                blocked = missing = 0
                for code, n in (st.get("errs") or {}).items():
                    if "RESTRICTED" in code:
                        blocked += n
                    elif any(k in code for k in ("INVALID", "NO_ID", "NOT_FOUND", "PRIVATE", "NOT_PARTICIPANT")):
                        missing += n
                blocked = min(blocked, gone)
                missing = min(missing, gone - blocked)
                other = gone - blocked - missing
                text += "\n\n" + strings("archive_left_out", gone)
                for n, key in ((blocked, "archive_why_restricted"), (missing, "archive_why_missing"),
                               (other, "archive_why_other")):
                    if n > 0:
                        text += "\n• " + strings(key, n)
        builder.setMessage(text)
        builder.setPositiveButton(strings("copy_link"), click(lambda d, w: copy()))
        builder.setNegativeButton(strings("forward_file"), click(lambda d, w: forward()))
        builder.create().show()
