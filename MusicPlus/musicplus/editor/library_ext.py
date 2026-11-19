import json
import random
import re
import threading
import time
from ..compat import find_class, jclass, run_on_ui_thread
from elyx import strings
from ..helpers import _pln
from ..helpers import _http_stream, _http_text
from ..android import _cls, _mix, _layoutchg_proxy
from ..stores import _LazyTracks, _ProgressiveChatTracks
from ..safe import tolerated


class _QueueEditorLibraryExt:
    _ALBUM_SINGLES = "\u0001singles"
    _ALBUM_OTHER = "\u0001other"

    @staticmethod
    def _album_norm(title, artist=""):
        t = str(title or "").casefold().strip()
        an = re.sub(r"[\W_]+", "", str(artist or "").casefold())
        if an and " - " in t:
            head, tail = t.split(" - ", 1)
            if re.sub(r"[\W_]+", "", head) == an:
                t = tail
        t = re.sub(r"\s*[\(\[][^\)\]]*\b(?:feat|ft|featuring|with|prod|explicit|remaster(?:ed)?|bonus)\b[^\)\]]*[\)\]]", "", t)
        t = re.sub(r"\s+-\s+(?:\d{4}\s+)?remaster(?:ed)?.*$", "", t)
        t = re.sub(r"\s+(?:feat|ft)\.?\s.*$", "", t)
        return re.sub(r"[\W_]+", "", t)

    def _lib_itunes_albums(self, a, want):
        import urllib.parse
        q_ = urllib.parse.quote
        name = str(a.get("n") or "").strip()
        first = re.split(r"\s*(?:,|&|/|;|\bfeat\.?|\bft\.?|\bwith\b)\s*", name, flags=re.I)[0].strip() or name
        nn = lambda t: re.sub(r"[\W_]+", "", str(t).casefold())
        reached = False
        songs = []
        def get(url):
            return json.loads(_http_text(url)).get("results") or []
        aid = None
        for q in dict.fromkeys(x for x in (name, first) if x):
            try:
                res = get("https://itunes.apple.com/search?media=music&entity=musicArtist&limit=5&term=" + q_(q))
                reached = True
            except Exception:
                continue
            hit = next((r for r in res if nn(r.get("artistName", "")) == nn(q)), None)
            if hit and hit.get("artistId"):
                aid = hit["artistId"]
                break
        if aid:
            with tolerated():
                res = get(f"https://itunes.apple.com/lookup?id={aid}&entity=song&limit=200")
                reached = True
                songs += [r for r in res if r.get("wrapperType") == "track"]
        have = {self._album_norm(x.get("trackName"), name) for x in songs}
        for t, raw in [(t, r) for t, r in want.items() if t not in have][:60]:
            try:
                res = get("https://itunes.apple.com/search?media=music&entity=song&limit=10&term=" +
             q_(f"{first} {raw}"))
                reached = True
            except Exception:
                continue
            songs += [r for r in res if nn(first) and nn(first) in nn(r.get("artistName", ""))]
        if not reached:
            return None
        cands = {}
        for x in songs:
            t = self._album_norm(x.get("trackName"), name)
            cn = str(x.get("collectionName") or "").strip()
            if t in want and cn and x.get("collectionId"):
                cands.setdefault(t, {})[x["collectionId"]] = x
        def clean(n):
            n = re.sub(r"\s*[\(\[][^\)\]]*\b(?:deluxe|expanded|remaster(?:ed)?|international|bonus|"
          r"anniversary|special|edition|version)\b[^\)\]]*[\)\]]", "", n, flags=re.I)
            return re.sub(r"\s+", " ", n).strip() or n
        def rank(x):
            n = str(x.get("collectionName") or "")
            single = bool(re.search(r"-\s*(single|ep)\s*$", n, re.I))
            comp = bool(re.search(r"greatest hits|best of|\bhits\b|collection|compilation|essentials|"
          r"anthology|karaoke|tribute|\bsingles\b|playlist|sessions|b-sides|rarities",
          n, re.I))
            live = bool(re.search(r"\blive\b|unplugged|\bat the\b|in concert", n, re.I))
            tiny = int(x.get("trackCount") or 0) < 5
            return (comp, live, single, tiny, str(x.get("releaseDate") or "9999"), len(n))
        found = {}
        am, tn = a.setdefault("am", {}), a.setdefault("tn", {})
        for t, group in cands.items():
            best = min(group.values(), key=rank)
            cname = clean(str(best.get("collectionName")).strip())
            found[t] = cname
            with tolerated():
                if best.get("trackNumber"):
                    tn[t] = [int(best.get("discNumber") or 1), int(best["trackNumber"])]
                e = am.setdefault(cname, {})
                art = best.get("artworkUrl100")
                if art and not e.get("art"):
                    e["art"] = art.replace("100x100bb", "400x400bb")
                cnt = int(best.get("trackCount") or 0)
                if cnt and (not e.get("cnt") or cnt < e["cnt"]):
                    e["cnt"] = cnt
        return found

    def _lib_artist_albums(self, a, msgs):
        p = self.p
        if a.get("alv") != 3:
            a["al"], a["alv"], a["am"], a["tn"], a["nf"] = {}, 3, {}, {}, {}
            p.__dict__.setdefault("_album_tried", {}).pop(a["k"], None)
        cache = a.setdefault("al", {})
        titles = {}
        for m in msgs:
            titles[self._lib_key(m)] = (self._album_norm(self._title_of(m), a.get("n", "")), self._title_of(m))
        nf = a.setdefault("nf", {})
        now = time.time()
        tn = a.setdefault("tn", {})
        want = {t: raw for t, raw in titles.values()
       if t and (t not in cache or t not in tn) and now - nf.get(t, 0) > 2592000}
        k = a["k"]
        busy = p.__dict__.setdefault("_album_busy", set())
        tried = p.__dict__.setdefault("_album_tried", {}).setdefault(k, set())
        todo = {t: raw for t, raw in want.items() if t not in tried}
        if todo and k not in busy and p._net_ok():
            busy.add(k)
            tried.update(todo)
            def work():
                found = None
                with tolerated():
                    found = self._lib_itunes_albums(a, todo)
                def done():
                    busy.discard(k)
                    if found is not None:
                        hit = {t: found[t] for t in todo if found.get(t)}
                        for t in todo:
                            if t not in tn:
                                nf[t] = int(time.time())
                        cache.update({t: v for t, v in hit.items() if t not in cache})
                        p._lib_save()
                    with tolerated():
                        if self.dialog.isShowing() and self.lib_state == ("artist", k):
                            self._lib_render()
                run_on_ui_thread(done)
            threading.Thread(target=work, daemon=True).start()
        return {key: cache.get(t, "") for key, (t, _raw) in titles.items()}

    def _lib_album_tabs(self, a, msgs, dupes=(), natural=None):
        self.lib_album_missing = 0
        self.lib_dupe_info = None
        dupes = list(dupes or ())
        natural = list(natural or [])
        opened = self.__dict__.setdefault("lib_dupes_open", set())
        artist_name = a.get("n", "")
        def tkey_factory():
            tn = a.get("tn") or {}
            def tkey(m):
                v = tn.get(self._album_norm(self._title_of(m), artist_name))
                return (0, v[0], v[1]) if v else (1, 0, 0)
            return tkey
        def group_of(m):
            al = (a.get("al") or {}).get(self._album_norm(self._title_of(m), artist_name), "")
            if not al:
                return self._ALBUM_OTHER
            return self._ALBUM_SINGLES if al.lower().endswith("- single") else al
        def finish(sel, base, album_sorted=False):
            if not dupes:
                return base
            scope = (a["k"], sel)
            in_scope = [d for d in dupes if sel is None or group_of(d) == sel]
            if not in_scope:
                return base
            is_open = scope in opened
            self.lib_dupe_info = {"n": len(in_scope), "open": is_open, "scope": scope,
          "album": sel is not None and sel not in (self._ALBUM_SINGLES, self._ALBUM_OTHER)}
            if not is_open:
                return base
            full = [m for m in natural if sel is None or group_of(m) == sel]
            if album_sorted:
                full = sorted(full, key=tkey_factory())
            return full
        try:
            albums = self._lib_artist_albums(a, msgs)
            groups, order = {}, []
            for m in msgs:
                al = albums.get(self._lib_key(m), "")
                g = (self._ALBUM_SINGLES if al.lower().endswith("- single") else al) if al else self._ALBUM_OTHER
                if g not in groups:
                    order.append(g)
                groups.setdefault(g, []).append(m)
            real = [g for g in order if g not in (self._ALBUM_SINGLES, self._ALBUM_OTHER)]
            if not real or len(groups) < 2:
                return finish(None, msgs)
            real.sort(key=lambda g: -len(groups[g]))
            tail = [g for g in (self._ALBUM_SINGLES, self._ALBUM_OTHER) if g in groups]
            chips = [None] + real + tail
            sel_map = self.__dict__.setdefault("lib_album_sel", {})
            sel = sel_map.get(a["k"])
            if sel is not None and sel not in groups:
                sel = None
                sel_map.pop(a["k"], None)
            def pick(i):
                if chips[i] is None:
                    sel_map.pop(a["k"], None)
                else:
                    sel_map[a["k"]] = chips[i]
                self._lib_render()
            def chip(g):
                if g is None:
                    return {"title": strings("all"), "lead": None}
                title = (strings("singles") if g == self._ALBUM_SINGLES
             else strings("other") if g == self._ALBUM_OTHER else g)
                return {"title": title, "pad_l": 6, "max_w": 180, "lead_size": (self.dp(24), self.dp(24)),
             "lead_gap": 7,
             "lead": lambda sv, g=g: self._album_lead(a, g, groups[g][0], sv)}
            self._chip_row(("album", a["k"]), [chip(g) for g in chips],
          chips.index(sel), pick)
            if sel is not None:
                self.lib_filter_label = (strings("singles") if sel == self._ALBUM_SINGLES
             else strings("other") if sel == self._ALBUM_OTHER else sel)
            if sel is None:
                return finish(None, msgs)
            out = groups[sel]
            album_sorted = False
            if sel not in (self._ALBUM_SINGLES, self._ALBUM_OTHER):
                out = sorted(out, key=tkey_factory())
                album_sorted = True
                cnt = int(((a.get("am") or {}).get(sel) or {}).get("cnt") or 0)
                self.lib_album_missing = max(0, cnt - len(out)) if cnt else 0
            return finish(sel, out, album_sorted)
        except Exception:
            return msgs

    def _album_lead(self, a, album, first_msg, row, radius_dp=5, glyph_sp=11):
        base = self._album_cover_view(first_msg, radius_dp=radius_dp, glyph_sp=glyph_sp, row=row)
        with tolerated():
            url = ((a.get("am") or {}).get(album) or {}).get("art")
            if url:
                return self._album_itunes_cover_view(url, radius_dp, glyph_sp, base=base)
        return base

    def _album_itunes_cover_view(self, url, radius_dp=5, glyph_sp=11, base=None):
        FL = _cls("android.widget.FrameLayout")
        FLP = _cls("android.widget.FrameLayout$LayoutParams")
        GD = _cls("android.graphics.drawable.GradientDrawable")
        glyph = None
        if base is not None:
            cover = base
        else:
            cover = FL(self.act)
            cbg = GD()
            cbg.setColor(_mix(self.c_item, self.c_sub, 0.15))
            cbg.setCornerRadius(float(self.dp(radius_dp)))
            cover.setBackground(cbg)
            with tolerated():
                cover.setClipToOutline(True)
            glyph = self._glyph_icon(("files_music", "msg_filled_data_music", "msg_music", "msg_media"), self.c_sub, pad=max(2, int(glyph_sp * 0.3)), size=glyph_sp)
            cover.addView(glyph, FLP(-1, -1))
        iv = _cls("android.widget.ImageView")(self.act)
        iv.setScaleType(_cls("android.widget.ImageView$ScaleType").CENTER_CROP)
        cover.addView(iv, FLP(-1, -1))
        cache = self.p.__dict__.setdefault("_album_bmp", {})
        bmp = cache.get(url)
        if bmp is not None:
            iv.setImageBitmap(bmp)
            if glyph is not None:
                glyph.setVisibility(8)
            return cover
        def work():
            import os, hashlib
            with tolerated():
                BF = _cls("android.graphics.BitmapFactory")
                ctx = find_class("org.telegram.messenger.ApplicationLoader").applicationContext
                folder = os.path.join(str(ctx.getCacheDir().getAbsolutePath()), "smq_albums")
                os.makedirs(folder, exist_ok=True)
                path = os.path.join(folder, hashlib.md5(url.encode("utf-8")).hexdigest() + ".jpg")
                image = BF.decodeFile(path) if os.path.exists(path) else None
                if image is None:
                    stream = _http_stream(url)
                    try:
                        image = BF.decodeStream(stream)
                    finally:
                        stream.close()
                    if image is None:
                        return
                    with tolerated():
                        fos = jclass("java.io.FileOutputStream")(path)
                        image.compress(_cls("android.graphics.Bitmap$CompressFormat").JPEG, 85, fos)
                        fos.close()
                scaled = _cls("android.graphics.Bitmap").createScaledBitmap(image, 160, 160, True)
                if scaled is not image:
                    with tolerated():
                        image.recycle()
                cache[url] = scaled
                from ..helpers import mem_tight, trim_caches
                trim_caches(cache, keep=(20 if mem_tight() else 120))
                def show():
                    with tolerated():
                        iv.setImageBitmap(scaled)
                        if glyph is not None:
                            glyph.setVisibility(8)
                run_on_ui_thread(show)
        threading.Thread(target=work, daemon=True).start()
        return cover

    def _lib_artist_menu(self, key):
        p, act = self.p, self.act
        artist = next((x for x in self._lib_artist_data()["list"] if x["k"] == key), None)
        if artist is None:
            self._lib_go("home")
            return
        name = str(artist.get("n", strings("artist")))
        sc = self._lib_scope(("artist", key))
        msgs = [m for m in (sc["shown"] if sc else self._lib_artist_msgs(key)) if m is not None]
        qname, qsrc, qcover = (sc["name"], sc["src"], sc["cover"]) if sc else (name, ("artist", key), None)
        meta = self._lib_tracks_meta(len(msgs), self._lib_message_minutes(msgs)) if msgs else strings("no_cached_tracks")
        if sc and msgs:
            meta = f"{sc['label']} · {meta}"
        def guarded(fn):
            def run():
                if msgs:
                    fn()
                else:
                    p._bulletin(strings("no_cached_tracks_for_this_artist"), error=True)
            return run
        play_next = guarded(lambda: p._lib_play_msgs(msgs, "next", name=qname, source_key=qsrc, cover=qcover))
        add_to = guarded(lambda: p._lib_add_to_sheet(
       act, lambda cb: cb(list(msgs)), sc["label"] if sc else name, strings("n_tracks", len(msgs))))
        exclude_from_queue = guarded(lambda: p._exclude_from_queue(msgs, sc["label"] if sc else name))
        def select_tracks():
            if self.lib_state != ("artist", key):
                self._lib_go("artist", key)
            self._lib_select_all_menu()
        pinned = key in self._lib_pinned_artists()
        extras = [(strings("unpin_artist") if pinned else strings("pin_artist"),
       strings("remove_from_the_top_of_artists") if pinned else strings("always_show_at_the_top_of"),
       False, lambda: self._lib_toggle_pin_artist(key, name))]
        if msgs:
            extras += [
          p._share_playlist_opt((sc["label"] if sc and sc.get("label") else name), lambda cb: cb(list(msgs))),
          (strings("set_as_profile_playlist"), strings("use_this_artists_tracks_as_your"), False,
          lambda: p._profile_playlist_sheet(
          act, name, lambda cb: cb(list(msgs)), len(msgs)))]
        lead = None
        with tolerated():
            lead = self._artist_avatar(key, self.dp(48), name, views={})
        p._collection_sheet(
       act, name, meta, play_next, add_to,
       select=select_tracks if msgs else None,
       exclude=exclude_from_queue if msgs else None,
       extras=extras,
       danger=[(strings("remove_from_library"),
       strings("change_this_later_in_the_excluded"),
       True, lambda: self._lib_exclude_artist(key, name))],
       artist_search=name,
       lead=lead)

    def _lib_chat_info(self, c):
        cached = self.p._chat_track_cache.get((c["d"], c["t"]))
        acc = self._lib_chat_account(c, cached)
        sub = (self._lib_tracks_meta(len(cached), self._lib_message_minutes(cached))
       if cached is not None else (self._lib_cached_meta(c) or strings(self._CHAT_KIND_KEYS.get(self._lib_chat_kind(c, acc), "chat"))))
        return acc, sub

    def _lib_chat_row(self, c, first, last):
        acc, sub = self._lib_chat_info(c)
        self._lib_row(c["n"], sub, (lambda k=(c["d"], c["t"]): self._lib_go("chat", k)),
       first, last, glyph=("msg_groups", "msg_discussion", "msg_channel"), avatar_did=int(c["d"]), avatar_acc=acc,
       reorder_type="chats", reorder_id=(int(c["d"]), int(c["t"])),
       type_icons=self._TYPE_ICONS.get(self._lib_chat_kind(c, acc)),
       long_cb=lambda k=(c["d"], c["t"]): self._lib_chat_menu(k))

    def _lib_chat_card(self, c, grid_row):
        acc, sub = self._lib_chat_info(c)
        self._lib_round_card(
       grid_row, lambda size: self._lib_avatar_tile(int(c["d"]), acc, size, True),
       c["n"], sub, lambda k=(c["d"], c["t"]): self._lib_go("chat", k), (strings("chat") + ": "),
       reorder_type="chats", reorder_id=(int(c["d"]), int(c["t"])),
       menu_cb=lambda k=(c["d"], c["t"]): self._lib_chat_menu(k))

    def _lib_friend_info(self, friend):
        uid = int(friend.get("d", friend.get("id", 0)) or 0)
        acc = int(friend.get("a", 0) or 0)
        cached = self.p._friend_track_cache.get((acc, uid))
        sub = (self._lib_tracks_meta(len(cached), self._lib_message_minutes(cached))
       if cached is not None else
       (self._lib_cached_meta(friend) or strings("profile_playlist_tap_to_load")))
        return uid, acc, sub

    def _lib_friend_row(self, friend, first, last):
        uid, acc, sub = self._lib_friend_info(friend)
        self._lib_row(friend.get("n", strings("profile")), sub, (lambda user_id=uid: self._lib_go("friend", user_id)),
       first, last, glyph=("files_music", "msg_filled_data_music", "msg_music", "msg_media"), avatar_did=uid, avatar_acc=acc,
       reorder_type="friends", reorder_id=uid,
       long_cb=lambda user_id=uid: self._lib_friend_menu(user_id),
       description=strings("friend_profile_playlist") + str(friend.get("n", strings("profile"))))

    def _lib_friend_card(self, friend, grid_row):
        uid, acc, sub = self._lib_friend_info(friend)
        self._lib_round_card(
       grid_row, lambda size: self._lib_avatar_tile(uid, acc, size, True),
       friend.get("n", strings("profile")), sub,
       lambda user_id=uid: self._lib_go("friend", user_id), (strings("friend") + ": "),
       reorder_type="friends", reorder_id=uid,
       menu_cb=lambda user_id=uid: self._lib_friend_menu(user_id))

    def _lib_album_tile(self, a, name):
        base = None
        with tolerated():
            artist_name = a.get("n", "")
            cache = a.get("al") or {}
            for m in self._lib_artist_msgs(a["k"]):
                if m is not None and cache.get(self._album_norm(self._title_of(m), artist_name)) == name:
                    base = self._album_cover_view(m, radius_dp=12, glyph_sp=18)
                    break
        if base is None:
            base = self._album_cover_view(None, radius_dp=12, glyph_sp=18)
        with tolerated():
            url = ((a.get("am") or {}).get(name) or {}).get("art")
            if url:
                return self._album_itunes_cover_view(url, radius_dp=12, glyph_sp=18, base=base)
        return base

    def _lib_search_albums(self, query):
        excluded = self._lib_excluded_artists()
        out = []
        for a in self._lib_artist_data().get("list", []):
            if str(a.get("k", "")).casefold() in excluded:
                continue
            counts = {}
            for name in (a.get("al") or {}).values():
                name = str(name or "").strip()
                if name and not name.lower().endswith("- single"):
                    counts[name] = counts.get(name, 0) + 1
            for name in (a.get("am") or {}):
                name = str(name or "").strip()
                if name and not name.lower().endswith("- single"):
                    counts.setdefault(name, 0)
            for name, n in counts.items():
                if query in name.casefold():
                    out.append({"album": name, "artist": a, "n": n})
        out.sort(key=lambda e: (-e["n"], e["album"].casefold()))
        return out[:20]

    def _lib_search_results(self):
        p = self.p
        d = p._lib_data()
        query = str(self.lib_search_query or "").strip().casefold()
        if not query:
            self._lib_home()
            return
        self._lib_set_selection_context(("search",))
        contains = lambda value: query in str(value or "").casefold()
        artists = [a for a in self._lib_artist_data().get("list", [])
       if contains(a.get("n"))]
        playlists = [pl for pl in d.get("playlists", []) if contains(pl.get("name"))]
        chats = [c for c in d.get("chats", []) if contains(c.get("n"))]
        friends = [f for f in d.get("friends", []) if contains(f.get("n"))]
        track_hits = []
        track_seen = set()
        library_chat_keys = set()
        for c in d.get("chats", []):
            with tolerated():
                library_chat_keys.add((int(c.get("d", 0)), int(c.get("t", 0))))
        def add_message_track(message):
            if message is None:
                return
            with tolerated():
                title = self._title_of(message)
                artist = self._author_of(message)
                if not contains(title):
                    return
                key = self._lib_key(message)
                if key is not None and key in track_seen:
                    return
                if key is not None:
                    track_seen.add(key)
                track_hits.append({
             "title": title, "artist": artist, "message": message,
             "key": key, "playlist_id": None
             })
        cache = getattr(p, "_chat_track_cache", {}) or {}
        for chat_key in library_chat_keys:
            if len(track_hits) >= 30:
                break
            msgs = cache.get(chat_key, []) or []
            rows = getattr(msgs, "rows", None)
            if rows is not None:
                for n, r in enumerate(rows):
                    if contains(str(r.get("t") or "")):
                        add_message_track(msgs[n])
                        if len(track_hits) >= 30:
                            break
            else:
                for message in msgs:
                    add_message_track(message)
        for pl in d.get("playlists", []):
            for track in pl.get("tracks", []) or []:
                title = str(track.get("t", "") or "")
                artist = str(track.get("a", "") or "")
                if not contains(title):
                    continue
                try:
                    key = (int(track.get("i", 0)), int(track.get("d", 0)))
                except Exception:
                    key = None
                if key is not None and key in track_seen:
                    continue
                if key is not None:
                    track_seen.add(key)
                track_hits.append({
             "title": title or "Audio", "artist": artist,
             "message": p._msg_cache.get(key) if key is not None else None,
             "key": key, "playlist_id": pl.get("id"), "track": track
             })
        track_hits = track_hits[:30]
        albums = self._lib_search_albums(query)
        total = len(artists) + len(albums) + len(playlists) + len(chats) + len(friends) + len(track_hits)
        self._lib_label(strings("search_results"), strings("n_matches", total))
        if not total:
            self._lib_hint(strings("no_results_for_n_try_an", self.lib_search_query.strip()))
            return
        def add_section(title, entries, count_text=None):
            if not entries:
                return
            self._lib_label(title, count_text or str(len(entries)))
            for i, entry in enumerate(entries):
                yield i, entry
        for i, artist in add_section(strings("artists"), artists):
            key = str(artist.get("k", "")).casefold()
            name = str(artist.get("n", strings("artist")))
            self._lib_row(
          name, strings("n_tracks", int(artist.get('c', 0) or 0)),
          lambda k=key: self._lib_go("artist", k), i == 0, i == len(artists) - 1,
          tile_fn=lambda cd, a=artist: self._lib_artist_photo(a, cd),
          description=(strings("artist") + ": ") + name)
        for i, entry in add_section(strings("albums"), albums):
            al, art = entry["album"], entry["artist"]
            n = entry["n"]
            def open_album(a=art, name=al):
                self.__dict__.setdefault("lib_album_sel", {})[a["k"]] = name
                self._lib_go("artist", str(a.get("k", "")).casefold())
            self._lib_row(
          al, str(art.get("n", "Artist")) + ((" · " + strings("n_tracks", n)) if n else ""),
          open_album, i == 0, i == len(albums) - 1,
          tile_fn=lambda cd, a=art, name=al: self._lib_album_tile(a, name),
          description=(strings("album") + ": ") + al)
        for i, playlist in add_section(strings("playlists"), playlists):
            tracks = playlist.get("tracks", []) or []
            self._lib_row(
          _pln(playlist.get("name", strings("playlist"))),
          self._lib_tracks_meta(len(tracks), p._lib_minutes(tracks)),
          lambda pid=playlist.get("id"): self._lib_go("pl", pid),
          i == 0, i == len(playlists) - 1,
          cover_ms=self._lib_playlist_cover_messages(tracks),
          description=(strings("playlist") + ": ") + _pln(playlist.get("name", strings("playlist"))))
        for i, entry in add_section(strings("tracks"), track_hits):
            message = entry.get("message")
            playlist_id = entry.get("playlist_id")
            track = entry.get("track")
            if message is not None:
                callback = lambda m=message: p._lib_play_msgs([m], "play")
            elif playlist_id is not None:
                callback = lambda pid=playlist_id: self._lib_go("pl", pid)
            else:
                callback = lambda: None
            if message is None and track is None:
                track = {"t": entry.get("title") or "Audio"}
            self._lib_track_row(
          message, track, callback,
          lambda m=message, t=track, pid=playlist_id: self._lib_track_menu(m, t, pid, selectable=False),
          i == 0, i == len(track_hits) - 1, selectable=False)
        for i, chat in add_section(strings("chats"), chats):
            self._lib_chat_row(chat, i == 0, i == len(chats) - 1)
        for i, friend in add_section(strings("friends"), friends):
            self._lib_friend_row(friend, i == 0, i == len(friends) - 1)
        if len(track_hits) >= 30:
            self._lib_hint(strings("showing_the_first_30_track_matches"))

    def _lib_home(self):
        p = self.p
        d = p._lib_data()
        def playlists():
            p._lib_liked_playlist(True)
            p._dl_pl(True)
            p._pp_pl(True)
            pls = d.get("playlists", [])
            self._lib_section(
          "playlists", strings("playlists"), pls,
          lambda pl, first, last: self._lib_playlist_entry_row(pl, first, last),
          lambda pl, row: self._lib_playlist_entry_card(pl, row),
          sort=self._lib_playlist_list_sort_menu, sort_desc=strings("sort_playlists"))
            self._lib_prefetch_covers(pls)
            if not pls:
                self._lib_hint(strings("no_playlists_yet_use_add_to"))
        def chats():
            entries = d.get("chats", [])
            self._lib_section("chats", strings("chats"), entries, self._lib_chat_row, self._lib_chat_card)
            if not entries:
                self._lib_hint(strings("add_a_chat_from_its_music"))
        def friends():
            entries = d.get("friends", [])
            self._lib_section("friends", strings("friends"), entries, self._lib_friend_row, self._lib_friend_card)
            if not entries:
                self._lib_hint(strings("add_a_user_from_their_music"))
        section_builders = {
       "playlists": playlists,
       "chats": chats,
       "friends": friends,
       "artists": self._lib_artists_section,
       }
        order = list(p._library_section_order())
        if self.__dict__.get("_lib_shown", False) or len(order) < 2:
            for section in order:
                section_builders[section]()
            return
        tok = self.__dict__.get("_lib_rtok")
        box = self.lib_box
        def step(i):
            if tok != self.__dict__.get("_lib_rtok"):
                return
            n0 = int(box.getChildCount())
            try:
                section_builders[order[i]]()
            except Exception:
                self._lib_hint(strings("library_couldnt_load"))
            with tolerated():
                if self.tab == "library":
                    n1 = int(box.getChildCount())
                    for k in range(n0, min(n1, n0 + 14)):
                        v = box.getChildAt(k)
                        v.setAlpha(0.0)
                        v.setTranslationY(float(self.dp(10)))
                        v.animate().alpha(1.0).translationY(0.0).setDuration(220).setStartDelay(
                      min(k - n0, 6) * 20).start()
            if i + 1 < len(order):
                self.handler.post(self.Run(lambda: step(i + 1)))
            elif not self.__dict__.get("_lib_pre"):
                self.handler.postDelayed(self.Run(self._lib_load_covers), 30)
        self.handler.post(self.Run(lambda: step(0)))

    def _lib_remove_track(self, pid, t):
        pl = self.p._lib_pl(pid)
        gh = self.__dict__.get("_pl_ghosts", {}).get(pid)
        if gh:
            gh[:] = [g for g in gh if g[1] is not t]
        if pl is not None and t in pl["tracks"]:
            pl["tracks"].remove(t)
            self.p._lib_save()
        self._lib_render()

    def _lib_track_menu(self, m, t=None, pid=None, selectable=True):
        p, act = self.p, self.act
        track_key = self._lib_key(m, t)
        if m is None:
            st = "gone"
            with tolerated():
                st = p._resolver.state(self._lib_key(track=t))
            if st == "loading":
                p._bulletin(strings("still_loading_this_song"))
                return
            if st == "failed":
                p._resolver.retry([self._lib_key(track=t)])
                self._lib_render()
                return
            if pid:
                self._lib_remove_track(pid, t)
                p._bulletin(strings("removed_the_unavailable_track"))
            return
        hero = [(strings("play_next"), lambda: p._lib_play_msgs([m], "next", keep_order=False), False),
       p._hero_add_to(act, m)]
        if selectable:
            hero.append((strings("select"), lambda: self._lib_begin_selection(track_key), False))
        if pid:
            hero.append((strings("remove"), lambda: self._lib_remove_track(pid, t), True))
        p._track_sheet(act, m, hero, editor=self)

    def _lib_undo_tracks(self, pid, snap, text, done_text):
        def restore():
            pl = self.p._lib_pl(pid)
            if pl is None:
                return False
            pl["tracks"][:] = snap[0]
            if snap[1] is None:
                pl.pop("sm", None)
            else:
                pl["sm"] = snap[1]
            self.p._lib_save()
            with tolerated():
                self._lib_render()
            return True
        self._start_undo(snap, text, restore, done_text)

    def _lib_reverse_playlist(self, pid):
        pl = self.p._lib_pl(pid)
        if pl is None:
            return
        snap = (list(pl["tracks"]), pl.get("sm"))
        pl["tracks"].reverse()
        self.p._lib_save()
        self._lib_render()
        self._lib_undo_tracks(pid, snap, strings("playlist_reversed"), strings("reverse_undone"))

    def _lib_sort_playlist(self, pid, mode):
        pl = self.p._lib_pl(pid)
        if pl is None:
            return
        tracks = pl["tracks"]
        snap = (list(tracks), pl.get("sm"))
        descending = mode.endswith("_desc")
        base = mode[:-5] if descending else mode
        if base == "title":
            tracks.sort(key=lambda t: (str(t.get("t", "")).lower(), str(t.get("a", "")).lower()), reverse=descending)
        elif base == "artist":
            tracks.sort(key=lambda t: (str(t.get("a", "")).lower(), str(t.get("t", "")).lower()), reverse=descending)
        elif base == "duration":
            tracks.sort(key=lambda t: int(t.get("s", 0)), reverse=descending)
        elif base == "shuffle":
            random.shuffle(tracks)
        else:
            self._lib_reverse_playlist(pid)
            return
        pl["sm"] = [base, bool(descending)]
        self.p._lib_save()
        self._lib_render()
        if base == "shuffle":
            self._lib_undo_tracks(pid, snap, strings("playlist_shuffled"), strings("shuffle_undone"))
        else:
            self._lib_undo_tracks(pid, snap, strings("list_sorted"), strings("sort_undone"))

    def _lib_playlist_sort_menu(self, pid):
        pl = self.p._lib_pl(pid)
        if pl is None:
            return
        self._lib_sort_sheet(
       strings("sort_playlist"), pl["name"],
       [("title", strings("title"), strings("track_title")),
       ("artist", strings("artist"), strings("artist_name")),
       ("duration", strings("duration"), strings("track_length")),
       ("shuffle", strings("shuffle"), strings("random_order"))],
       lambda mode, desc: self._lib_sort_playlist(pid, mode + ("_desc" if desc else "")),
       desc=bool((pl.get("sm") or [None, False])[1]),
       current=lambda: (pl.get("sm") or [None])[0],
       extra=[(strings("reverse_order"), strings("reverse_the_current_track_order"), False,
       lambda: self._lib_reverse_playlist(pid))])

    def _lib_playlist_menu(self, pid):
        p, act = self.p, self.act
        pl = p._lib_pl(pid)
        if pl is None:
            self._lib_go("home")
            return
        tracks = pl["tracks"]
        name = pl["name"]
        meta = self._lib_tracks_meta(len(tracks), p._lib_minutes(tracks))
        def rename():
            def save(text):
                if text:
                    p._lib_rename(pid, text)
                self.lib_confirm = None
                self._lib_render()
            self._prompt_text(strings("rename_playlist"), name, strings("playlist_name"), save)
        def delete():
            d = p._lib_data()
            snap = (list(d["playlists"]), d.get("last"))
            p._lib_delete(pid)
            self._lib_go("home")
            self._lib_undo_list("playlists", snap, strings("deleted_n", name))
        p._collection_sheet(
       act, name, meta,
       lambda: p._lib_play(act, tracks, "next", name=name),
       lambda: p._lib_add_to_sheet(
       act, (lambda cb: cb(tracks)), name, strings("n_tracks", len(tracks)), exclude=pid),
       select=lambda: self._lib_select_all_menu(),
       exclude=lambda: p._exclude_from_queue(self._lib_known(tracks), name),
       extras=[
       (strings("sort_tracks"), strings("sort_by_title_artist_duration_or"), False,
       lambda: self._lib_playlist_sort_menu(pid))] + ([] if p._lib_protected(pl) else [
       (strings("rename_playlist"), strings("change_the_playlist_name"), False, rename)]) + [
       p._share_playlist_opt(name, lambda cb: cb(tracks))] + ([] if pid == "profile" else [
       (strings("set_as_profile_playlist"), strings("use_this_playlist_as_your_profile"), False,
       lambda: p._profile_playlist_sheet(
       act, name, lambda cb: p._lib_resolve(act, tracks, cb), len(tracks)))]),
       danger=[] if p._lib_protected(pl) else [(strings("delete_playlist"), "", True, delete)],
       playlist=pl)

    def _lib_playlist_view(self, pid):
        p = self.p
        pl = p._lib_pl(pid)
        if pl is None:
            self._lib_go("home")
            return
        p._lib_data()["last"] = pid
        self._lib_set_selection_context(("pl", pid))
        tracks = pl["tracks"]
        name = pl["name"]
        act = self.act
        dl = pid == "downloaded"
        if pid == "profile" and p._pp_last is None:
            p._pp_pull()
        rs = p._resolver
        def tkey(t):
            return (int(t["i"]), int(t["d"]))
        ghosts = self.__dict__.setdefault("_pl_ghosts", {}).setdefault(pid, [])
        if ghosts:
            tracks = list(tracks)
            for gi, gt in sorted(ghosts, key=lambda g: g[0]):
                tracks.insert(min(gi, len(tracks)), gt)
        msgs = self._lib_known(tracks)
        rs.request_tracks([t for t, m in zip(tracks, msgs) if m is None])
        if any(m is None for m in msgs):
            msgs = self._lib_known(tracks)
        def droppable(t):
            lf = str(t.get("lf") or "") if dl else ""
            if not lf:
                return True
            with tolerated():
                f = jclass("java.io.File")(lf)
                par = f.getParentFile()
                return (not bool(f.exists())) and par is not None and bool(par.exists())
            return False
        if pid != "profile":
            shown = {id(g[1]) for g in ghosts}
            fresh = [(i, t) for i, (t, m) in enumerate(zip(tracks, msgs))
                     if m is None and id(t) not in shown and rs.state(tkey(t)) == "gone" and droppable(t)]
            if fresh:
                ghosts.extend(fresh)
                gone_ids = {id(t) for _, t in fresh}
                pl["tracks"] = [t for t in pl["tracks"] if id(t) not in gone_ids]
                p._liked_cache = None
                p._lib_save()
        loading_n = sum(1 for t, m in zip(tracks, msgs) if m is None and rs.state(tkey(t)) == "loading")
        failed_n = sum(1 for t, m in zip(tracks, msgs) if m is None and rs.state(tkey(t)) == "failed")
        meta = self._lib_tracks_meta(len(tracks), p._lib_minutes(tracks))
        if loading_n:
            meta += strings("loading_n", loading_n)
        elif failed_n:
            meta += strings("n_couldnt_load", failed_n)
        self._lib_detail_header(name, meta,
       lambda: self._lib_go("home"),
       lambda: self._lib_playlist_menu(pid),
       sync_pid=pid if pid in ("profile", "downloaded") else None)
        self._lib_detail_actions(
       lambda: p._lib_play(act, tracks, "play", name=name, source_key=("playlist", pid)),
       lambda: p._lib_play(act, tracks, "play", shuffle=True, name=name, source_key=("playlist", pid)),
       )
        if dl:
            fixed = False
            for t, m in zip(tracks, msgs):
                if m is not None and t.get("stub"):
                    t.update(p._lib_track(m))
                    t.pop("stub", None)
                    fixed = True
            if fixed:
                p._lib_save()
        if not tracks:
            self._lib_hint((strings("searching_for_downloaded_songs") if p.__dict__.get("_dl_busy") or p.__dict__.get("_dl_deep_busy")
          else "No downloaded songs yet. Tap the sync button to search.") if dl else
          strings("this_playlist_is_empty_use_add"))
        def dl_tail():
            deep = bool(p.__dict__.get("_dl_deeped"))
            def dig():
                def done(n):
                    p._dl_deeped = True
                    p._bulletin(strings("couldnt_read_telegrams_storage_index") if n < 0 else
                strings("added_n_downloaded_tracks", n) if n else
                strings("no_new_downloaded_tracks_found"), error=n < 0)
                    if self.lib_state == ("pl", pid):
                        self._lib_render()
                p._bulletin(strings("searching_for_downloaded_songs"))
                p._dl_scan(lambda: p._dl_deep(done))
                if self.lib_state == ("pl", pid):
                    self._lib_render()
            self._lib_row(strings("search_again") if deep else strings("find_downloaded_songs"),
          strings("look_through_telegrams_downloaded_files"), dig, True, True,
          glyph=("msg_add",), description=strings("find_more_downloaded_songs"), top_margin_dp=8)
        def profile_note():
            self._lib_hint(strings("profile_playlist_note"))
        tail = dl_tail if dl else profile_note if pid == "profile" else None
        def retry_failed():
            rs.retry([tkey(t) for t, m in zip(tracks, msgs)
          if m is None and rs.state(tkey(t)) == "failed"])
            self._lib_render()
        def row_at(i):
            t, m = tracks[i], msgs[i]
            if m is None:
                st = rs.state(tkey(t))
                if st == "loading":
                    on_click = lambda: p._bulletin(strings("still_loading_this_song"))
                elif st == "failed":
                    on_click = retry_failed
                else:
                    on_click = lambda tt=t: self._lib_track_menu(None, tt, pid)
            else:
                on_click = lambda tt=t: p._lib_play(
             act, tracks, "play", start=(tt["i"], tt["d"]), name=name, source_key=("playlist", pid))
            on_more = lambda mm=m, tt=t: self._lib_track_menu(mm, tt, pid)
            return m, t, on_click, on_more
        self._lib_render_track_rows(len(tracks), row_at, playlist_id=pid, tail=tail)
        if tail is not None and not tracks:
            tail()

    def _lib_fetch_chat_tracks(self, key, act, callback=None, since_id=0, force=False, on_batch=None):
        p = self.p
        key = tuple(key)
        cached = p._chat_track_cache.get(key)
        if cached is not None and not force:
            if callback is not None:
                callback(cached)
            return
        if callback is not None:
            self.lib_waiters.setdefault(key, []).append(callback)
        bb = self.__dict__.setdefault("_lib_bb", {})
        if on_batch is not None:
            cbs, buf = bb.setdefault(key, ([], []))
            cbs.append(on_batch)
            for b in list(buf):
                with tolerated():
                    on_batch(*b)
        if key in self.lib_loading:
            return
        chat = next((c for c in p._lib_data()["chats"] if (c["d"], c["t"]) == key), None)
        if chat is None:
            for fn in self.lib_waiters.pop(key, []):
                fn([])
            return
        self.lib_loading.add(key)
        def publish_ready(used):
            self.lib_loading.discard(key)
            bb.pop(key, None)
            done_stream = self.lib_streams.get(key)
            if done_stream is not None:
                self._lib_follow_merge(done_stream, True)
            p._chat_track_cache[key] = used
            self.__dict__.setdefault("_lib_topic_groups", {}).pop(key, None)
            self.lib_streams.pop(key, None)
            p._activity_status(("chat_stream", key), None)
            p.__dict__.setdefault("_lib_fresh", {})[("c",) + key] = time.time()
            if used and not self.__dict__.get("_artist_scanning"):
                p._artist_dirty = True
                self._lib_artist_auto()
            if used:
                if len(used) >= 128:
                    self._lib_store_counts_async(chat, used, ("chat", key))
                else:
                    self._lib_store_counts(chat, used)
            p._request_library_refresh()
            for fn in self.lib_waiters.pop(key, []):
                with tolerated():
                    fn(used)
            if self.lib_state == ("chat", key):
                self._lib_render()
        def ready(used):
            if not since_id:
                publish_ready(used)
                return
            def merge_incremental():
                merged = None
                with tolerated():
                    old = p._chat_track_cache.revive(key)
                    if old is not None and getattr(old, "rows", None) is not None:
                        if used:
                            try:
                                acc = int(old._idx.acc)
                            except Exception:
                                acc = int(used[0].currentAccount)
                            nidx = p._tstore.append(key, used, acc)
                            if nidx is not None:
                                merged = _LazyTracks(p._chat_track_cache, key, idx=nidx)
                        else:
                            merged = old
                    elif old is not None and getattr(old, "_objs", None) is not None:
                        combined = list(used or []) + list(old._objs or [])
                        by_key = {}
                        for item in combined:
                            with tolerated():
                                by_key[(int(item.getId()), int(item.getDialogId()))] = item
                        merged = sorted(by_key.values(), key=lambda m: -int(m.getId()))
                if merged is None:
                    try:
                        run_on_ui_thread(failed)
                    except Exception:
                        failed()
                    return
                def commit():
                    publish_ready(merged)
                try:
                    run_on_ui_thread(commit)
                except Exception:
                    commit()
            threading.Thread(target=merge_incremental, daemon=True,
          name="smq-incremental-chat-merge").start()
        def failed():
            self.lib_loading.discard(key)
            bb.pop(key, None)
            self.lib_streams.pop(key, None)
            p._activity_status(("chat_stream", key), None)
            stale = None
            with tolerated():
                stale = p._chat_track_cache.revive(key)
            for fn in self.lib_waiters.pop(key, []):
                with tolerated():
                    fn(stale if stale is not None else [])
            if stale is not None and self.lib_state == ("chat", key):
                self._lib_render()
        def batches(batch, count, total):
            cbs, buf = bb.setdefault(key, ([], []))
            buf.append((batch, count, total))
            for cb in list(cbs):
                with tolerated():
                    cb(batch, count, total)
        self.handler.post(self.Run(lambda: p._fetch_scope_tracks(
       None, chat["d"], chat["t"], [], ready, act, on_fail=failed,
       since_id=since_id, on_batch=batches, silent=True)))

    def _lib_stream_begin(self, key, base=None, mode="initial", known_ids=None):
        key = tuple(key)
        tail = []
        known = set(known_ids or ())
        if known_ids is None:
            rows = getattr(base, "rows", None) if base is not None else None
            if rows is not None:
                try:
                    known = set(int(r.get("i", 0) or 0) for r in rows)
                except Exception:
                    known = set()
            elif base is not None and mode != "rescan":
                objs = getattr(base, "_objs", None)
                if objs is not None:
                    try:
                        known = set(int(m.getId()) for m in objs if m is not None)
                    except Exception:
                        known = set()
        display = _ProgressiveChatTracks(base if base is not None else [], tail)
        stream = {"base": base if base is not None else [], "tail": tail,
       "display": display, "known": known, "mode": mode, "count": 0}
        self.lib_streams[key] = stream
        return stream

    def _lib_follow_stream(self, key, src):
        st = self.lib_streams.get(tuple(key))
        if st is not None:
            st["follow"] = {"src": src, "idx": len(st["tail"]), "state": {"keys": None, "desc": None}}

    def _lib_follow_merge(self, stream, final=False):
        fol = stream.get("follow")
        if fol is None:
            return
        p = self.p
        if getattr(p, "_queue_scope_key", None) != fol["src"]:
            stream["follow"] = None
            return
        if p.__dict__.get("_queue_build_state") is not None:
            return
        items = stream["tail"][fol["idx"]:]
        fol["idx"] = len(stream["tail"])
        with tolerated():
            p._queue_insert_sorted(items, fol["state"], final)

    def _lib_stream_meta_text(self, stream):
        n = len(stream["display"])
        if stream["mode"] == "rescan":
            return strings("n_tracks_rescanning", n)
        if n <= 0:
            return strings("loading_tracks")
        total = int(stream.get("total", 0) or 0)
        if total >= n:
            return strings("n_of_n_tracks_loaded", n, total)
        return strings("n_tracks_loaded", n)

    def _lib_stream_batch(self, key, batch, count=0, total=0):
        key = tuple(key)
        stream = self.lib_streams.get(key)
        if stream is None:
            return
        added = 0
        for m in batch or []:
            try:
                mid = int(m.getId())
            except Exception:
                continue
            if mid in stream["known"]:
                continue
            stream["known"].add(mid)
            stream["tail"].append(m)
            k = self.p._msg_key(m)
            if k:
                self.p._msg_cache[k] = m
            added += 1
        if added:
            self._lib_follow_merge(stream)
        stream["count"] = int(count or stream["count"])
        with tolerated():
            stream["total"] = max(int(stream.get("total", 0) or 0), int(total or 0))
        with tolerated():
            if stream["total"] and self.lib_state == ("chat", key):
                self._sync_pct_set(min(99, int(100 * int(stream["count"]) / int(stream["total"]))))
        if self.__dict__.get("_lib_replay"):
            return
        viewing = self.tab == "library" and self.lib_state == ("chat", key)
        if viewing:
            self.p._activity_status(("chat_stream", key), None)
        else:
            visible_n = len(stream["tail"])
            self.p._activity_status(("chat_stream", key),
          (strings("rescanning_chat_n_new_tracks_found", visible_n) if stream["mode"] == "rescan"
          else strings("loading_chat_n_tracks_loaded", visible_n)))
        if not added or not viewing:
            return
        loader = self.lib_track_loader
        if loader is not None and loader.get("context") == self.lib_state:
            loader["count"] = len(stream["display"])
            self._lib_sync_last_corners()
            self.handler.postDelayed(self.Run(self._lib_maybe_load_more), 30)
            with tolerated():
                meta = self._lib_stream_meta_text(stream)
                self.lib_detail_base_meta = meta
                if self.lib_detail_meta is not None and not self.lib_sel_mode:
                    self.lib_detail_meta.setText(meta)
        else:
            self._lib_render()

    def _lib_chat_rescan(self, key, full=False):
        p, act = self.p, self.act
        key = tuple(key)
        old = p._chat_track_cache.get(key)
        before = len(old) if old is not None else 0
        prep_key = ("chat_rescan_prep", key)
        p._activity_status(prep_key, strings("preparing_chat_rescan"))
        p._bulletin(strings("checking_for_new_music") if not full and old is not None else strings("rescanning"))
        def prepare():
            since = 0
            known_ids = set()
            try:
                rows = getattr(old, "rows", None) if old is not None else None
                if rows is not None:
                    known_ids = set(int(r.get("i", 0) or 0) for r in rows)
                    if not full and p._tstore.enabled() and known_ids:
                        since = max(known_ids)
                else:
                    objs = getattr(old, "_objs", None) if old is not None else None
                    if objs is not None:
                        known_ids = set()
                        top = 0
                        for message in objs:
                            with tolerated():
                                mid = int(message.getId())
                                known_ids.add(mid)
                                top = max(top, mid)
                        if not full and p._tstore.enabled():
                            since = top
            except Exception:
                since = 0
            def start_fetch():
                p._activity_status(prep_key, None)
                self._lib_stream_begin(
            key, base=old if old is not None else [], mode="rescan",
            known_ids=known_ids)
                if self.tab == "library" and self.lib_state == ("chat", key):
                    self._lib_render()
                def finished(found):
                    with tolerated():
                        n = len(found) if found is not None else 0
                        if not since:
                            p._bulletin(strings("n_tracks_loaded_2", n))
                        elif n > before:
                            d = n - before
                            p._bulletin(strings("n_new_tracks_found", d))
                        else:
                            p._bulletin(strings("no_new_music"))
                self._lib_fetch_chat_tracks(
            key, act, finished, since_id=since, force=True,
            on_batch=lambda batch, count, total: self._lib_stream_batch(
            key, batch, count, total))
            try:
                run_on_ui_thread(start_fetch)
            except Exception:
                start_fetch()
        threading.Thread(target=prepare, daemon=True, name="smq-chat-rescan-plan").start()

    def _lib_chat_menu(self, key):
        p, act = self.p, self.act
        key = tuple(key)
        chat = next((c for c in p._lib_data()["chats"] if (c["d"], c["t"]) == key), None)
        if chat is None:
            self._lib_go("home")
            return
        msgs = p._chat_track_cache.get(key)
        if msgs is None:
            meta = strings("loading_tracks")
        else:
            cached_meta = self._lib_cached_meta(chat)
            if cached_meta is not None:
                meta = cached_meta
            elif len(msgs) >= 128:
                meta = self._lib_tracks_meta(len(msgs), 0)
            else:
                meta = self._lib_tracks_meta(len(msgs), self._lib_message_minutes(msgs))
        sc = self._lib_scope(("chat", key))
        def scoped():
            return [m for m in sc["shown"] if m is not None]
        if sc:
            items = scoped()
            meta = f"{sc['label']} · " + self._lib_tracks_meta(len(items), self._lib_message_minutes(items))
        def play_next():
            if sc:
                p._lib_play_msgs(scoped(), "next", name=sc["name"], source_key=sc["src"])
                return
            self._lib_fetch_chat_tracks(key, act, lambda found: p._lib_play_msgs(
          found, "next", name=chat["n"]))
        def add_to():
            if sc:
                p._lib_add_to_sheet(act, lambda cb: cb(scoped()), sc["label"], sc["label"])
                return
            self._lib_add_chat_items_to_sheet(key, chat, act)
        def rescan(full=False):
            self._lib_chat_rescan(key, full)
        def remove():
            d = p._lib_data()
            snap = (list(d["chats"]), None)
            p._lib_remove_chat(chat["d"], chat["t"])
            self._lib_go("home")
            self._lib_undo_list("chats", snap, strings("removed_n", chat['n']))
        lead = None
        with tolerated():
            lead = self._lib_avatar_tile(int(chat["d"]), self._lib_chat_info(chat)[0], self.dp(48), True)
        p._collection_sheet(
       act, chat["n"], meta, play_next, add_to,
       select=lambda: self._lib_select_all_menu(),
       exclude=lambda: p._exclude_from_queue(scoped() if sc else msgs, sc["label"] if sc else chat["n"]),
       extras=[
       (strings("rescan_this_chat"), strings("checks_for_new_songs_hold_for"), False, rescan, "", None,
       lambda: rescan(True)),
       p._share_playlist_opt(
       sc["label"] if sc else chat["n"],
       (lambda cb: cb(scoped())) if sc else (lambda cb: self._lib_fetch_chat_tracks(key, act, cb))),
       (strings("set_as_profile_playlist"), strings("use_this_chats_music_as_your"), False,
       lambda: p._profile_playlist_sheet(
       act, sc["label"] if sc else chat["n"],
       (lambda cb: cb(scoped())) if sc else (lambda cb: self._lib_fetch_chat_tracks(key, act, cb)),
       len(scoped()) if sc else len(msgs) if msgs is not None else None))],
       danger=[(strings("remove_from_library"), strings("this_only_removes_the_saved_shortcut"), True, remove)],
       header_action=(("msg_viewintopic", "msg_openin", "msg_profile"),
       strings("open_chat"), lambda: p._open_chat_scope(chat["d"], sc["topic"] if sc else chat["t"])),
       lead=lead)

    def _lib_add_chat_items_to_sheet(self, key, chat, act):
        self.p._lib_add_to_sheet(
       act,
       (lambda cb: self._lib_fetch_chat_tracks(key, act, cb)),
       chat["n"], chat["n"],
       )

    def _lib_chat_view(self, key):
        p = self.p
        key = tuple(key)
        chat = next((c for c in p._lib_data()["chats"] if (c["d"], c["t"]) == key), None)
        if chat is None:
            self._lib_go("home")
            return
        act = self.act
        self._lib_set_selection_context(("chat", key))
        self.lib_scope = None
        stream = self.lib_streams.get(key)
        cached = p._chat_track_cache.get(key)
        if stream is None and cached is not None and key not in self.lib_loading and \
       bool(p.get_setting("lib_auto_refresh", False)) and p._net_ok() and \
       time.time() - p.__dict__.setdefault("_lib_fresh", {}).get(("c",) + key, 0) > self._LIB_TTL:
            p._chat_track_cache.pop(key, None)
            cached = None
        if cached is None and (stream is None or (
       stream.get("mode") == "initial" and key not in self.lib_loading)):
            if stream is None:
                stream = self._lib_stream_begin(key, base=[], mode="initial")
            self._lib_replay = True
            try:
                self._lib_fetch_chat_tracks(
             key, act, on_batch=lambda batch, count, total: self._lib_stream_batch(key, batch, count, total))
            finally:
                self._lib_replay = False
        if stream is not None:
            msgs = stream["display"]
        else:
            msgs = cached
        if msgs is not None and stream is None:
            if len(msgs) < 128:
                self._lib_store_counts(chat, msgs)
            elif chat.get("cm") is None or chat.get("cn") != len(msgs):
                self._lib_store_counts_async(chat, msgs, ("chat", key))
        if stream is not None:
            meta = self._lib_stream_meta_text(stream)
        else:
            if msgs is None:
                meta = strings("loading_tracks")
            else:
                cached_meta = self._lib_cached_meta(chat)
                if cached_meta is not None:
                    meta = cached_meta
                elif len(msgs) >= 128:
                    meta = self._lib_tracks_meta(len(msgs), 0)
                else:
                    meta = self._lib_tracks_meta(len(msgs), self._lib_message_minutes(msgs))
        self._lib_detail_header(chat["n"], meta,
       lambda: self._lib_go("home"),
       lambda: self._lib_chat_menu(key),
       avatar_did=chat["d"], avatar_acc=self._lib_chat_account(chat, None if stream is not None else msgs),
       sync_action=(lambda: self._lib_chat_rescan(key), lambda: key in self.lib_loading or key in self.lib_streams))
        if msgs is None or (stream is not None and not msgs):
            self._lib_empty_loading_view(strings("loading_tracks"))
            return
        shown = msgs
        self.lib_filter_label = None
        acc = self._lib_chat_account(chat, None if stream is not None else msgs)
        qname, qsrc = chat["n"], ("chat", key[0], key[1])
        if key[1] == 0 and stream is None and self._lib_is_forum(key[0], acc):
            try:
                shown = self._lib_topic_tabs(key, msgs, acc)
            except Exception:
                shown = msgs
                self.lib_filter_label = None
            self._lib_apply_filter_meta(shown)
            tsel = self.__dict__.get("lib_topic_sel", {}).get(key, 0)
            if tsel and self.lib_filter_label:
                qname = p._auto_queue_name(key[0], tsel, None, acc) or chat["n"]
                qsrc = ("chat", key[0], tsel)
                self.lib_scope = {"state": ("chat", key), "shown": shown, "name": qname,
             "src": qsrc, "cover": None, "label": self.lib_filter_label, "topic": tsel}
        def play_chat(**kw):
            p._lib_play_msgs(shown, "play", name=qname, source_key=qsrc, **kw)
            self._lib_follow_stream(key, qsrc)
        self._lib_detail_actions(
       lambda: play_chat(),
       lambda: play_chat(shuffle=True),
       )
        def row_at(i):
            m = shown[i]
            on_click = lambda mm=m, idx=i: play_chat(start=p._msg_key(mm), _start_index=idx)
            on_more = lambda mm=m: self._lib_track_menu(mm)
            return m, None, on_click, on_more
        self._lib_render_track_rows(len(shown), row_at)

    def _lib_friend(self, user_id):
        try:
            uid = int(user_id)
        except Exception:
            return None
        return next((f for f in self.p._lib_data().get("friends", [])
       if int(f.get("d", f.get("id", 0)) or 0) == uid), None)

    def _lib_friend_account(self, friend, messages=None):
        for message in messages or []:
            with tolerated():
                return int(message.currentAccount)
        try:
            return int(friend.get("a", 0) or 0)
        except Exception:
            return 0

    def _lib_fetch_friend_tracks(self, user_id, act, callback=None, force=False):
        p = self.p
        friend = self._lib_friend(user_id)
        if friend is None:
            if callback is not None:
                callback([])
            return
        uid = int(friend.get("d", friend.get("id", 0)) or 0)
        acc = self._lib_friend_account(friend)
        key = (acc, uid)
        cached = p._friend_track_cache.get(key)
        if cached is not None and not force:
            if callback is not None:
                callback(cached)
            return
        waiters = getattr(self, "lib_friend_waiters", None)
        if waiters is None:
            self.lib_friend_waiters = {}
            waiters = self.lib_friend_waiters
        if callback is not None:
            waiters.setdefault(key, []).append(callback)
        busy = getattr(self, "lib_friend_loading", set())
        self.lib_friend_loading = busy
        if key in busy:
            return
        busy.add(key)
        def work():
            error = None
            messages = []
            try:
                input_user = p._pm_input_user(uid, int(friend.get("h", 0) or 0), acc)
                docs = p._pm_get_saved_music(acc, input_user, lambda: False, lambda _t: None)
                for index, doc in enumerate(docs):
                    with tolerated():
                        msg = p._pm_synthetic_music_message(acc, uid, doc, index)
                        if msg is not None:
                            with tolerated():
                                if not bool(msg.isMusic()):
                                    continue
                            messages.append(msg)
            except Exception as e:
                error = str(e)
            def finish():
                busy.discard(key)
                p._friend_track_cache[key] = messages if error is None else []
                if error is None:
                    friend["r"] = int(time.time())
                    p.__dict__.setdefault("_lib_fresh", {})[("f",) + key] = time.time()
                    friend["cn"] = len(messages)
                    friend["cm"] = self._lib_message_minutes(messages)
                    p._lib_save()
                for fn in waiters.pop(key, []):
                    with tolerated():
                        fn(messages if error is None else [])
                if self.lib_state == ("friend", uid):
                    if error:
                        p._bulletin(strings("couldnt_load_this_profile_playlist"), error=True)
                    self._lib_render()
            try:
                run_on_ui_thread(finish)
            except Exception:
                finish()
        threading.Thread(target=work, daemon=True).start()

    def _lib_friend_rescan(self, uid, acc):
        self.p._friend_track_cache.pop((int(acc or 0), int(uid)), None)
        self._lib_fetch_friend_tracks(uid, self.act, force=True)
        self._lib_render()

    def _lib_friend_menu(self, user_id):
        p, act = self.p, self.act
        friend = self._lib_friend(user_id)
        if friend is None:
            self._lib_go("home")
            return
        uid = int(friend.get("d", friend.get("id", 0)) or 0)
        name = str(friend.get("n", strings("profile")))
        cached = p._friend_track_cache.get((int(friend.get("a", 0) or 0), uid))
        meta = (self._lib_tracks_meta(len(cached), self._lib_message_minutes(cached))
       if cached is not None else strings("profile_playlist"))
        def rescan():
            p._friend_track_cache.pop((int(friend.get("a", 0) or 0), uid), None)
            self._lib_fetch_friend_tracks(uid, act, force=True)
            self._lib_render()
        def remove():
            snap = (list(p._lib_data()["friends"]), None)
            p._lib_data()["friends"] = [f for f in p._lib_data()["friends"]
          if int(f.get("d", f.get("id", 0)) or 0) != uid]
            p._friend_track_cache.pop((int(friend.get("a", 0) or 0), uid), None)
            p._lib_save()
            self._lib_go("home")
            self._lib_undo_list("friends", snap, strings("removed_n", name))
        lead = None
        with tolerated():
            lead = self._lib_avatar_tile(uid, int(friend.get("a", 0) or 0), self.dp(48), True)
        p._collection_sheet(
       act, name, meta,
       lambda: self._lib_fetch_friend_tracks(uid, act, lambda found:
       p._lib_play_msgs(found, "next", name=name)),
       lambda: p._lib_add_to_sheet(act, lambda cb: self._lib_fetch_friend_tracks(uid, act, cb), name, name),
       select=lambda: self._lib_select_all_menu(),
       exclude=lambda: p._exclude_from_queue(cached, name),
       extras=[
       p._share_playlist_opt(name, lambda cb: self._lib_fetch_friend_tracks(uid, act, cb)),
       (strings("rescan"), strings("refresh_this_users_public_profile_playlist"), False, rescan),
       (strings("open_profile"), strings("view_the_users_telegram_profile"), False,
       lambda: p._open_profile_user(uid, int(friend.get("a", 0) or 0)))],
       danger=[(strings("remove_from_library"), strings("this_only_removes_the_saved_shortcut"), True, remove)],
       header_action=(("msg_viewintopic", "msg_openin", "msg_profile"),
       strings("open_profile"), lambda: p._open_profile_user(uid, int(friend.get("a", 0) or 0))),
       lead=lead)

    def _lib_friend_view(self, user_id):
        p = self.p
        friend = self._lib_friend(user_id)
        if friend is None:
            self._lib_go("home")
            return
        uid = int(friend.get("d", friend.get("id", 0)) or 0)
        acc = int(friend.get("a", 0) or 0)
        name = str(friend.get("n", strings("profile")))
        key = (acc, uid)
        self._lib_set_selection_context(("friend", uid))
        msgs = p._friend_track_cache.get(key)
        busy_f = getattr(self, "lib_friend_loading", set())
        if msgs is not None and key not in busy_f and \
       bool(p.get_setting("lib_auto_refresh", False)) and \
       time.time() - p.__dict__.setdefault("_lib_fresh", {}).get(("f",) + key, 0) > self._LIB_TTL:
            p._friend_track_cache.pop(key, None)
            msgs = None
        if msgs is not None:
            friend["cn"] = len(msgs)
            friend["cm"] = self._lib_message_minutes(msgs)
        meta = self._lib_tracks_meta(len(msgs), self._lib_message_minutes(msgs)) if msgs is not None else strings("loading_profile_playlist")
        self._lib_detail_header(name, meta,
       lambda: self._lib_go("home"),
       lambda: self._lib_friend_menu(uid),
       avatar_did=uid, avatar_acc=acc,
       sync_action=(lambda: self._lib_friend_rescan(uid, acc),
                    lambda: (int(acc or 0), int(uid)) in getattr(self, "lib_friend_loading", ()) or (int(acc or 0), int(uid)) not in p._friend_track_cache))
        if msgs is None:
            self._lib_empty_loading_view(strings("loading_profile_playlist"))
            self._lib_fetch_friend_tracks(uid, self.act)
            return
        self._lib_detail_actions(
       lambda: p._lib_play_msgs(msgs, "play", name=name, source_key=("friend", uid)),
       lambda: p._lib_play_msgs(msgs, "play", shuffle=True, name=name, source_key=("friend", uid)),
       )
        if not msgs:
            self._lib_hint(strings("no_public_music_was_found_rescan"))
            return
        def row_at(i):
            m = msgs[i]
            on_click = lambda mm=m: p._lib_play_msgs(
          msgs, "play", start=p._msg_key(mm), name=name, source_key=("friend", uid))
            on_more = lambda mm=m: self._lib_track_menu(mm)
            return m, None, on_click, on_more
        self._lib_render_track_rows(len(msgs), row_at)

    def _build_lyrics_page(self):
        FL = jclass("android.widget.FrameLayout")
        FLP = jclass("android.widget.FrameLayout$LayoutParams")
        LL = jclass("android.widget.LinearLayout")
        page = FL(self.act)
        self.lyr_sv = jclass("android.widget.ScrollView")(self.act)
        self.lyr_sv.setVerticalScrollBarEnabled(False)
        self.lyr_col = LL(self.act)
        self.lyr_col.setOrientation(1)
        self.lyr_col.setPadding(self.dp(20), self.dp(24), self.dp(20), self.dp(24))
        self.lyr_sv.addView(self.lyr_col, self.LP(-1, -2))
        page.addView(self.lyr_sv, FLP(-1, -1))
        self.lyr_status = self._text("", 14, self.c_sub, gravity=17)
        self.lyr_status.setPadding(self.dp(24), 0, self.dp(24), 0)
        page.addView(self.lyr_status, FLP(-1, -2, 17))
        dp = self.dp
        btn = LL(self.act)
        btn.setOrientation(0)
        btn.setGravity(16)
        btn.setPadding(dp(12), dp(9), dp(16), dp(9))
        self.lyr_btn_bg = jclass("android.graphics.drawable.GradientDrawable")()
        self.lyr_btn_bg.setCornerRadius(float(dp(22)))
        btn.setBackground(self.lyr_btn_bg)
        self.lyr_btn_icon = self._glyph_icon(("msg_current_location", "msg_location"), self.c_accent, pad=0)
        btn.addView(self.lyr_btn_icon, self.LP(dp(18), dp(18)))
        self.lyr_btn_txt = self._text(strings("lyrics_resync"), 14, self.c_accent, bold=True, single=True)
        self.lyr_btn_txt.setPadding(dp(8), 0, 0, 0)
        btn.addView(self.lyr_btn_txt, self.LP(-2, -2))
        btn.setContentDescription(strings("lyrics_resync"))
        with tolerated():
            btn.setElevation(float(dp(6)))
        btn.setOnClickListener(self.Click(lambda v: self._lyr_resync()))
        with tolerated():
            self._press_fx(btn)
        btn.setVisibility(8)
        btn.setAlpha(0.0)
        page.addView(btn, FLP(-2, -2, 81))
        self.lyr_btn = btn
        self.lyr_btn_vis = False
        self.lyr_inset = None
        self.lyr_free = False
        self.lyr_touch = False
        self.lyr_moved = False
        self.lyr_down_y = 0.0
        self.lyr_last_user = 0.0
        self.lyr_last_y = 0
        self.lyr_anim = None
        self.lyr_coloranim = {}
        self._lyr_slop = float(int(jclass("android.view.ViewConfiguration").get(self.act).getScaledTouchSlop()))
        self.lyr_sv.setOnTouchListener(self.Touch(self._lyr_touch))
        self.lyr_sv.addOnLayoutChangeListener(_layoutchg_proxy()(self._lyr_sync_insets))
        self.lyr_run = self.Run(self._lyr_tick)
        self._lyr_running = False
        self.lyr_key = None
        self.lyr_data = None
        self.lyr_views = []
        self.lyr_active = -1
        self.lyr_word = -1
        self.lyr_stale = 0.0
        self.lyr_token = 0
        self.lyr_off = 0
        self.lyr_cache = {}
        return page
