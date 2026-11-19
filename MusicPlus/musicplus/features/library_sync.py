import json
import os
import random
import threading
import time
from ..compat import (
 ArrayList,
 find_class,
 get_private_field,
 jarray,
 jbyte,
 jclass,
 run_on_ui_thread,
)
from ..constants import _PROGRESSIVE_SHUFFLE_POOL
from elyx import strings
from ..helpers import _deep_tuple, _pln
from ..helpers import _LIB_DYN
from ..tabs import _PROGRESSIVE_PREV_TRACKS
from ..editor import _QueueEditor
from ..sheets import _ActionSheet
from ..safe import tolerated


class _PluginLibrarySync:
    def _topic_title(self, dialog_id, topic_id, acc=0) -> str:
        with tolerated():
            MCtl = find_class("org.telegram.messenger.MessagesController").getInstance(int(acc))
            topic = MCtl.getTopicsController().findTopic(-int(dialog_id), int(topic_id))
            if topic is not None and topic.title:
                return str(topic.title).strip()
        return ""

    def _topic_label(self, dialog_id, topic_id, acc=0) -> str:
        return (self._topic_title(dialog_id, topic_id, acc)
       or (strings("general") if int(topic_id) == 1 else strings("topic_n", topic_id)))

    @staticmethod
    def _origin_chat_key(sc):
        with tolerated():
            h = sc[0]
            if h in ("chat", "topic") and len(sc) >= 3:
                return int(sc[1]), int(sc[2] or 0), ""
            if isinstance(h, int) or (isinstance(h, str) and h.lstrip("-").isdigit()):
                t = sc[1] if len(sc) > 1 else 0
                return int(h), int(t) if str(t).lstrip("-").isdigit() else 0, str(sc[2] if len(sc) > 2 else "")
        return None

    def _origin_set(self, name=None, scope=None, cover=False, owned=False):
        self._queue_name = (str(name).strip() or None) if name else None
        self._queue_scope_key = _deep_tuple(scope)
        if cover is not False:
            self._queue_cover_key = _deep_tuple(cover) if cover is None or isinstance(cover, (tuple, list)) else self._msg_key(cover)
        if owned is not False:
            self._lib_owned = owned

    def _origin_title(self, name=None, scope=None):
        nm = str(name or "").strip()
        ck = self._origin_chat_key(scope)
        if nm and not (ck and nm == strings("queue")):
            return nm
        with tolerated():
            h, acc = scope[0], int(self._chat_account(None, None) or 0)
            if h == "playlist":
                pl = self._lib_pl(scope[1])
                return _pln(pl.get("name") or "") if pl else nm
            if h == "artist":
                return str(scope[2] if len(scope) > 2 and scope[2] else scope[1])
            if h in ("profile_music", "friend"):
                uid = int(scope[1])
                return (strings("my_profile") if h == "profile_music" and uid == self._me(acc) else self._dialog_title(uid, acc)) or nm
            if ck and self._dialog_title(ck[0], acc):
                return self._auto_queue_name(ck[0], ck[1], ck[2] or None, acc)
        return nm

    def _origin_display(self):
        return self._origin_title(self._queue_name, self._queue_scope_key) or strings("queue")

    def _saved_music_uid(self):
        with tolerated():
            mc = self._get_mc()
            lst = getattr(mc, "currentSavedMusicList", None) if mc is not None else None
            if lst is not None:
                uid = int(lst.dialogId)
                pm = mc.getPlayingMessageObject()
                if pm is not None and int(pm.getDialogId()) != uid:
                    return 0
                return uid
        return 0

    def _profile_scope_sync(self):
        uid = self._saved_music_uid()
        if not uid:
            return False
        k = self._queue_scope_key
        if isinstance(k, (tuple, list)) and len(k) >= 2 and k[0] == "profile_music" and int(k[1]) == uid and self._queue_name:
            return True
        if time.monotonic() < getattr(self, "_origin_pin_until", 0.0):
            return False
        with tolerated():
            acc = int(self._chat_account(None, None) or 0)
            name = strings("my_profile") if uid == self._me(acc) else self._dialog_title(uid, acc)
            self._origin_set((name or strings("profile_playlist"))[:60], ("profile_music", uid))
            return True
        return False

    def _origin_pack(self):
        with tolerated():
            self._profile_scope_sync()
        sc = self._queue_scope_key
        return [self._origin_title(self._queue_name, sc) or None, list(sc) if isinstance(sc, (tuple, list)) else None]

    def _auto_queue_name(self, dialog_id, topic_id=0, query=None, acc=0) -> str:
        chat = self._dialog_title(dialog_id, acc) if dialog_id else ""
        tail = ""
        if topic_id:
            tail = self._topic_label(dialog_id, topic_id, acc)
        q = (query or "").strip()
        if q:
            tail = f"{tail}/{q}" if tail else q
        queue_name = chat or strings("queue")
        name = f"{queue_name}:{tail}" if tail else queue_name
        return name[:60]

    def _me(self, acc=0):
        try:
            return int(find_class("org.telegram.messenger.UserConfig").getInstance(int(acc)).getClientUserId())
        except Exception:
            return 0

    def _open_own_profile_playlist(self, alert=None):
        with tolerated():
            if alert is not None:
                alert.dismiss()
        self._open_queue_editor()
        def go():
            ed = getattr(self, "_editor", None)
            if ed is None:
                return
            with tolerated():
                ed._set_tab("library")
            with tolerated():
                ed._lib_go("pl", "profile")
            pl = self._pp_pl()
            tr = list(pl["tracks"]) if pl else []
            if tr:
                self._lib_play(ed.act, tr, "play", start=(tr[0]["i"], tr[0]["d"]), name=pl.get("name") or "Profile Playlist",
                               source_key=("playlist", "profile"))
        self._post(go, 450)

    def _own_profile_queue(self):
        k = self._queue_scope_key
        return bool(isinstance(k, (tuple, list)) and len(k) >= 2 and k[0] == "profile_music"
       and int(k[1]) == self._me(self._chat_account(None, None)))

    def _profile_activity_user_id(self, fragment, current=None):
        try:
            cls_name = str(fragment.getClass().getName()) if fragment is not None else ""
        except Exception:
            cls_name = ""
        if "ProfileActivity" not in cls_name:
            return 0
        for name in ("userId", "user_id", "user_id_long", "dialog_id", "peerId", "profileUserId"):
            val = self._read(fragment, name)
            if val is None:
                continue
            with tolerated():
                if hasattr(val, "user_id"):
                    val = val.user_id
                uid = int(val)
                if uid > 0:
                    return uid
        args = self._read(fragment, "arguments", "getArguments")
        with tolerated():
            if args is not None:
                for name in ("user_id", "userId"):
                    uid = int(args.getLong(name, 0) or args.getInt(name, 0) or 0)
                    if uid > 0:
                        return uid
        with tolerated():
            did = int(current.getDialogId()) if current is not None else 0
            if did > 0:
                return did
            if args is None or not (args.getLong("chat_id", 0) or args.getLong("user_id", 0)):
                return self._me(current.currentAccount if current is not None else 0)
        return 0

    def _name_queue(self, current, fragment, topic_id, query):
        if time.monotonic() < getattr(self, "_origin_pin_until", 0.0):
            return
        if self._profile_scope_sync():
            return
        self._lib_owned = None
        self._queue_cover_key = None
        with tolerated():
            did = int(current.getDialogId()) if current is not None else 0
            acc = self._chat_account(fragment, [current] if current is not None else None)
            profile_uid = self._profile_activity_user_id(fragment, current)
            if profile_uid:
                name = strings("my_profile") if profile_uid == self._me(acc) else self._dialog_title(profile_uid, acc)
                name = (name or strings("profile_playlist"))[:60]
                key = ("profile_music", int(profile_uid))
                if key == self._queue_scope_key and self._queue_name:
                    return
                self._origin_set(name, key)
                return
            key = (did, int(topic_id or 0), (query or "").strip().lower())
            if key == self._queue_scope_key and self._queue_name and self._queue_name != strings("queue"):
                return
            self._origin_set(self._auto_queue_name(did, topic_id, query, acc) if self._dialog_title(did, acc) else None, key)

    def _lib_data(self):
        if self._lib_cache is None:
            try:
                d = json.loads(self.get_setting("library_v1", "") or "{}")
            except Exception:
                d = {}
            if not isinstance(d, dict):
                d = {}
            d.setdefault("playlists", [])
            d.setdefault("chats", [])
            d.setdefault("friends", [])
            d.setdefault("last", None)
            d["playlists"] = [pl for pl in d["playlists"] if not (isinstance(pl, dict) and pl.get("id") == "last_queue")]
            try:
                default_account = int(find_class("org.telegram.messenger.UserConfig").selectedAccount)
            except Exception:
                default_account = 0
            for chat in d["chats"]:
                if isinstance(chat, dict):
                    chat.setdefault("a", default_account)
            for friend in d["friends"]:
                if isinstance(friend, dict):
                    friend.setdefault("a", default_account)
                    if "d" not in friend and "id" in friend:
                        friend["d"] = friend.get("id", 0)
            self._lib_cache = d
        return self._lib_cache

    def _lib_save(self):
        old_liked = getattr(self, "_liked_cache", None)
        self._liked_cache = None
        with tolerated():
            self.set_setting("library_v1", json.dumps(self._lib_data(), separators=(",", ":")))
        with tolerated():
            if old_liked is not None and self._liked_keys() != old_liked:
                run_on_ui_thread(self._liked_changed)
        with tolerated():
            self._pp_changed()

    def _lib_track(self, m):
        try:
            dur = int(m.getDuration())
        except Exception:
            dur = 0
        d = {"i": int(m.getId()), "d": int(m.getDialogId()),
       "t": _QueueEditor._title_of(m), "a": _QueueEditor._author_of(m), "s": dur}
        if self._pm_is_synth(m):
            d["pf"] = d["d"]
        return d

    def _lib_dicts(self, items):
        return [x if isinstance(x, dict) else self._lib_track(x) for x in items if x is not None]

    def _dl_pl(self, create=False):
        d = self._lib_data()
        for pl in d["playlists"]:
            if pl.get("id") == "downloaded":
                return pl
        if not create:
            return None
        pl = {"id": "downloaded", "name": "Downloaded Songs", "tracks": [], "created": int(time.time())}
        first = d["playlists"][0] if d["playlists"] else None
        at = 1 if first is not None and str(first.get("name", "")).strip().lower() == "liked songs" else 0
        d["playlists"].insert(at, pl)
        self._lib_save()
        return pl

    def _dl_merge(self, found, scanned=None, purge_stubs=False):
        pl = self._dl_pl(True)
        if pl is None:
            return
        fk = {(t["i"], t["d"]) for t in found}
        keep = []
        for t in pl["tracks"]:
            k = (t["i"], t["d"])
            if purge_stubs and t.get("stub") and not t.get("lf") and k not in fk:
                continue
            if purge_stubs and t.get("lf") and not self._dl_local_ok(t["lf"], bool(t.get("tg"))) \
          and k not in fk:
                continue
            if k not in fk and scanned is not None:
                if k in scanned:
                    continue
                m = dict.get(self._msg_cache, k)
                if m is not None and not self._is_downloaded(m):
                    continue
            keep.append(t)
        have = {(t["i"], t["d"]) for t in keep}
        keep += [t for t in found if (t["i"], t["d"]) not in have]
        if [(t["i"], t["d"]) for t in keep] != [(t["i"], t["d"]) for t in pl["tracks"]]:
            pl["tracks"] = keep
            self._lib_save()

    def _dl_scan(self, done):
        if self.__dict__.get("_dl_busy"):
            done()
            return
        self._dl_busy = True
        def work():
            out, seen = [], set()
            with tolerated():
                srcs = [self._chat_track_cache.get((int(c["d"]), int(c["t"])))
             for c in list(self._lib_data().get("chats", []))]
                srcs += list(self._friend_track_cache.values())
                for src in srcs:
                    for m in (src or ()):
                        k = self._msg_key(m)
                        if k is None:
                            continue
                        seen.add(k)
                        if self._is_downloaded(m):
                            out.append(self._lib_track(m))
            def fin():
                self._dl_busy = False
                with tolerated():
                    self._dl_merge(out, seen)
                done()
            try:
                run_on_ui_thread(fin)
            except Exception:
                self._dl_busy = False
        threading.Thread(target=work, daemon=True).start()

    def _local_meta(self, path):
        title = artist = ""
        dur = 0
        with tolerated():
            R = jclass("android.media.MediaMetadataRetriever")()
            try:
                R.setDataSource(str(path))
                title = str(R.extractMetadata(7) or "")
                artist = str(R.extractMetadata(2) or "")
                dur = int(int(R.extractMetadata(9) or 0) // 1000)
            finally:
                with tolerated():
                    R.release()
        if not title:
            title = os.path.splitext(os.path.basename(str(path)))[0]
        return title, artist, dur

    @staticmethod
    def _dl_local_ok(path, tagged):
        low = str(path).lower()
        if low.endswith((".oga", ".opus")):
            return False
        if low.endswith(".ogg") and not tagged:
            return False
        return True

    def _local_message(self, t):
        try:
            path = str(t.get("lf") or "")
            f = jclass("java.io.File")(path)
            if not path or not bool(f.exists()) or int(f.length()) <= 0:
                return None
            did, mid = int(t["d"]), int(t["i"])
            acc = int(self._chat_account(None, None))
            T = "org.telegram.tgnet.TLRPC$"
            tl = find_class(T + "TL_message")()
            tl.id = mid
            tl.date = int(int(f.lastModified()) // 1000)
            tl.message = ""
            with tolerated():
                tl.flags = int(getattr(tl, "flags", 0) or 0) | 768
            if did > 0:
                peer = find_class(T + "TL_peerUser")()
                peer.user_id = did
            else:
                peer = find_class(T + "TL_peerChannel")()
                peer.channel_id = -did
            tl.peer_id = peer
            doc = find_class(T + "TL_document")()
            doc.id = int(abs(hash((did, mid, path))) % (1 << 62))
            doc.size = int(f.length())
            doc.date = tl.date
            low = path.lower()
            doc.mime_type = ("audio/mpeg" if low.endswith((".mp3", ".mpga")) else
          "audio/flac" if low.endswith(".flac") else
          "audio/ogg" if low.endswith((".ogg", ".oga", ".opus")) else
          "audio/mp4" if low.endswith((".m4a", ".aac")) else "audio/mpeg")
            with tolerated():
                doc.file_reference = jarray(jbyte)(0)
            au = find_class(T + "TL_documentAttributeAudio")()
            au.voice = False
            au.title = str(t.get("t") or "")
            au.performer = str(t.get("a") or "")
            au.duration = int(t.get("s") or 0)
            with tolerated():
                au.flags = 3
            doc.attributes.add(au)
            fn = find_class(T + "TL_documentAttributeFilename")()
            fn.file_name = os.path.basename(path)
            doc.attributes.add(fn)
            media = find_class(T + "TL_messageMediaDocument")()
            media.document = doc
            tl.media = media
            tl.attachPath = path
            tl.dialog_id = did
            mo = find_class("org.telegram.messenger.MessageObject")(acc, tl, False, True)
            with tolerated():
                if not bool(mo.isMusic()):
                    return None
            return mo
        except Exception:
            return None

    def _dl_deep(self, done):
        if self.__dict__.get("_dl_deep_busy"):
            return
        self._dl_deep_busy = True
        def work():
            found, ok = [], False
            voice_dir = set()
            with tolerated():
                UC = find_class("org.telegram.messenger.UserConfig")
                FL = find_class("org.telegram.messenger.FileLoader")
                exts = (".mp3", ".m4a", ".flac", ".ogg", ".oga", ".opus", ".wav", ".aac", ".wma", ".mpga")
                files, dbs = [], []
                for acc in range(int(UC.MAX_ACCOUNT_COUNT)):
                    with tolerated():
                        if not bool(UC.getInstance(acc).isClientActivated()):
                            continue
                        dbs.append(FL.getInstance(acc).getFileDatabase())
                seen_dirs = set()
                for kind in (FL.MEDIA_DIR_DOCUMENT, FL.MEDIA_DIR_AUDIO):
                    with tolerated():
                        folder = FL.getDirectory(kind)
                        path = str(folder.getAbsolutePath())
                        if path in seen_dirs:
                            continue
                        seen_dirs.add(path)
                        for f in (folder.listFiles() or ()):
                            if str(f.getName()).lower().endswith(exts):
                                files.append(f)
                                if kind == FL.MEDIA_DIR_AUDIO:
                                    voice_dir.add(str(f.getAbsolutePath()))
                have = set()
                pl = self._dl_pl()
                for t in (pl["tracks"] if pl else ()):
                    if t.get("stub") and not t.get("lf"):
                        continue
                    have.add((t["i"], t["d"]))
                for f in files:
                    for db in dbs:
                        with tolerated():
                            meta = db.getFileDialogId(f, None)
                            if meta is None:
                                continue
                            did, mid = int(meta.dialogId), int(meta.messageId)
                            if not did or not mid:
                                continue
                            ok = True
                            if (mid, did) in have:
                                break
                            have.add((mid, did))
                            found.append({"i": mid, "d": did, "lf": str(f.getAbsolutePath())})
                            break
            def stage2():
                keep, local = [], []
                for t in found:
                    m = dict.get(self._msg_cache, (t["i"], t["d"])) or self._msg_cache.get((t["i"], t["d"]))
                    if m is not None and self._resolver.state((t["i"], t["d"])) == "ok":
                        keep.append(self._lib_track(m))
                    else:
                        local.append(t)
                def tag():
                    out = []
                    for t in local:
                        if t["lf"] in voice_dir:
                            continue
                        title, artist, dur = self._local_meta(t["lf"])
                        tagged = bool(artist) or title != os.path.splitext(os.path.basename(t["lf"]))[0]
                        if not self._dl_local_ok(t["lf"], tagged):
                            continue
                        out.append(dict(t, t=title, a=artist, s=dur, tg=1 if tagged else 0))
                    def fin():
                        self._dl_deep_busy = False
                        with tolerated():
                            self._dl_merge(keep + out, purge_stubs=ok)
                        done(len(keep) + len(out) if (ok or found) else -1)
                    try:
                        run_on_ui_thread(fin)
                    except Exception:
                        self._dl_deep_busy = False
                threading.Thread(target=tag, daemon=True).start()
            def fin1():
                if not found:
                    self._dl_deep_busy = False
                    with tolerated():
                        self._dl_merge([], purge_stubs=ok)
                    done(0 if ok else -1)
                    return
                self._resolver.request_tracks(
             [{"i": t["i"], "d": t["d"]} for t in found], silent=True, on_done=stage2)
            try:
                run_on_ui_thread(fin1)
            except Exception:
                self._dl_deep_busy = False
        threading.Thread(target=work, daemon=True).start()

    def _lib_pl(self, pid):
        for p in self._lib_data()["playlists"]:
            if p["id"] == pid:
                return p
        return None

    def _lib_minutes(self, tracks):
        return max(1, int(round(sum(int(t.get("s", 0)) for t in tracks) / 60.0))) if tracks else 0

    def _lib_create(self, name, items):
        seen, tracks = set(), []
        for t in self._lib_dicts(items):
            k = (t["i"], t["d"])
            if k not in seen:
                seen.add(k)
                tracks.append(t)
        d = self._lib_data()
        pl = {"id": f"p{int(time.time() * 1000)}{random.randint(100, 999)}", "name": (name or "").strip()[:60] or strings("playlist"),
       "tracks": tracks, "created": int(time.time())}
        d["playlists"].insert(0, pl)
        d["last"] = pl["id"]
        self._lib_save()
        self._request_library_refresh()
        return pl

    def _lib_append(self, pid, items):
        pl = self._lib_pl(pid)
        if pl is None:
            return 0
        have = {(t["i"], t["d"]) for t in pl["tracks"]}
        added = 0
        new = []
        for t in self._lib_dicts(items):
            k = (t["i"], t["d"])
            if k not in have:
                have.add(k)
                new.append(t)
                added += 1
        pl["tracks"][0:0] = new
        self._lib_data()["last"] = pid
        self._lib_save()
        self._request_library_refresh()
        return added

    def _lib_liked_playlist(self, create=False):
        data = self._lib_data()
        for playlist in data["playlists"]:
            if str(playlist.get("name", "")).strip().lower() == "liked songs":
                return playlist
        if not create:
            return None
        playlist = {
       "id": f"p{int(time.time() * 1000)}{random.randint(100, 999)}",
       "name": "Liked Songs",
       "tracks": [],
       "created": int(time.time()),
       }
        data["playlists"].insert(0, playlist)
        self._lib_save()
        return playlist

    def _liked_keys(self):
        cache = getattr(self, "_liked_cache", None)
        if cache is None:
            playlist = self._lib_liked_playlist(False)
            cache = set()
            for track in (playlist or {}).get("tracks", []):
                with tolerated():
                    cache.add((int(track.get("i", 0)), int(track.get("d", 0))))
            self._liked_cache = cache
        return cache

    def _liked_changed(self):
        ed = getattr(self, "_editor", None)
        if ed is not None:
            with tolerated():
                ed._refresh_liked_icons()

    def _is_track_liked(self, msg):
        if msg is None:
            return False
        try:
            return (int(msg.getId()), int(msg.getDialogId())) in self._liked_keys()
        except Exception:
            return False

    def _toggle_track_liked(self, msg):
        if msg is None:
            return False
        try:
            key = (int(msg.getId()), int(msg.getDialogId()))
            playlist = self._lib_liked_playlist(True)
            tracks = playlist.setdefault("tracks", [])
            for index, track in enumerate(tracks):
                if (int(track.get("i", 0)), int(track.get("d", 0))) == key:
                    del tracks[index]
                    self._lib_save()
                    self._liked_changed()
                    return False
            tracks.insert(0, self._lib_track(msg))
            self._lib_save()
            self._liked_changed()
            self._like_cache(msg)
            return True
        except Exception:
            self._bulletin(strings("couldnt_update_liked_songs"), error=True)
            return False

    def _like_cache(self, msg):
        with tolerated():
            key = self._msg_key(msg)
            if key:
                self._msg_cache[key] = msg
        def persist():
            with tolerated():
                if self._sstore.enabled():
                    self._sstore.add([msg])
        with tolerated():
            threading.Thread(target=persist, daemon=True, name="smq-like-cache").start()
        with tolerated():
            if not self._is_downloaded(msg):
                self._start_download(msg)

    def _lib_protected(self, pl):
        return pl is not None and (pl.get("id") in _LIB_DYN
       or str(pl.get("name", "")).strip().lower() == "liked songs")

    def _lib_delete(self, pid):
        if self._lib_protected(self._lib_pl(pid)):
            return
        d = self._lib_data()
        d["playlists"] = [p for p in d["playlists"] if p["id"] != pid]
        if d.get("last") == pid:
            d["last"] = d["playlists"][0]["id"] if d["playlists"] else None
        self._lib_save()

    def _lib_rename(self, pid, name):
        pl = self._lib_pl(pid)
        if pl is not None and (name or "").strip():
            pl["name"] = name.strip()[:60]
            self._lib_save()

    def _lib_sync_names(self, force=False):
        now = time.monotonic()
        if not force and now - self.__dict__.get("_names_t", -99.0) < 20.0:
            return False
        self._names_t = now
        changed = False
        with tolerated():
            d = self._lib_data()
            for c in d["chats"]:
                with tolerated():
                    did, tid, acc = int(c["d"]), int(c.get("t") or 0), int(c.get("a", 0) or 0)
                    if not self._dialog_title(did, acc) or (tid and not self._topic_title(did, tid, acc)):
                        continue
                    new = self._auto_queue_name(did, tid, None, acc)
                    if new and new != c.get("n"):
                        c["n"] = new
                        changed = True
            for f in d["friends"]:
                with tolerated():
                    did, acc = int(f.get("d", f.get("id", 0)) or 0), int(f.get("a", 0) or 0)
                    new = self._dialog_title(did, acc) if did > 0 else ""
                    if new and new != f.get("n"):
                        f["n"] = new
                        changed = True
            if changed:
                self._lib_save()
        return changed

    def _lib_add_chat(self, dialog_id, topic_id, name, account=0) -> bool:
        d = self._lib_data()
        for c in d["chats"]:
            if c["d"] == int(dialog_id) and c["t"] == int(topic_id or 0):
                c.setdefault("a", int(account))
                return False
        d["chats"].append({"d": int(dialog_id), "t": int(topic_id or 0),
       "n": name, "a": int(account)})
        self._artist_dirty = True
        self._lib_save()
        self._request_library_refresh()
        return True

    def _lib_remove_chat(self, dialog_id, topic_id):
        d = self._lib_data()
        d["chats"] = [c for c in d["chats"] if not (c["d"] == int(dialog_id) and c["t"] == int(topic_id or 0))]
        self._lib_save()
        try:
            self._chat_track_cache.forget((int(dialog_id), int(topic_id or 0)))
        except Exception:
            self._chat_track_cache.pop((int(dialog_id), int(topic_id or 0)), None)
        self._request_library_refresh()

    def _lib_prompt_new(self, act, default, items, after=None):
        def create(text):
            pl = self._lib_create(text or default, items)
            self._bulletin(strings("saved_n_n_tracks", pl['name'], len(pl['tracks'])))
            if after:
                after(pl)
        _ActionSheet(self, act)._prompt_text(strings("save_as_playlist"), default, strings("playlist_name"), create)

    def _lib_add_to(self, pid, items):
        added = self._lib_append(pid, items)
        pl = self._lib_pl(pid)
        name = pl["name"] if pl else "playlist"
        self._bulletin(strings("added_n_tracks_to_n", added, name) if added
       else strings("nothing_new_to_add_to_n", name), error=not added)

    def _lib_add_to_sheet(self, act, get_items, default_name=strings("playlist"), subtitle="",
    exclude=None, need_active=False, end_of_queue=True):
        options = []
        if end_of_queue:
            options += [
          (strings("end_of_queue"), "", False,
          lambda: get_items(lambda its: self._lib_queue_items(act, its, "end", need_active))),
          None,
          ]
        options.append(
       (strings("new_playlist"), "", False,
       lambda: get_items(lambda its: self._lib_prompt_new(act, default_name, its))))
        pls = [p for p in self._lib_data()["playlists"] if p["id"] != exclude and p["id"] != "downloaded"]
        if pls:
            options.append(None)
            for p in pls:
                options.append((_pln(p["name"]), strings("n_tracks", len(p['tracks'])), False,
             (lambda pid=p["id"]: get_items(lambda its: self._lib_add_to(pid, its))),
             "", None, None, False, lambda sh, cd, pl=p: sh._opt_tile(pl, cd)))
        _ActionSheet(self, act).show_sheet(strings("add_to"), subtitle, options)

    def _lib_queue_items(self, act, items, mode, need_active=False):
        if not items:
            return
        if isinstance(items[0], dict):
            self._lib_play(act, items, mode)
        else:
            self._lib_play_msgs(items, mode, keep_order=False, need_active=need_active)

    def _lib_cache_queue(self):
        with tolerated():
            mc = self._get_mc()
            pl = self._get_playlist(mc) if mc is not None else None
            for i in range(int(pl.size()) if pl is not None else 0):
                m = pl.get(i)
                k = self._msg_key(m) if m is not None else None
                if k:
                    self._msg_cache[k] = m

    def _pm_profile_fetch(self, uid, acc, on_done):
        friend = next((f for f in self._lib_data().get("friends", [])
       if int(f.get("d", f.get("id", 0)) or 0) == uid), None)
        h = int(friend.get("h", 0) or 0) if friend else 0
        if friend:
            acc = int(friend.get("a", acc) or 0)
        def work():
            msgs = []
            with tolerated():
                inp = self._pm_input_user(uid, h, acc)
                docs = self._pm_get_saved_music(acc, inp, lambda: False, lambda _t: None)
                for index, doc in enumerate(docs):
                    with tolerated():
                        m = self._pm_synthetic_music_message(acc, uid, doc, index)
                        if m is None:
                            continue
                        with tolerated():
                            if not bool(m.isMusic()):
                                continue
                        msgs.append(m)
            def fin():
                on_done(msgs)
            try:
                run_on_ui_thread(fin)
            except Exception:
                fin()
        threading.Thread(target=work, daemon=True).start()

    def _lib_resolve(self, act, tracks, on_done):
        self._lib_resolve_chats(act, tracks, on_done)

    def _lib_resolve_chats(self, act, tracks, on_done):
        self._lib_cache_queue()
        keys = [(int(t["i"]), int(t["d"])) for t in tracks]
        self._resolver.request_tracks(
       tracks, on_done=lambda: on_done([self._msg_cache.get(k) for k in keys]))

    def _lib_fast_jump(self, keys, mode, start, shuffle, name, source_key, msgs=None):
        if mode != "play" or self._offline_active():
            return False
        try:
            scope = source_key or ("library", name or strings("library"))
            if self._queue_scope_key is None or self._src_canon(self._queue_scope_key) != self._src_canon(scope):
                return False
            if start is None or shuffle:
                return self._lib_fast_restart(keys, msgs, start, shuffle)
            wanted = (int(start[0]), int(start[1]))
            m = None
            for x in (msgs or ()):
                if x is not None and self._msg_key(x) == wanted:
                    m = x
                    break
            if m is None:
                m = self._msg_cache.get(wanted)
            if m is None or not self._jump_in_queue(m):
                return False
            with tolerated():
                self._lib_update_playing_icons_now(wanted)
            return True
        except Exception:
            return False

    def _lib_fast_restart(self, keys, msgs, start, shuffle):
        if self.__dict__.get("_queue_build_state") is not None:
            return False
        mc = self._get_mc()
        pl = self._get_playlist(mc) if mc is not None else None
        if pl is None or int(pl.size()) == 0:
            return False
        if keys is None:
            keys = [self._msg_key(x) for x in (msgs or ()) if x is not None]
        keys = [k for k in keys if k is not None]
        if not keys:
            return False
        inq = {}
        for i in range(int(pl.size())):
            m = pl.get(i)
            k = self._msg_key(m) if m is not None else None
            if k is not None:
                inq[k] = m
        if any(k not in inq for k in keys):
            return False
        if start is not None:
            pick = (int(start[0]), int(start[1]))
        elif shuffle:
            cur = None
            with tolerated():
                cm = mc.getPlayingMessageObject()
                cur = self._msg_key(cm) if cm is not None else None
            pool = [k for k in keys if k != cur] or keys
            pick = random.choice(pool)
        else:
            pick = keys[0]
        if pick not in inq:
            return False
        if shuffle:
            self._enable_shuffle()
        if not self._jump_in_queue(inq[pick]):
            return False
        with tolerated():
            self._lib_update_playing_icons_now(pick)
        return True

    def _pick_forget(self):
        with tolerated():
            ed = getattr(self, "_editor", None)
            if ed is not None:
                ed._pick_clear()

    def _lib_update_playing_icons_now(self, key):
        ed = getattr(self, "_editor", None)
        if ed is not None:
            ed._lib_update_playing_icons(key, False)
            self._post(ed._mini_update, 0)

    def _lib_play(self, act, tracks, mode="play", start=None, shuffle=False, name=None, source_key=None):
        with tolerated():
            from ..compat import set_private_field
            mc0 = self._get_mc()
            if mc0 is not None and getattr(mc0, "currentSavedMusicList", None) is not None:
                set_private_field(mc0, "currentSavedMusicList", None)
        with tolerated():
            self._pp_log("PLAY requested: mode=%s n=%d name=%s | push_busy=%s pull_busy=%s resolver_active=%s pf_active=%s build=%s" % (
                mode, len(tracks), name, self._pp_busy, self._pp_pull_busy, getattr(self._resolver, "active", "?"),
                getattr(self._resolver, "pf_active", "?"), self.__dict__.get("_queue_build_state") is not None))
        keys = [(int(t["i"]), int(t["d"])) for t in tracks]
        if mode == "play" and start is not None:
            with tolerated():
                ed = getattr(self, "_editor", None)
                m0 = self._msg_cache.get((int(start[0]), int(start[1])))
                if ed is not None and m0 is not None:
                    ed._pick_show(m0)
        if self._lib_fast_jump(keys, mode, start, shuffle, name, source_key):
            return
        if mode == "play" and keys:
            with tolerated():
                self._queue_expected_count = len(keys)
                self._queue_hydration_open = False
                if name:
                    self._origin_set(name, self._queue_scope_key)
                ed = getattr(self, "_editor", None)
                if ed is not None:
                    ed._update_title()
        def go(msgs):
            have = [m for m in msgs if m is not None]
            missing = len(keys) - len(have)
            if not have:
                self._queue_expected_count = None
                self._pick_forget()
                if any(k in self._resolver.failed for k in keys):
                    self._bulletin(strings("couldnt_load_those_tracks_check_your"), error=True)
                else:
                    self._bulletin(strings("those_tracks_arent_available_any_more"), error=True)
                return
            if missing:
                gone = sum(1 for k, m in zip(keys, msgs) if m is None and k in self._msg_missing)
                if gone:
                    self._bulletin(strings("n_tracks_unavailable_deleted_or_too", gone))
                elif missing - gone:
                    n = missing - gone
                    self._bulletin(strings("n_tracks_couldnt_be_loaded_check", n))
            self._lib_play_msgs(have, mode, start, shuffle, name, source_key=source_key, _jump_tried=True)
        cache, gone = self._msg_cache, self._msg_missing
        unresolved = any(k not in cache and k not in gone for k in keys)
        if unresolved:
            self._lib_cache_queue()
            unresolved = any(k not in cache and k not in gone for k in keys)
        for k in keys:
            if k in self._resolver.failed:
                self._resolver.failed.discard(k)
                self._resolver.tries.pop(k, None)
        if mode == "play" and keys and unresolved:
            self._lib_play_instant(tracks, keys, mode, start, shuffle, name, source_key)
            return
        if unresolved:
            self._bulletin(strings("loading_songs"))
        self._lib_resolve(act, tracks, go)

    def _cancel_progressive_queue(self):
        token = int(self.__dict__.get("_queue_build_token", 0)) + 1
        self._queue_build_token = token
        state = self.__dict__.pop("_queue_build_state", None)
        self._queue_expected_count = None
        if state is not None:
            with tolerated():
                self._activity_status(state.get("status_key"), None)
        return token

    def _lib_play_msgs_progressive(self, msgs, start=None, name=None, source_key=None, cover=None, start_index=None,
    shuffle=False):
        try:
            total = int(len(msgs))
        except Exception:
            return False
        shuffle_on, rev = self._read_order()
        if total < 128:
            return False
        shuf = bool(shuffle or shuffle_on)
        if shuf:
            self._enable_shuffle()
            if start is None and start_index is None:
                start_index = random.randrange(min(total, _PROGRESSIVE_SHUFFLE_POOL))
        token = self._cancel_progressive_queue()
        status_key = ("queue_build", token)
        state = {"token": token, "total": total, "loaded": 0, "visible": [None] * total,
       "keys": set(), "status_key": status_key, "rev": bool(rev),
       "vkeys": [None] * total, "size": 0, "pending": [], "first_msg": None,
       "first_key": None, "scope": source_key, "name": name or strings("library"),
       "before_key": None, "before_msg": None, "shuf": shuf}
        self._queue_build_state = state
        self._queue_expected_count = total
        with tolerated():
            self._origin_set(name or strings("library"), source_key if source_key is not None else self._queue_scope_key)
        def msg_key(msg):
            try:
                return self._msg_key(msg)
            except Exception:
                return None
        def ui_sync(fn, timeout=30.0):
            event = threading.Event()
            result = {"ok": False}
            def wrapped():
                try:
                    fn()
                    result["ok"] = True
                except Exception:
                    pass
                finally:
                    event.set()
            try:
                run_on_ui_thread(wrapped)
            except Exception:
                return False
            if not event.wait(timeout):
                return False
            return bool(result["ok"])
        def current_token():
            return (int(self.__dict__.get("_queue_build_token", -1)) == token and
          self.__dict__.get("_queue_build_state") is state)
        def find_start():
            wanted = tuple(start) if start is not None else None
            if start_index is not None:
                with tolerated():
                    hinted = int(start_index)
                    if 0 <= hinted < total:
                        candidate = msgs[hinted]
                        if candidate is not None and (wanted is None or msg_key(candidate) == wanted):
                            return hinted, candidate
            if wanted is not None:
                rows = getattr(msgs, "rows", None)
                if rows is not None:
                    with tolerated():
                        for i, row in enumerate(rows):
                            if int(row.get("i", 0) or 0) == int(wanted[0]) and \
                      int(row.get("d", 0) or 0) == int(wanted[1]):
                                candidate = msgs[i]
                                if candidate is not None:
                                    return i, candidate
                objs = getattr(msgs, "_objs", None)
                if objs is not None:
                    for i, candidate in enumerate(objs):
                        if candidate is not None and msg_key(candidate) == wanted:
                            return i, candidate
                for i in range(total):
                    try:
                        candidate = msgs[i]
                    except Exception:
                        continue
                    if candidate is not None and msg_key(candidate) == wanted:
                        return i, candidate
            for i in range(total):
                try:
                    candidate = msgs[i]
                except Exception:
                    continue
                if candidate is not None:
                    return i, candidate
            return None, None
        def refresh_editor(force=False):
            editor = getattr(self, "_editor", None)
            if editor is None:
                del state["pending"][:]
                return
            with tolerated():
                now = time.monotonic()
                loaded = int(state.get("loaded", 0))
                last_loaded = int(state.get("last_ui_loaded", 0))
                last_time = float(state.get("last_ui_refresh", 0.0))
                if not force and loaded - last_loaded < 64 and now - last_time < 0.12:
                    return
                state["last_ui_loaded"] = loaded
                state["last_ui_refresh"] = now
                if force:
                    editor._set_progressive_items(state)
                else:
                    editor._progressive_flush(state)
                editor._lib_progress_refresh()
        def abandon(note=None, reload_ui=False):
            if not current_token():
                return
            self._queue_build_state = None
            self._queue_expected_count = None
            self._queue_build_token = int(self.__dict__.get("_queue_build_token", 0)) + 1
            self._activity_status(status_key, None)
            editor = getattr(self, "_editor", None)
            if editor is not None:
                with tolerated():
                    if reload_ui:
                        editor._reload()
                    else:
                        editor._update_title()
            if note:
                self._bulletin(note)
        def start_first(index, first, window=()):
            if not current_token():
                return
            state["start_index"] = int(index)
            state["visible"][int(index)] = first
            key = msg_key(first)
            state["vkeys"][int(index)] = key
            state["first_key"] = key
            state["first_msg"] = first
            state["keys"].add(key) if key is not None else None
            state["loaded"] = 1
            for widx, wmsg in window:
                wkey = msg_key(wmsg)
                state["visible"][int(widx)] = wmsg
                state["vkeys"][int(widx)] = wkey
                if wkey is not None:
                    state["keys"].add(wkey)
                state["loaded"] += 1
            if window:
                state["before_msg"] = window[0][1]
                state["before_key"] = msg_key(window[0][1])
            self._lib_play_msgs([w[1] for w in window] + [first], "play", start=key, name=name,
          source_key=source_key, cover=cover, _progressive=True)
            if not current_token():
                return
            try:
                mc = self._get_mc()
                pl = self._get_playlist(mc) if mc is not None else None
                if pl is None or self._index_of(pl, int(first.getId()), int(first.getDialogId())) < 0:
                    raise RuntimeError("first track wasn't installed in the player")
            except Exception:
                self._queue_build_state = None
                self._queue_expected_count = None
                self._activity_status(status_key, None)
                return
            state["size"] = int(pl.size())
            self._lib_owned = (state["keys"], self._queue_scope_key)
            refresh_editor(force=True)
        def apply_batch(pairs, region):
            if not current_token():
                return False
            mc = self._get_mc()
            playlist = self._get_playlist(mc) if mc is not None else None
            if mc is None or playlist is None:
                raise RuntimeError("player playlist disappeared")
            if int(playlist.size()) < int(state.get("size", 0)):
                abandon(strings("queue_changed_stopped_loading_the_rest"), reload_ui=True)
                return False
            try:
                first_present = int(playlist.indexOf(state["first_msg"])) >= 0
            except Exception:
                first_present = True
            if not first_present:
                abandon()
                return False
            messages = [m for _idx, m in pairs if m is not None]
            if not messages:
                return True
            insert_front = ((not rev and region == "after") or (rev and region == "before"))
            ordered = list(reversed(messages)) if insert_front or region == "before" else list(messages)
            if insert_front:
                insert_at = 0
            elif not rev and region == "before":
                anchor = -1
                a_msg = state.get("before_msg") or state["first_msg"]
                a_key = state.get("before_key") or state.get("first_key")
                try:
                    anchor = int(playlist.indexOf(a_msg))
                except Exception:
                    anchor = -1
                if anchor < 0 and a_key is not None:
                    anchor = self._index_of(playlist, int(a_key[0]), int(a_key[1]))
                insert_at = max(0, anchor + 1) if anchor >= 0 else int(playlist.size())
            else:
                insert_at = int(playlist.size())
            arr = ArrayList()
            for message in ordered:
                arr.add(message)
            try:
                playlist.addAll(int(insert_at), arr)
            except Exception:
                for offset, message in enumerate(ordered):
                    playlist.add(int(insert_at) + offset, message)
            for message in messages:
                self._map_put(mc, message)
            if insert_front:
                cur = self._current_index(mc)
                if cur < 0:
                    cur = self._index_of(playlist, int(state["first_key"][0]), int(state["first_key"][1]))
                if cur >= 0:
                    self._set_int_field(mc, "currentPlaylistNum", cur + len(messages))
            mkeys = {}
            for idx, message in pairs:
                if message is None:
                    continue
                k = msg_key(message)
                mkeys[id(message)] = k
                if k is not None:
                    state["keys"].add(k)
                if 0 <= idx < len(state["visible"]):
                    state["visible"][idx] = message
                    state["vkeys"][idx] = k
            if rev:
                where, disp = (("front", list(reversed(messages))) if region == "before"
             else ("end", list(messages)))
            else:
                where, disp = (("before_first", list(messages)) if region == "before"
             else ("end", list(messages)))
            state["pending"].append((where, [(m, mkeys.get(id(m))) for m in disp]))
            state["loaded"] += len(messages)
            state["size"] = int(playlist.size())
            if state.get("shuf"):
                if (int(playlist.size()) - int(state.get("shuf_synced", 0)) >= 512
             or not state.get("shuf_synced")):
                    self._shuffle_sync(mc, playlist)
                    state["shuf_synced"] = int(playlist.size())
            refresh_editor()
            return True
        def wait_if_dragging():
            while current_token():
                ed = getattr(self, "_editor", None)
                if ed is None or getattr(ed, "drag", None) is None:
                    return
                time.sleep(0.05)
        def run_segment(indices, region):
            batch = []
            for idx in indices:
                if not current_token():
                    return False
                if idx == state.get("start_index"):
                    continue
                try:
                    message = msgs[idx]
                except Exception:
                    message = None
                if message is None:
                    continue
                batch.append((idx, message))
                if len(batch) >= 64:
                    current = list(batch)
                    batch = []
                    wait_if_dragging()
                    if not ui_sync(lambda b=current, r=region: apply_batch(b, r)):
                        return False
                    time.sleep(0.01)
            if batch:
                current = list(batch)
                wait_if_dragging()
                if not ui_sync(lambda b=current, r=region: apply_batch(b, r)):
                    return False
            return True
        def fail_build(message=None):
            def fail_ui():
                if not current_token():
                    return
                self._queue_build_state = None
                self._queue_expected_count = None
                self._activity_status(status_key, None)
                editor = getattr(self, "_editor", None)
                if editor is not None:
                    with tolerated():
                        editor._update_title()
                if message:
                    self._bulletin(message, error=True)
            ui_sync(fail_ui, timeout=5.0)
        def work():
            try:
                index, first = find_start()
                if first is None or index is None:
                    fail_build(strings("no_available_tracks_to_play"))
                    return
                window = []
                if not shuf:
                    for widx in range(max(0, index - _PROGRESSIVE_PREV_TRACKS), index):
                        try:
                            wm = msgs[widx]
                        except Exception:
                            wm = None
                        if wm is not None:
                            window.append((widx, wm))
                w0 = window[0][0] if window else index
                if not ui_sync(lambda: start_first(index, first, window)):
                    fail_build(strings("couldnt_start_the_queue"))
                    return
                if not current_token():
                    return
                if rev:
                    if not run_segment(range(w0 - 1, -1, -1), "before"):
                        fail_build(strings("queue_loading_stopped"))
                        return
                    if not run_segment(range(index + 1, total), "after"):
                        fail_build(strings("queue_loading_stopped"))
                        return
                else:
                    if not run_segment(range(index + 1, total), "after"):
                        fail_build(strings("queue_loading_stopped"))
                        return
                    if not run_segment(range(0, w0), "before"):
                        fail_build(strings("queue_loading_stopped"))
                        return
                def finish_ui():
                    if not current_token():
                        return
                    mc = self._get_mc()
                    playlist = self._get_playlist(mc) if mc is not None else None
                    actual = int(playlist.size()) if playlist is not None else state["loaded"]
                    self._queue_build_state = None
                    self._queue_expected_count = None
                    self._activity_status(status_key, None)
                    with tolerated():
                        if mc is not None and playlist is not None:
                            if state.get("shuf"):
                                self._shuffle_sync(mc, playlist)
                            else:
                                self._finish_bulk_edit(mc, playlist)
                    editor = getattr(self, "_editor", None)
                    if editor is not None:
                        with tolerated():
                            editor._progressive_flush(state)
                            editor._update_title()
                            editor._mini_update()
                    self._origin_set(name or strings("library"), source_key if source_key is not None else self._queue_scope_key)
                    self._lib_owned = (frozenset(state["keys"]), self._queue_scope_key)
                    if actual < total:
                        pass
                if not ui_sync(finish_ui):
                    fail_build(strings("queue_finished_but_the_ui_couldnt"))
            except Exception:
                fail_build(strings("queue_loading_stopped"))
        threading.Thread(target=work, daemon=True, name="smq-progressive-queue").start()
        return True

    def _pick_feedback(self, msgs, start, start_index):
        ed = getattr(self, "_editor", None)
        if ed is None or getattr(ed, "root", None) is None:
            return
        m0 = None
        if start_index is not None and 0 <= int(start_index) < len(msgs):
            m0 = msgs[int(start_index)]
        if m0 is None and start is not None:
            k = (int(start[0]), int(start[1]))
            m0 = self._msg_cache.get(k)
            if m0 is None and len(msgs) <= 200:
                for m in msgs:
                    if m is not None and self._msg_key(m) == k:
                        m0 = m
                        break
        if m0 is None and start is None and start_index is None:
            m0 = next((m for m in msgs if m is not None), None)
        if m0 is not None and ed._key(m0) != ed.__dict__.get("_pick_key"):
            ed._pick_show(m0)

    def _lib_play_msgs(self, msgs, mode="play", start=None, shuffle=False, name=None,
    keep_order=True, need_active=False, source_key=None, quiet=False, cover=None,
    _progressive=False, _start_index=None, _offline_done=False, _jump_tried=False):
        if mode == "play" and not shuffle and not _progressive and not _offline_done:
            with tolerated():
                self._pick_feedback(msgs, start, _start_index)
        if (not _progressive and not _offline_done and not _jump_tried and mode == "play"
       and self._lib_fast_jump(None, mode, start, shuffle, name, source_key, msgs)):
            return
        if (not _progressive and not _offline_done and mode == "play"
       and self._offline_active()):
            src = [m for m in msgs if m is not None]
            def find_first():
                begin = 0
                if start is not None:
                    for i, m in enumerate(src):
                        if self._msg_key(m) == tuple(start):
                            begin = i
                            break
                for i in list(range(begin, len(src))) + list(range(0, begin)):
                    if self._is_downloaded(src[i]):
                        return i
                return -1
            def run_offline(idx):
                if idx < 0:
                    self._bulletin(strings("offline_mode_no_downloaded_tracks_to"), error=True)
                    return
                self._lib_play_msgs(src, mode, self._msg_key(src[idx]), shuffle, name, keep_order,
             need_active, source_key, quiet, cover, False,
             idx if len(src) == len(msgs) else None, True)
            if len(src) <= 400:
                run_offline(find_first())
            else:
                def scan_work():
                    try:
                        idx = find_first()
                    except Exception:
                        idx = -1
                    run_on_ui_thread(lambda: run_offline(idx))
                threading.Thread(target=scan_work, daemon=True).start()
            return
        if not _progressive:
            try:
                n = int(len(msgs))
            except Exception:
                n = 0
            if mode == "play" and n >= 128:
                if self._lib_play_msgs_progressive(
             msgs, start=start, name=name, source_key=source_key, cover=cover,
             start_index=_start_index, shuffle=shuffle):
                    return
            if mode not in ("next", "end"):
                self._cancel_progressive_queue()
        msgs = [m for m in msgs if m is not None]
        if not msgs:
            self._bulletin(strings("nothing_to_play"), error=True)
            return
        mc = self._get_mc()
        if mc is None:
            self._bulletin(strings("player_not_available"), error=True)
            return
        pl = self._get_playlist(mc)
        active = pl is not None and int(pl.size()) > 0 and self._playing_key(mc) is not None
        if mode in ("next", "end") and not active and need_active:
            self._bulletin(strings("start_playing_a_track_first"), error=True)
            return
        if mode in ("next", "end") and active:
            added = self._queue_bulk_insert(mc, pl, msgs, next_=(mode == "next"), keep_order=keep_order)
            where = strings("next") if mode == "next" else strings("to_the_end_of_the_queue")
            if not quiet:
                self._bulletin(strings("added_n_tracks_n", added, where) if added
             else strings("already_in_the_queue"), error=not added)
            ed = getattr(self, "_editor", None)
            if ed is not None and added:
                with tolerated():
                    if mode == "end":
                        ed._append_tail()
                    else:
                        ed._reload()
            return
        if shuffle:
            self._enable_shuffle()
        seq = list(msgs)
        first = random.choice(seq[:_PROGRESSIVE_SHUFFLE_POOL]) if shuffle and start is None else seq[0]
        if start is not None:
            for m in seq:
                if self._msg_key(m) == tuple(start):
                    first = m
                    break
        _shuffle_on, rev = self._read_order()
        stored = seq if rev else seq[::-1]
        al = ArrayList()
        for m in stored:
            al.add(m)
        did = int(first.getDialogId())
        started = False
        prev_filter = getattr(self, "_active_filter", None)
        prev_id = (self._queue_name, self._queue_scope_key, self._queue_cover_key, self._lib_owned)
        new_name = name or strings("library")
        new_scope = source_key or ("library", new_name)
        self._origin_set(new_name, new_scope, cover=cover,
       owned=(frozenset(k for k in (self._msg_key(m) for m in stored) if k is not None), _deep_tuple(new_scope)))
        self._lock_playlist("library")
        previous_remote = bool(getattr(self, "_allow_remote", False))
        previous_bypass = bool(getattr(self, "_lib_bypass", False))
        self._allow_remote = True
        self._lib_bypass = True
        try:
            for args in ((al, first, did, False, None), (al, first, did, 0), (al, first, did)):
                with tolerated():
                    mc.setPlaylist(*args)
                    started = True
                    break
        finally:
            self._allow_remote = previous_remote
            self._lib_bypass = previous_bypass
        def queue_matches():
            try:
                current_pl = self._get_playlist(mc)
                if current_pl is None:
                    return False
                if int(current_pl.size()) != len(stored):
                    return False
                wanted_list = [self._msg_key(m) for m in stored]
                actual_list = [self._msg_key(current_pl.get(i))
             for i in range(int(current_pl.size()))]
                return bool(wanted_list) and actual_list == wanted_list
            except Exception:
                return False
        if not started or not queue_matches():
            try:
                current_pl = self._get_playlist(mc)
                if current_pl is None:
                    raise RuntimeError("playlist unavailable")
                current_pl.clear()
                pmap = get_private_field(mc, "playlistMap")
                if pmap is not None:
                    pmap.clear()
                for item in stored:
                    current_pl.add(item)
                    self._map_put(mc, item)
                first_index = self._index_of(current_pl, int(first.getId()), int(first.getDialogId()))
                if first_index < 0:
                    raise RuntimeError("selected library track missing from rebuilt queue")
                self._set_int_field(mc, "currentPlaylistNum", first_index)
                if _shuffle_on:
                    with tolerated():
                        mc.buildShuffledPlayList()
                        self._set_int_field(mc, "currentPlaylistNum", 0)
                started = queue_matches()
            except Exception:
                started = False
        def rollback(text):
            self._active_filter = prev_filter
            self._origin_set(prev_id[0], prev_id[1], cover=prev_id[2], owned=prev_id[3])
            self._bulletin(text, error=True)
        if not started:
            rollback(strings("couldnt_build_the_library_queue_playback"))
            return
        previous_remote = bool(getattr(self, "_allow_remote", False))
        previous_bypass = bool(getattr(self, "_lib_bypass", False))
        self._allow_remote = True
        self._lib_bypass = True
        try:
            mc.playMessage(first)
        except Exception:
            rollback(strings("queue_built_but_playback_couldnt_start"))
            return
        finally:
            self._allow_remote = previous_remote
            self._lib_bypass = previous_bypass
        self._lock_playlist("library")
        if source_key and isinstance(source_key, (tuple, list)) and len(source_key) >= 2 and source_key[0] == "playlist":
            playlist = self._lib_pl(source_key[1])
            if playlist is not None:
                playlist["last_played"] = int(time.time())
                self._lib_save()
        self._origin_set(new_name, new_scope)
        if not _progressive:
            self._sync_editor_after_library_start()
        with tolerated():
            editor = getattr(self, "_editor", None)
            if editor is not None:
                editor._update_title()
