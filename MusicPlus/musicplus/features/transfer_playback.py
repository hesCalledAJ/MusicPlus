import json
import os
import random
import threading
import time
from ..compat import (
 ArrayList,
 Divider,
 Switch,
 MethodHook,
 Text,
 find_class,
 get_last_fragment,
 get_private_field,
 jclass,
 set_private_field,
 run_on_ui_thread,
)
from elyx import strings
from ..android import _cls, _proxies, _proxy
from ..telegram_io import _MusicFetcher
from ..editor import _QueueEditor
from ..sheets import _jc
from ..native_sheets import _NativeSheet, _ProgressSheet
from ..safe import tolerated
from ..constants import HOWTO_URL


class _PluginTransferPlayback:
    def _xfer_tracks(self, tracks, cap=50000):
        out = []
        for t in list(tracks or ())[:cap]:
            with tolerated():
                r = {"i": int(t["i"]), "d": int(t["d"]), "t": str(t.get("t") or "")[:200],
             "a": str(t.get("a") or "")[:200], "s": int(t.get("s") or 0)}
                if t.get("pf"):
                    r["pf"] = int(t["pf"])
                out.append(r)
        return out

    def _xfer_creator(self):
        try:
            UC = find_class("org.telegram.messenger.UserConfig")
            u = UC.getInstance(UC.selectedAccount).getCurrentUser()
            un = ""
            try:
                un = str(find_class("org.telegram.messenger.UserObject").getPublicUsername(u) or "")
            except Exception:
                un = str(getattr(u, "username", "") or "")
            nm = str(find_class("org.telegram.messenger.UserObject").getUserName(u) or "")
            return {"d": int(u.id), "u": un, "n": nm[:64]}
        except Exception:
            return {}

    @staticmethod
    def _xfer_who(by):
        if not isinstance(by, dict):
            return ""
        u = str(by.get("u") or "").strip().lstrip("@")
        return ("@" + u) if u else str(by.get("n") or "").strip()

    def _xfer_share_tracks(self, name, items):
        tracks = self._xfer_tracks(self._lib_dicts([m for m in (items or ()) if m is not None]))
        self._share_stats = {"raw": len(items or ()), "conv": len(tracks)}
        if not tracks:
            self._bulletin(strings("nothing_to_share"), error=True)
            return
        nm = str(name or "").strip()[:60] or strings("playlist")
        self._archive_share(nm, tracks)

    def _share_playlist_opt(self, name, fetch):
        return (strings("share_as_playlist"), strings("share_with_other_music_users"), False,
       lambda: fetch(lambda items: self._xfer_share_tracks(name, items)))


    def _xfer_library(self):
        d = self._lib_data()
        return {"musicplus": 1, "kind": "library", "exported": int(time.time()), "by": self._xfer_creator(),
       "playlists": [{"name": p.get("name"), "created": int(p.get("created") or 0),
       "tracks": self._xfer_tracks(p.get("tracks"))}
       for p in d["playlists"] if p.get("id") not in self._XFER_SKIP],
       "chats": [{"d": int(c["d"]), "t": int(c.get("t") or 0), "n": c.get("n")} for c in d["chats"]],
       "friends": [{"d": int(f.get("d", f.get("id", 0)) or 0), "h": int(f.get("h", 0) or 0), "n": f.get("n")}
       for f in d["friends"]],
       "views": d.get("views") or {}}

    _XFER_SETTING_SKIP = ("library_v1", "live_queue_v1", "export_library_now", "export_settings_now",
    "clear_offline_cache_now", "excluded_artists_open", "lib_section_order_open", "update_last", "update_seen")
    _XFER_SETTING_KEYS = ("glass_follow_tg", "sheet_expand_first",
    "sheet_min_height", "tab_enabled", "tab_style", "tab_index", "drawer_enabled", "replace_row", "dynamic_tint", "keep_sheet_alive",
    "lyrics_keep_awake", "mini_compact",
    "hq_thumbs", "hq_thumbs_default_migrated", "persist_track_cache", "keep_queue_cached",
    "lib_auto_refresh", "lib_grid_columns", "lib_section_order", "artist_min_tracks", "pinned_artists",
    "excluded_artists", "max_queue_songs", "lock_queue", "locked_queue_behavior", "locked_queue_behavior_v2_migrated",
    "locked_queue_behavior_v3_migrated", "respect_hashtag", "respect_topic",
    "sleep_wait_for_last_track", "crossfade_sec", "pb_speed", "pb_pitch", "eq_on", "eq_gains", "eq_preset", "eq_user_presets", "eq_bass", "eq_virt", "eq_loud", "offline_mode", "offline_mode_v2", "stall_timeout_v5", "cancel_skipped_download", "preload_next_track", "update_check")

    def _xfer_settings(self):
        out = {}
        for k in self._XFER_SETTING_KEYS:
            if k in self._XFER_SETTING_SKIP:
                continue
            try:
                v = self.get_setting(k, None)
            except Exception:
                v = None
            if isinstance(v, (bool, int, float, str)):
                out[k] = v
        return {"musicplus": 1, "kind": "settings", "exported": int(time.time()), "by": self._xfer_creator(),
       "settings": out}

    def _xfer_parse(self, text):
        o = json.loads((text or "").lstrip("\ufeff"))
        if not isinstance(o, dict) or o.get("musicplus") != 1 or o.get("kind") not in ("playlist", "library", "settings"):
            raise ValueError("not a Music + file")
        return o

    def _xfer_async(self, build, then):
        def work():
            try:
                out = build()
            except Exception:
                out = None
            run_on_ui_thread(lambda: then(out))
        threading.Thread(target=work, daemon=True, name="smq-transfer").start()

    def _xfer_caption(self, n, who):
        head = "Music + Playlist\n" + strings("containing_n_tracks", n) + (f" by {who}" if who else "")
        label = strings("how_to_use")
        u16 = lambda t: len(t.encode("utf-16-le")) // 2
        return head + "\n\n" + label, [(u16(head) + 2, u16(label), HOWTO_URL)], head + "\n\n" + label + " " + HOWTO_URL

    def _xfer_send_entities(self, path, caption, ents, dialog):
        UC = find_class("org.telegram.messenger.UserConfig")
        acc = UC.selectedAccount
        me = UC.getInstance(acc).getClientUserId()
        smh = jclass("java.lang.Class").forName("org.telegram.messenger.SendMessagesHelper", True,
                                                self._xfer_ctx().getClassLoader())
        cands = [m for m in smh.getDeclaredMethods() if str(m.getName()) == "prepareSendingDocuments"
                 and len(m.getParameterTypes()) in (23, 27)
                 and str(m.getParameterTypes()[5].getName()) == "java.util.ArrayList"
                 and str(m.getParameterTypes()[4].getName()) == "java.lang.String"]
        if not cands:
            raise RuntimeError("prepareSendingDocuments missing")
        cands.sort(key=lambda x: len(x.getParameterTypes()))
        m = cands[0]
        Long, Int, Bool = jclass("java.lang.Long"), jclass("java.lang.Integer"), jclass("java.lang.Boolean")
        ai = find_class("org.telegram.messenger.AccountInstance").getInstance(acc)
        Ent = _jc("org.telegram.tgnet.TLRPC$TL_messageEntityTextUrl")
        el = ArrayList()
        for off, ln, url in ents:
            e = Ent()
            e.offset = int(off)
            e.length = int(ln)
            e.url = url
            el.add(e)
        args = []
        for i, t in enumerate(m.getParameterTypes()):
            tn = str(t.getName())
            if tn.endswith("AccountInstance"):
                args.append(ai)
            elif i in (1, 2):
                lst = ArrayList()
                lst.add(path)
                args.append(lst)
            elif i == 4:
                args.append(caption)
            elif i == 5:
                args.append(el)
            elif i == 6:
                args.append("application/octet-stream")
            elif tn == "long":
                args.append(Long(me if dialog is None else int(dialog)) if i == 7 else Long(0))
            elif tn == "boolean":
                args.append(Bool(i == 13))
            elif tn == "int":
                args.append(Int(0))
            else:
                args.append(None)
        m.setAccessible(True)
        m.invoke(None, *args)

    def _xfer_send_saved(self, path, caption, dialog=None, ents=None, plain=None):
        if ents:
            try:
                self._xfer_send_entities(path, caption, ents, dialog)
                return True, ""
            except Exception:
                caption = plain or caption
        try:
            UC = find_class("org.telegram.messenger.UserConfig")
            acc = UC.selectedAccount
            me = UC.getInstance(acc).getClientUserId()
            ctx = self._xfer_ctx()
            smh = jclass("java.lang.Class").forName("org.telegram.messenger.SendMessagesHelper", True, ctx.getClassLoader())
            opts = [m for m in smh.getDeclaredMethods() if str(m.getName()) == "prepareSendingDocument"]
            if not opts:
                return False, "prepareSendingDocument missing"
            opts.sort(key=lambda x: len(x.getParameterTypes()), reverse=True)
            Long, Int, Bool = jclass("java.lang.Long"), jclass("java.lang.Integer"), jclass("java.lang.Boolean")
            ai = find_class("org.telegram.messenger.AccountInstance").getInstance(acc)
            err = ""
            for m in opts:
                try:
                    strings = [path, path, caption or None, "application/octet-stream"]
                    args, long_done = [], False
                    for t in m.getParameterTypes():
                        tn = str(t.getName())
                        if tn.endswith("AccountInstance"):
                            args.append(ai)
                        elif tn == "java.lang.String":
                            args.append(strings.pop(0) if strings else None)
                        elif tn == "java.lang.CharSequence":
                            args.append(caption or None)
                        elif tn == "long" and not long_done:
                            args.append(Long(me if dialog is None else int(dialog)))
                            long_done = True
                        elif tn == "long":
                            args.append(Long(0))
                        elif tn == "int":
                            args.append(Int(0))
                        elif tn == "boolean":
                            args.append(Bool(True))
                        else:
                            args.append(None)
                    m.setAccessible(True)
                    m.invoke(None, *args)
                    return True, ""
                except Exception as e:
                    err = f"{type(e).__name__}: {e}"[:160]
            return False, err
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"[:160]

    def _xfer_send(self, obj, stem="Backup", ext=".mpdb"):
        def build():
            o = obj() if callable(obj) else obj
            txt = json.dumps(o, separators=(",", ":"), ensure_ascii=False)
            ctx = self._xfer_ctx()
            base = ctx.getExternalCacheDir() or ctx.getCacheDir()
            dd = _cls("java.io.File")(base, "musicplus_send")
            dd.mkdirs()
            d = str(dd.getAbsolutePath())
            with tolerated():
                for f in os.listdir(d):
                    os.remove(os.path.join(d, f))
            who = self._xfer_who(o.get("by"))
            if o.get("kind") == "playlist":
                safe = "".join("_" if (c in '\\/:*?"<>|' or ord(c) < 32) else c
             for c in str(o.get("name") or "")).strip().strip(".")[:80] or "Playlist"
                name = safe + ext
                n = len(o.get("tracks") or ())
                cap = self._xfer_caption(n, who)
            elif o.get("kind") == "settings":
                name = f"MusicPlusSettings-{time.strftime('%Y-%m-%d')}{ext}"
                cap = None
            else:
                name = f"MusicPlus{stem}-{time.strftime('%Y-%m-%d')}{ext}"
                cap = None
            path = os.path.join(d, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(txt)
            return path, cap, name, o.get("archive") if o.get("kind") == "playlist" else None
        def finish(ok, why, where=None):
            self._bulletin((strings("sent_to_n", where) if where else strings("sent_to_saved_messages")) if ok
          else strings("couldnt_send_the_file") + (f" ({why})" if why else ""), error=not ok)
        def then(res):
            if not res:
                finish(False, "")
                return
            path, cap, fname, arch = res
            text, ents, plain = cap if isinstance(cap, tuple) else (cap, None, None)
            t0 = int(time.time())
            try:
                ok, why = self._xfer_send_saved(path, text, int(arch) if arch else None, ents, plain)
            except Exception as e:
                ok, why = False, type(e).__name__
            if arch:
                if ok:
                    self._archive_link_flow(int(arch), fname, t0)
                else:
                    finish(False, why)
            else:
                finish(ok, why)
        self._xfer_async(build, then)

    def _xfer_ctx(self):
        return find_class("org.telegram.messenger.ApplicationLoader").applicationContext

    def _xfer_apply(self, o):
        if o.get("kind") == "settings":
            n = 0
            skip = set(self._XFER_SETTING_SKIP) | {"library_v1", "live_queue_v1"}
            for k, v in dict(o.get("settings") or {}).items():
                k = str(k)
                if k in skip or not isinstance(v, (bool, int, float, str)):
                    continue
                with tolerated():
                    if k == "excluded_artists":
                        ex = set(json.loads(self.get_setting("excluded_artists", "[]") or "[]"))
                        ex |= {str(x) for x in (json.loads(v) if isinstance(v, str) else [])[:5000]}
                        v = json.dumps(sorted(ex))
                    self.set_setting(k, v)
                    n += 1
            self._artist_dirty = True
            with tolerated():
                self._request_library_refresh()
            return strings("imported_n_settings_restart_the_app", n)
        if o.get("kind") == "playlist":
            tracks = self._xfer_tracks(o.get("tracks"))
            if not tracks:
                return strings("nothing_to_import")
            if o.get("archive"):
                self._archive_prime()
            base = (str(o.get("name") or "").strip()[:54] or strings("playlist"))
            names = {str(p.get("name", "")).strip().casefold() for p in self._lib_data()["playlists"]}
            for p in self._lib_data()["playlists"]:
                if p.get("id") in self._XFER_SKIP or str(p.get("name", "")).strip().casefold() != base.casefold():
                    continue
                have = {(t["i"], t["d"]) for t in (p.get("tracks") or ())}
                if all((t["i"], t["d"]) in have for t in tracks):
                    return strings("n_already_exists", base)
            name, n = base, 1
            while name.casefold() in names:
                n += 1
                name = f"{base} ({n})"
            self._lib_create(name, tracks)
            return strings("imported_n_n_tracks", name, len(tracks))
        d = self._lib_data()
        by = {str(p.get("name", "")).strip().casefold(): p for p in d["playlists"] if p.get("id") not in self._XFER_SKIP}
        npl = ntr = nch = nfr = 0
        stamp = f"{int(time.time() * 1000)}"
        for src in list(o.get("playlists") or [])[:500]:
            if not isinstance(src, dict):
                continue
            name = str(src.get("name") or "").strip()[:60] or strings("playlist")
            if name.casefold() in by:
                continue
            pl = {"id": f"p{stamp}{npl}", "name": name, "tracks": [],
          "created": int(src.get("created") or time.time())}
            d["playlists"].append(pl)
            by[name.casefold()] = pl
            npl += 1
            have = set()
            for t in self._xfer_tracks(src.get("tracks")):
                k = (t["i"], t["d"])
                if k not in have:
                    have.add(k)
                    pl["tracks"].append(t)
                    ntr += 1
        try:
            acc = int(find_class("org.telegram.messenger.UserConfig").selectedAccount)
        except Exception:
            acc = 0
        seen = {(int(c["d"]), int(c.get("t") or 0)) for c in d["chats"]}
        for c in list(o.get("chats") or [])[:2000]:
            with tolerated():
                k = (int(c["d"]), int(c.get("t") or 0))
                if k not in seen:
                    seen.add(k)
                    d["chats"].append({"d": k[0], "t": k[1], "n": str(c.get("n") or "")[:60], "a": acc})
                    nch += 1
        seen = {int(f.get("d", f.get("id", 0)) or 0) for f in d["friends"]}
        for f in list(o.get("friends") or [])[:2000]:
            with tolerated():
                u = int(f["d"])
                if u not in seen:
                    seen.add(u)
                    d["friends"].append({"d": u, "h": int(f.get("h", 0) or 0), "a": acc, "n": str(f.get("n") or "")[:60]})
                    nfr += 1
        views = o.get("views")
        if isinstance(views, dict):
            cur = d.setdefault("views", {})
            for k, v in views.items():
                cur.setdefault(str(k), v)
        self._artist_dirty = True
        self._lib_save()
        self._request_library_refresh()
        if not (npl or ntr or nch or nfr):
            return strings("nothing_new_to_import")
        return strings("imported_n_playlists_n_tracks_n", npl, ntr, nch, nfr)

    def _xfer_from_message(self, msg):
        f = self._msg_local_file(msg)
        if f is not None:
            self._xfer_from_file(f)
            return
        self._bulletin(strings("downloading_backup"))
        self._start_download(msg)
        self._xfer_poll(msg, 0)

    def _xfer_poll(self, msg, n):
        f = self._msg_local_file(msg)
        if f is not None:
            self._xfer_from_file(f)
            return
        if n >= 40:
            self._bulletin(strings("couldnt_download_the_backup"), True)
            return
        self._post(lambda: self._xfer_poll(msg, n + 1), 500)

    def _xfer_from_file(self, f):
        def work():
            try:
                p = str(f.getAbsolutePath())
                if os.path.getsize(p) > self._XFER_MAX_BYTES:
                    raise ValueError("too big")
                with open(p, "r", encoding="utf-8-sig") as fh:
                    o = self._xfer_parse(fh.read())
            except Exception:
                run_on_ui_thread(lambda: self._bulletin(strings("this_isnt_a_music_backup"), True))
                return
            run_on_ui_thread(lambda: self._xfer_confirm(o))
        threading.Thread(target=work, daemon=True).start()

    def _xfer_confirm(self, o):
        with tolerated():
            act = get_last_fragment().getParentActivity()
            if act is None:
                return
            if o.get("kind") == "settings":
                what = ""
            elif o.get("kind") == "playlist":
                what = strings("playlist_n_n_tracks", str(o.get("name") or strings("playlist"))[:60],
             len(o.get("tracks") or ()))
            else:
                what = strings("n_playlists_n_chats_n_friends", len(o.get("playlists") or ()),
             len(o.get("chats") or ()), len(o.get("friends") or ()))
            click = _proxy("org.telegram.ui.ActionBar.AlertDialog$OnButtonClickListener", "onClick")
            b = _jc("org.telegram.ui.ActionBar.AlertDialog$Builder")(act)
            b.setTitle(strings("import_music_settings") if o.get("kind") == "settings" else strings("import_music_data"))
            who = self._xfer_who(o.get("by"))
            if who:
                what += "\n" + strings("author_n", who)
            if o.get("kind") == "settings":
                b.setMessage(strings("your_current_music_settings_will_be"))
            else:
                b.setMessage(what + "\n\n" + strings("it_is_merged_with_your_library"))
            b.setPositiveButton(strings("import"), click(lambda d, w: self._bulletin(self._xfer_apply(o))))
            b.setNegativeButton(strings("cancel"), click(lambda d, w: None))
            b.create().show()

    def _backup_rows(self):
        info = strings("saves_a_backup_file_to_your")
        def runner(fn):
            def run(*_a):
                try:
                    run_on_ui_thread(fn)
                except Exception:
                    fn()
            return run
        return [Text(text=strings("export_library"), icon="files_internal", accent=True,
       on_click=runner(lambda: self._xfer_send(self._xfer_library))),
       Text(text=strings("export_settings"), icon="filled_profile_settings", accent=True,
       on_click=runner(lambda: self._xfer_send(self._xfer_settings, "Settings", ".mpss"))),
       Divider(text=info)]

    def _cache_clear_row(self):
        text = strings("clear_offline_library_cache")
        def do_clear(dlg=None):
            with tolerated():
                freed = self._tstore.clear() + self._sstore.clear()
                with tolerated():
                    os.remove(self._sstore.gone_path())
                self._resolver.gone.clear()
                self._chat_track_cache.clear()
                self._msg_cache.clear()
                self._bulletin(strings("offline_cache_cleared_n_mb", freed / 1048576))
            if dlg is not None:
                dlg.dismiss()
        def run(*_a):
            def show():
                with tolerated():
                    fragment = get_last_fragment()
                    act = fragment.getParentActivity() if fragment is not None else None
                    if act is None:
                        do_clear()
                        return
                    sh = _NativeSheet(act, strings("clear_offline_cache"),
                strings("all_saved_track_lists_are_deleted"))
                    sh.primary_button(strings("clear_cache"), lambda: do_clear(sh.dlg), color=sh.c_red)
                    sh.secondary_row((strings("cancel"), sh.dlg.dismiss))
                    sh.show()
            try:
                run_on_ui_thread(show)
            except Exception:
                show()
        if Text is not None:
            with tolerated():
                return Text(text=text, icon="msg_delete", accent=True, on_click=run)
        return Switch(key="clear_offline_cache_now", text=text, default=False,
       subtext=strings("deletes_the_saved_track_lists_they"),
       on_change=lambda v: run() if v else None)

    @staticmethod
    def _msg_key(m):
        try:
            return (int(m.getId()), int(m.getDialogId()))
        except Exception:
            return None

    def _playing_key(self, mc):
        try:
            pm = mc.getPlayingMessageObject()
            return self._msg_key(pm) if pm is not None else None
        except Exception:
            return None

    def _chat_messages(self, frag):
        out, seen = [], set()
        def add(m):
            if m is None:
                return
            k = self._msg_key(m)
            if k is not None and k not in seen:
                seen.add(k)
                out.append(m)
        msgs = self._read(frag, "messages")
        if msgs is not None:
            with tolerated():
                for i in range(msgs.size()):
                    add(msgs.get(i))
        if not out:
            with tolerated():
                lv = self._read(frag, "chatListView")
                for i in range(int(lv.getChildCount())):
                    v = lv.getChildAt(i)
                    with tolerated():
                        add(v.getMessageObject())
        return out

    def _chat_scope(self, context):
        frag = None
        with tolerated():
            frag = get_last_fragment()
        loaded = self._chat_messages(frag) if frag is not None else []
        music = []
        for m in loaded:
            with tolerated():
                if m.isMusic():
                    music.append(m)
        dialog_id = 0
        if music:
            try:
                dialog_id = int(music[0].getDialogId())
            except Exception:
                dialog_id = 0
        if not dialog_id and frag is not None:
            dialog_id = self._to_int(self._read(frag, "getDialogId"))
        if not dialog_id:
            try:
                dialog_id = self._to_int(
             context.get("dialog_id") or context.get("userId") or context.get("user_id")) if context else 0
                if not dialog_id and context and context.get("user") is not None:
                    dialog_id = self._to_int(self._read(context.get("user"), "id", "user_id"))
            except Exception:
                dialog_id = 0
        topic_id = self._detect_topic_id(frag, music[0] if music else None) if frag is not None else 0
        tracks = []
        for m in music:
            if topic_id:
                mt = self._get_message_topic_id(m, True)
                if mt != 0 and mt != topic_id:
                    continue
            tracks.append(m)
        tracks.sort(key=lambda m: int(m.getId()))
        return frag, dialog_id, topic_id, tracks, len(loaded)

    def _chat_account(self, frag, music) -> int:
        for m in music or []:
            try:
                return int(m.currentAccount)
            except Exception:
                break
        acc = self._read(frag, "getCurrentAccount", "currentAccount") if frag is not None else None
        if acc is not None:
            return self._to_int(acc)
        try:
            return int(_jc("org.telegram.messenger.UserConfig").selectedAccount)
        except Exception:
            return 0

    def _fetch_and_insert(self, kind, frag, dialog_id, topic_id, loaded_tracks):
        pkey = ("fetch", int(dialog_id or 0), int(topic_id or 0))
        act = frag.getParentActivity() if frag is not None else None
        if act is None or not dialog_id:
            self._bulletin(strings("cant_determine_this_chat"), error=True)
            return
        scope = strings("topic") if topic_id else strings("chat").lower()
        acc = self._chat_account(frag, loaded_tracks)
        sheet = _ProgressSheet(self, act)
        partial = {"continue": False}
        def on_progress(count, total):
            if total and total >= count:
                sheet.set_text(strings("n_of_n_tracks", count, total))
            else:
                sheet.set_text(strings("n_tracks_found", count))
            self._prog_set(pkey, count, total if total and total >= count else 0)
        def on_done(tracks, error, cancelled):
            sheet.close()
            self._prog_end(pkey)
            self._request_library_refresh()
            if cancelled and not partial["continue"]:
                return
            used = tracks
            if topic_id == 1 and used:
                with tolerated():
                    batch = ArrayList()
                    for item in used:
                        batch.add(item)
                    filtered_general = self._filter_messages(batch, 1, None, None)
                    used = ([filtered_general.get(i) for i in range(filtered_general.size())]
                if filtered_general is not None else [])
            if (error or partial["continue"]) and not tracks and loaded_tracks:
                used = loaded_tracks
                self._bulletin(strings("fetch_failed_n_using_loaded_messages", error), error=True)
            elif error and not tracks:
                self._bulletin(strings("couldnt_load_music_n", error), error=True)
                return
            if not used:
                self._bulletin(strings("no_music_found_in_this_n", scope), error=True)
                return
            mc = self._get_mc()
            pl = self._get_playlist(mc) if mc is not None else None
            if pl is None or pl.size() == 0 or self._playing_key(mc) is None:
                self._bulletin(strings("playback_stopped_start_a_track_first"), error=True)
                return
            added = self._queue_bulk_insert(mc, pl, used, next_=(kind == "next"))
            if added:
                where = strings("next") if kind == "next" else strings("to_the_bottom")
                extra = strings("hit_the_n_limit", _MusicFetcher.CAP) if len(used) >= _MusicFetcher.CAP else ""
                self._bulletin(strings("added_n_tracks_n_n", added, where, extra))
            else:
                self._bulletin(strings("nothing_new_to_add"), error=True)
        fetcher = _MusicFetcher(self, acc, dialog_id, topic_id, on_progress, on_done)
        def continue_partial():
            partial["continue"] = True
            fetcher.stop_with_partial()
        def cancel_fetch():
            fetcher.cancel()
            self._prog_end(pkey)
        if not self._library_ui_active():
            sheet.show_progress(strings("loading_music_of_this_n", scope), cancel_fetch,
          on_continue=continue_partial)
        else:
            with tolerated():
                sheet.close()
        self._prog_set(pkey, 0, 0)
        fetcher.start()

    def _playback_descending(self, L, rev) -> bool:
        desc = asc = 0
        prev = None
        for m in L:
            if m is None:
                continue
            try:
                cur = (int(m.getDialogId()), int(m.getId()))
            except Exception:
                continue
            if prev is not None and prev[0] == cur[0]:
                if cur[1] < prev[1]:
                    desc += 1
                elif cur[1] > prev[1]:
                    asc += 1
            prev = cur
        if desc != asc:
            return desc > asc
        return not rev

    def _prepare_editable_order(self):
        shuffle_on, rev = self._read_order()
        return shuffle_on, rev

    def _do_chat_action(self, kind, context):
        try:
            mc = self._get_mc()
            pl = self._get_playlist(mc) if mc is not None else None
            frag, dialog_id, topic_id, tracks, _ = self._chat_scope(context)
            scope = strings("topic") if topic_id else strings("chat").lower()
            if kind == "exclude":
                if pl is None or pl.size() == 0:
                    self._bulletin(strings("queue_is_empty"), error=True)
                    return
                removed, kept_playing = self._queue_exclude(mc, pl, dialog_id, topic_id)
                if removed:
                    note = strings("kept_the_playing_track") if kept_playing else ""
                    self._bulletin(strings("excluded_n_tracks_of_this_n", removed, scope, note))
                else:
                    self._bulletin(strings("nothing_from_this_n_in_the", scope), error=True)
                return
            if pl is None or pl.size() == 0 or self._playing_key(mc) is None:
                self._bulletin(strings("start_playing_a_track_first"), error=True)
                return
            self._fetch_and_insert(kind, frag, dialog_id, topic_id, tracks)
        except Exception:
            self._bulletin(strings("queue_action_failed"), error=True)

    def _queue_exclude(self, mc, playlist, dialog_id, topic_id):
        self._prepare_editable_order()
        playing = self._playing_key(mc)
        removed = 0
        kept_playing = False
        pmap = None
        with tolerated():
            pmap = get_private_field(mc, "playlistMap")
        for i in range(playlist.size() - 1, -1, -1):
            m = playlist.get(i)
            if m is None:
                continue
            try:
                if dialog_id and int(m.getDialogId()) != dialog_id:
                    continue
                if topic_id and self._get_message_topic_id(m, True) != topic_id:
                    continue
            except Exception:
                continue
            if playing is not None and self._msg_key(m) == playing:
                kept_playing = True
                continue
            playlist.remove(i)
            removed += 1
            with tolerated():
                if pmap is not None:
                    pmap.remove(m.getId())
        if removed:
            self._finish_bulk_edit(mc, playlist)
        return removed, kept_playing

    def _queue_exclude_messages(self, messages):
        mc = self._get_mc()
        playlist = self._get_playlist(mc) if mc is not None else None
        if playlist is None or playlist.size() == 0:
            return 0, False
        keys = set()
        for message in messages or []:
            with tolerated():
                key = self._msg_key(message)
                if key is not None:
                    keys.add(key)
        if not keys:
            return 0, False
        self._prepare_editable_order()
        playing = self._playing_key(mc)
        removed = 0
        kept_playing = False
        pmap = None
        with tolerated():
            pmap = get_private_field(mc, "playlistMap")
        for i in range(playlist.size() - 1, -1, -1):
            message = playlist.get(i)
            if message is None or self._msg_key(message) not in keys:
                continue
            if playing is not None and self._msg_key(message) == playing:
                kept_playing = True
                continue
            playlist.remove(i)
            removed += 1
            with tolerated():
                if pmap is not None:
                    pmap.remove(message.getId())
        if removed:
            self._finish_bulk_edit(mc, playlist)
        return removed, kept_playing

    def _queue_bulk_insert(self, mc, playlist, tracks, next_: bool, keep_order: bool = False) -> int:
        shuffle_on, rev = self._prepare_editable_order()
        raw = [playlist.get(i) for i in range(playlist.size())]
        L = raw if rev else raw[::-1]
        playing = self._playing_key(mc)
        desc = self._playback_descending(L, rev)
        seq = list(tracks) if keep_order else sorted(tracks, key=lambda m: int(m.getId()), reverse=desc)
        seq_pairs = []
        incoming = set()
        for message in seq:
            key = self._msg_key(message)
            if key is None or key == playing or key in incoming:
                continue
            incoming.add(key)
            seq_pairs.append((message, key))
        seq = [message for message, _key in seq_pairs]
        seq_keys = {key for _message, key in seq_pairs}
        queue_pairs = [(message, self._msg_key(message)) for message in L if message is not None]
        if next_:
            rest = [message for message, key in queue_pairs
          if key not in seq_keys or key == playing]
            pp = -1
            for i, message in enumerate(rest):
                if self._msg_key(message) == playing:
                    pp = i
                    break
            new = rest[:pp + 1] + seq + rest[pp + 1:] if pp >= 0 else rest + seq
            added = len(seq)
        else:
            existing = {key for _message, key in queue_pairs if key is not None}
            add = [message for message, key in seq_pairs if key not in existing]
            new = L + add
            added = len(add)
        if added == 0:
            return 0
        order = new if rev else new[::-1]
        playlist.clear()
        for m in order:
            playlist.add(m)
        for m in seq:
            self._map_put(mc, m)
        if shuffle_on:
            placed = seq if next_ else add
            if not self._shuffle_place(mc, playlist, placed, next_):
                self._finish_bulk_edit(mc, playlist)
        else:
            self._finish_bulk_edit(mc, playlist)
        return added

    def _shuffle_queue(self):
        mc = self._get_mc()
        pl = self._get_playlist(mc) if mc is not None else None
        if pl is None or pl.size() < 2:
            return None
        _, rev = self._prepare_editable_order()
        raw = [pl.get(i) for i in range(pl.size())]
        snapshot = list(raw)
        L = raw if rev else raw[::-1]
        playing = self._playing_key(mc)
        cur = [m for m in L if playing is not None and m is not None and self._msg_key(m) == playing][:1]
        others = [m for m in L if m is not None and not (cur and m is cur[0])
       and not (playing is not None and self._msg_key(m) == playing)]
        random.shuffle(others)
        new = cur + others
        if len(new) != len(L):
            return None
        for i, m in enumerate(new if rev else new[::-1]):
            pl.set(i, m)
        self._finish_bulk_edit(mc, pl)
        return snapshot

    def _sort_queue(self, mode, desc=False):
        mc = self._get_mc()
        pl = self._get_playlist(mc) if mc is not None else None
        if pl is None or pl.size() < 2:
            return None
        _, rev = self._prepare_editable_order()
        raw = [pl.get(i) for i in range(pl.size())]
        snapshot = list(raw)
        L = [m for m in (raw if rev else raw[::-1]) if m is not None]
        if len(L) != len(raw):
            return None
        def dur(m):
            try:
                return int(m.getDuration())
            except Exception:
                return 0
        if mode == "title":
            key = lambda m: (_QueueEditor._title_of(m).lower(), _QueueEditor._author_of(m).lower())
        elif mode == "artist":
            key = lambda m: (_QueueEditor._author_of(m).lower(), _QueueEditor._title_of(m).lower())
        elif mode == "duration":
            key = dur
        else:
            return None
        new = sorted(L, key=key, reverse=bool(desc))
        for i, m in enumerate(new if rev else new[::-1]):
            pl.set(i, m)
        self._finish_bulk_edit(mc, pl)
        return snapshot

    def _restore_queue(self, snapshot) -> bool:
        mc = self._get_mc()
        pl = self._get_playlist(mc) if mc is not None else None
        if pl is None or pl.size() != len(snapshot):
            return False
        for i, m in enumerate(snapshot):
            pl.set(i, m)
        self._finish_bulk_edit(mc, pl)
        return True

    def _show_in_chat(self, msg):
        try:
            frag = get_last_fragment()
            did, mid = int(msg.getDialogId()), int(msg.getId())
            if self._pm_is_synth(msg) or getattr(msg, "messageOwner", None) is None:
                src = None
                with tolerated():
                    src = self._pm_src_get(msg.getDocument().id)
                if src:
                    did, mid = src
                else:
                    args = jclass("android.os.Bundle")()
                    try:
                        args.putLong("user_id", abs(did))
                    except Exception:
                        args.putInt("user_id", int(abs(did)))
                    frag.presentFragment(find_class("org.telegram.ui.ProfileActivity")(args))
                    return
            args = jclass("android.os.Bundle")()
            key = "user_id" if did > 0 else "chat_id"
            try:
                args.putLong(key, abs(did))
            except Exception:
                args.putInt(key, int(abs(did)))
            args.putInt("message_id", int(mid))
            frag.presentFragment(find_class("org.telegram.ui.ChatActivity")(args))
        except Exception:
            self._bulletin(strings("couldnt_open_the_chat"), error=True)

    def _open_chat_scope(self, dialog_id, topic_id=0):
        try:
            frag = get_last_fragment()
            if frag is None:
                self._bulletin(strings("cant_open_this_chat_here"), error=True)
                return
            did = int(dialog_id)
            topic = int(topic_id or 0)
            args = jclass("android.os.Bundle")()
            args.putLong("dialog_id", did)
            args.putLong("user_id" if did > 0 else "chat_id", abs(did))
            if topic:
                args.putLong("thread_msg_id", topic)
                args.putLong("topic_id", topic)
            frag.presentFragment(find_class("org.telegram.ui.ChatActivity")(args))
        except Exception:
            self._bulletin(strings("couldnt_open_the_chat"), error=True)

    def _pick_forward(self, msg, keep_caption=False):
        try:
            items = [m for m in (msg if isinstance(msg, (list, tuple)) else [msg]) if m is not None]
            if not items:
                return
            frag = get_last_fragment()
            lst = ArrayList()
            for m in items:
                lst.add(m)
            alert = find_class("org.telegram.ui.Components.ShareAlert")(
          frag.getParentActivity(), lst, None, False, None, False)
            with tolerated():
                set_private_field(alert, "showSendersName", False)
            self._fwd_alert = alert
            self._fwd_keep_caption = bool(keep_caption)
            self._fwd_menu_opened = False
            frag.showDialog(alert)
        except Exception:
            self._bulletin(strings("couldnt_open_the_forward_picker"), error=True)

    def _install_forward_hook(self):
        SMH = find_class("org.telegram.messenger.SendMessagesHelper")
        if SMH is None:
            return
        plugin = self
        Boolean = jclass("java.lang.Boolean")
        class ForwardHook(MethodHook):
            def before_hooked_method(self, param):
                with tolerated():
                    alert = getattr(plugin, "_fwd_alert", None)
                    if alert is None:
                        return
                    if not bool(alert.isShowing()):
                        plugin._fwd_alert = None
                        return
                    if len(param.args) == 12 and param.args[0] is not None:
                        if not getattr(plugin, "_fwd_menu_opened", False):
                            param.args[2] = Boolean.valueOf(True)
                        if not getattr(plugin, "_fwd_keep_caption", False):
                            param.args[3] = Boolean.valueOf(True)
        unhooks = self.hook_all_methods(SMH, "sendMessage", ForwardHook())
        if unhooks:
            self._hooks.extend(unhooks if isinstance(unhooks, list) else [unhooks])
        SA = find_class("org.telegram.ui.Components.ShareAlert")
        if SA is None:
            return
        class MenuHook(MethodHook):
            def after_hooked_method(self, param):
                with tolerated():
                    if getattr(plugin, "_fwd_alert", None) is not None:
                        plugin._fwd_menu_opened = True
        unhooks = self.hook_all_methods(SA, "onSendLongClick", MenuHook())
        if unhooks:
            self._hooks.extend(unhooks if isinstance(unhooks, list) else [unhooks])

    def _is_loading(self, m) -> bool:
        try:
            FL = find_class("org.telegram.messenger.FileLoader")
            doc = m.getDocument()
            name = str(FL.getAttachFileName(doc)) if doc is not None else str(m.getFileName())
            return bool(FL.getInstance(int(m.currentAccount)).isLoadingFile(name))
        except Exception:
            return False

    def _start_download(self, m):
        with tolerated():
            if self._unavailable(m):
                return
            FL = find_class("org.telegram.messenger.FileLoader")
            prio = int(getattr(FL, "PRIORITY_NORMAL", 1))
            FL.getInstance(int(m.currentAccount)).loadFile(m.getDocument(), m, prio, 0)
        with tolerated():
            self._schedule_deleted_check(m, 8.0)

    def _post(self, fn, ms):
        _, _, Run = _proxies()
        h = jclass("android.os.Handler")(jclass("android.os.Looper").getMainLooper())
        h.postDelayed(Run(fn), int(ms))

    def _dl_cancelled_set(self):
        return self.__dict__.setdefault("_dl_cancelled", set())

    def _dl_norm(self, msgs):
        return [m for m in (msgs if isinstance(msgs, (list, tuple)) else [msgs]) if m is not None]

    def _dl_option(self, msgs, dl_sub, cancel_sub):
        st = self._dl_state(msgs)
        if st == "done":
            return ()
        if st == "cancel":
            return (strings("cancel_downloading"), cancel_sub, False, lambda: self._cancel_downloads(msgs))
        return (strings("download"), dl_sub, False, lambda: self._download_tracks(msgs))

    def _dl_state(self, msgs):
        loading = missing = False
        for m in self._dl_norm(msgs):
            with tolerated():
                if self._is_downloaded(m) or self._unavailable(m):
                    continue
            missing = True
            with tolerated():
                if self._is_loading(m):
                    loading = True
                    break
        return "cancel" if loading else ("download" if missing else "done")
