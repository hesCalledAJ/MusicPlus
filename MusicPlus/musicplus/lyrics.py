import json
import random
import re
import threading
import time
import unicodedata
from .compat import dynamic_proxy, find_class, jclass, run_on_ui_thread


_LYR_KEY = "".join(random.choice("0123456789abcdef") for _ in range(32))
_LYR_RANK = {"word": 3, "line": 2, "plain": 1}


def _lyr_is_rtl(text, default=False):
    for ch in text or "":
        d = unicodedata.bidirectional(ch)
        if d in ("R", "AL"):
            return True
        if d == "L":
            return False
    return default


def _lyr_time(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        if s.endswith("ms"):
            return int(float(s[:-2]))
        if s.endswith("s"):
            return int(float(s[:-1]) * 1000)
        sec = 0.0
        for part in s.split(":"):
            sec = sec * 60 + float(part)
        return int(sec * 1000)
    except Exception:
        return None


def _lyr_finish(lines):
    lines = sorted((l for l in lines if l.get("t") is not None), key=lambda l: l["t"])
    for i, l in enumerate(lines):
        nxt = lines[i + 1]["t"] if i + 1 < len(lines) else None
        if l.get("e") is None or (nxt is not None and l["e"] > nxt + 2000):
            l["e"] = nxt if nxt is not None else l["t"] + 5000
    return lines


def _lyr_parse_ttml(xml_text):
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    ln = lambda tag: str(tag).rsplit("}", 1)[-1]
    def attr(el, name):
        for k, v in el.attrib.items():
            if k.rsplit("}", 1)[-1] == name:
                return v
        return None
    lines, any_word = [], False
    for p in root.iter():
        if ln(p.tag) != "p":
            continue
        toks = []
        def walk(el):
            if el.text:
                toks.append(("t", el.text))
            for ch in el:
                if ln(ch.tag) == "br":
                    toks.append(("t", " "))
                elif (attr(ch, "role") or "") in ("x-translation", "x-roman"):
                    pass
                else:
                    b, e = _lyr_time(attr(ch, "begin")), _lyr_time(attr(ch, "end"))
                    if b is not None and not any(True for _ in ch):
                        toks.append(("w", b, e, ch.text or ""))
                    else:
                        walk(ch)
                if ch.tail:
                    toks.append(("t", ch.tail))
        walk(p)
        words, text = [], ""
        for tk in toks:
            if tk[0] == "w":
                words.append([tk[1], tk[2], tk[3]])
                text += tk[3]
            else:
                text += tk[1]
                if words and tk[1][:1].isspace() and not words[-1][2].endswith(" "):
                    words[-1][2] += " "
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        t = _lyr_time(attr(p, "begin"))
        if t is None and words:
            t = words[0][0]
        e = _lyr_time(attr(p, "end"))
        line = {"t": t, "e": e, "text": text, "w": None}
        if len(words) >= 2 and t is not None and words[0][0] + 1000 < t:
            span = (e - t) if e is not None else 120000
            if words[-1][0] <= span + 500:
                words = [[a + t, (b + t if b is not None else None), c] for a, b, c in words]
        if len(words) >= 2:
            for i, w in enumerate(words):
                if w[1] is None:
                    w[1] = words[i + 1][0] if i + 1 < len(words) else (e or w[0] + 500)
            line["w"] = [tuple(w) for w in words]
            any_word = True
        lines.append(line)
    lines = _lyr_finish(lines)
    return ("word" if any_word else "line", lines) if lines else (None, [])


_LRC_TS = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")
_LRC_WORD = re.compile(r"(<\d+:\d+(?:\.\d+)?>)")


def _lyr_parse_lrc(text):
    lines, any_word = [], False
    for raw in str(text).splitlines():
        stamps, pos = [], 0
        while True:
            m = _LRC_TS.match(raw, pos)
            if not m:
                break
            stamps.append(int((int(m.group(1)) * 60 + float(m.group(2).replace(":", "."))) * 1000))
            pos = m.end()
        if not stamps:
            continue
        body = raw[pos:].strip()
        words = None
        if _LRC_WORD.search(body):
            parts = _LRC_WORD.split(body)
            cur, words = stamps[0], []
            for part in parts:
                if _LRC_WORD.fullmatch(part):
                    mm, ss = part[1:-1].split(":")
                    cur = int((int(mm) * 60 + float(ss)) * 1000)
                elif part.strip() and cur is not None:
                    words.append([cur, None, part])
                    cur = None
            for i, w in enumerate(words):
                w[1] = words[i + 1][0] if i + 1 < len(words) else None
            body = re.sub(r"\s+", " ", _LRC_WORD.sub("", body)).strip()
            words = [tuple(w) for w in words] if len(words) >= 2 else None
        for t in stamps:
            line = {"t": t, "e": None, "text": body, "w": words}
            if words:
                any_word = True
                line["e"] = words[-1][1]
            lines.append(line)
    lines = _lyr_finish(lines)
    for l in lines:
        if l["w"] and l["w"][-1][1] is None:
            l["w"] = [(a, b if b is not None else l["e"], c) for a, b, c in l["w"]]
    return ("word" if any_word else "line", lines) if lines else (None, [])


def _lyr_parse_plain(text):
    lines = [{"t": None, "e": None, "text": l.strip(), "w": None} for l in str(text).splitlines()]
    while lines and not lines[0]["text"]:
        lines.pop(0)
    while lines and not lines[-1]["text"]:
        lines.pop()
    return ("plain", lines) if lines else (None, [])


def _lyr_http_json(url, headers=None):
    conn = jclass("java.net.URL")(url).openConnection()
    conn.setConnectTimeout(8000)
    conn.setReadTimeout(10000)
    conn.setRequestProperty("User-Agent", "Mozilla/5.0")
    for k, v in (headers or {}).items():
        conn.setRequestProperty(k, v)
    if int(conn.getResponseCode()) != 200:
        return None
    stream = conn.getInputStream()
    try:
        sc = jclass("java.util.Scanner")(stream, "UTF-8").useDelimiter("\\A")
        return json.loads(str(sc.next())) if sc.hasNext() else None
    finally:
        stream.close()


def _lyr_http_text(url, headers=None):
    conn = jclass("java.net.URL")(url).openConnection()
    conn.setConnectTimeout(8000)
    conn.setReadTimeout(12000)
    conn.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36")
    conn.setRequestProperty("Accept-Language", "en-US,en;q=0.8")
    for k, v in (headers or {}).items():
        conn.setRequestProperty(k, v)
    if int(conn.getResponseCode()) != 200:
        return None
    stream = conn.getInputStream()
    try:
        sc = jclass("java.util.Scanner")(stream, "UTF-8").useDelimiter("\\A")
        return str(sc.next()) if sc.hasNext() else None
    finally:
        stream.close()


def _lyr_from_unison(title, artist, album, dur):
    import urllib.parse
    q = {"song": title, "artist": artist, "duration": str(int(dur))}
    if album:
        q["album"] = album
    data = _lyr_http_json("https://unison.betterlyrics.org/lyrics?" + urllib.parse.urlencode(q),
    {"x-key-id": _LYR_KEY})
    d = (data or {}).get("data") or {}
    body, fmt = d.get("lyrics"), d.get("format")
    if not body:
        return None
    if fmt == "ttml":
        kind, lines = _lyr_parse_ttml(body)
    elif fmt == "lrc":
        kind, lines = _lyr_parse_lrc(body)
    else:
        kind, lines = _lyr_parse_plain(body)
    return {"kind": kind, "lines": lines, "src": "Unison", "id": "unison"} if kind else None


def _lyr_from_lrclib(title, artist, album, dur):
    import urllib.parse
    q = {"track_name": title, "artist_name": artist, "duration": str(int(dur))}
    if album:
        q["album_name"] = album
    item = None
    try:
        item = _lyr_http_json("https://lrclib.net/api/get?" + urllib.parse.urlencode(q))
    except Exception:
        item = None
    if not item:
        hits = _lyr_http_json("https://lrclib.net/api/search?" + urllib.parse.urlencode(
       {"track_name": title, "artist_name": artist})) or []
        hits = [h for h in hits if h.get("syncedLyrics") or h.get("plainLyrics")]
        hits.sort(key=lambda h: (not h.get("syncedLyrics"), abs((h.get("duration") or 0) - dur)))
        item = hits[0] if hits and abs((hits[0].get("duration") or 0) - dur) <= 8 else None
    if not item:
        return None
    return _lyr_lrclib_result(item)


def _lyr_lrclib_result(item):
    rid = item.get("id")
    tag = ("lrclib:%s" % rid) if rid is not None else "lrclib"
    if item.get("syncedLyrics"):
        kind, lines = _lyr_parse_lrc(item["syncedLyrics"])
        if kind:
            return {"kind": kind, "lines": lines, "src": "LRCLIB", "id": tag}
    if item.get("plainLyrics"):
        kind, lines = _lyr_parse_plain(item["plainLyrics"])
        if kind:
            return {"kind": kind, "lines": lines, "src": "LRCLIB", "id": tag}
    return None


def _lyr_online(title, artist, album, dur):
    variants = _lyr_variants(title, artist)
    best = None
    for provider in (_lyr_from_unison, _lyr_from_lrclib):
        for t, a in variants:
            try:
                res = provider(t, a, album, dur)
            except Exception:
                res = None
            if res:
                if best is None or _LYR_RANK[res["kind"]] > _LYR_RANK[best["kind"]]:
                    best = res
                break
        if best and best["kind"] == "word":
            break
    if best is None:
        for fallback in (_lyr_genius_any, _lyr_ovh_any):
            try:
                best = fallback(title, artist, album, dur)
            except Exception:
                best = None
            if best:
                break
    return best


def _lyr_fetch(title, artist, album, dur, embedded=None, online=True, early=None, prefer=None):
    if prefer and (online or prefer == "local"):
        res = _lyr_by_id(prefer, title, artist, album, dur, embedded)
        if res:
            return res
    if not online:
        return embedded
    if embedded and embedded["kind"] == "word":
        return embedded
    if embedded and early is not None:
        try:
            early(embedded)
        except Exception:
            pass
    res = _lyr_online(title, artist, album, dur)
    if res is None or (embedded and _LYR_RANK[res["kind"]] <= _LYR_RANK[embedded["kind"]]):
        return embedded or res
    return res


_BRACKETS = r"\s*[\(\[\{\u00ab\uff08][^\)\]\}\u00bb\uff09]*[\)\]\}\u00bb\uff09]"
_ARTIST_SPLIT = r"\s*(?:,|&|/|;|\u060c|\u061b|\bfeat\.?|\bft\.?|\bwith\b|\s\u0648\s)\s*"


def _lyr_variants(title, artist):
    title, artist = (title or "").strip(), (artist or "").strip()
    clean_t = re.sub(_BRACKETS, "", title).strip() or title
    clean_t = re.sub(r"\s+-\s+(remaster|live|single|radio|mono|stereo).*$", "", clean_t, flags=re.I)
    first_a = re.split(_ARTIST_SPLIT, artist, flags=re.I)[0].strip() or artist
    return list(dict.fromkeys([(title, artist), (clean_t, first_a)]))


def _lyr_candidates(title, artist, album, dur, embedded=None, online=True):
    import urllib.parse
    out, seen = [], set()
    def add(res, note=""):
        if res and res.get("id") not in seen:
            seen.add(res.get("id"))
            res = dict(res)
            res["note"] = note
            out.append(res)
    if embedded:
        e = dict(embedded)
        e["id"] = "local"
        add(e)
    if not online:
        return out
    for t, a in _lyr_variants(title, artist):
        try:
            add(_lyr_from_unison(t, a, album, dur))
        except Exception:
            pass
        if "unison" in seen:
            break
    hits = []
    for t, a in _lyr_variants(title, artist):
        try:
            got = _lyr_http_json("https://lrclib.net/api/search?" + urllib.parse.urlencode(
           {"track_name": t, "artist_name": a})) or []
        except Exception:
            got = []
        hits = [h for h in got if h.get("syncedLyrics") or h.get("plainLyrics")]
        if hits:
            break
    hits.sort(key=lambda h: (not h.get("syncedLyrics"), abs((h.get("duration") or 0) - dur)))
    for h in hits[:6]:
        d = int(h.get("duration") or 0)
        note = ("%d:%02d" % (d // 60, d % 60)) if d else ""
        add(_lyr_lrclib_result(h), note)
    with_ovh = None
    try:
        with_ovh = _lyr_ovh_any(title, artist, album, dur)
    except Exception:
        pass
    add(with_ovh)
    try:
        for g in _lyr_genius_all(title, artist, 2):
            add(g, g.get("note", ""))
    except Exception:
        pass
    return out


def _lyr_by_id(pid, title, artist, album, dur, embedded=None):
    if pid == "local":
        return embedded
    if pid == "unison":
        for t, a in _lyr_variants(title, artist):
            try:
                res = _lyr_from_unison(t, a, album, dur)
            except Exception:
                res = None
            if res:
                return res
        return None
    if pid == "ovh":
        return _lyr_ovh_any(title, artist, album, dur)
    if pid == "genius" or (pid and pid.startswith("genius:")):
        sid = pid.split(":", 1)[1] if ":" in pid else ""
        res = None
        if sid.isdigit():
            try:
                res = _lyr_genius_result(sid, "https://genius.com/songs/" + sid)
            except Exception:
                res = None
        return res or _lyr_genius_any(title, artist, album, dur)
    if pid and pid.startswith("lrclib:"):
        try:
            item = _lyr_http_json("https://lrclib.net/api/get/" + pid.split(":", 1)[1])
        except Exception:
            item = None
        return _lyr_lrclib_result(item) if item else None
    return None


_FA_FIX = {ord(a): b for a, b in {
    "\u064a": "\u06cc", "\u0649": "\u06cc", "\u0626": "\u06cc", "\u0643": "\u06a9", "\u0629": "\u0647",
    "\u06c0": "\u0647", "\u06d5": "\u0647", "\u06c1": "\u0647", "\u06be": "\u0647", "\u0624": "\u0648",
    "\u0623": "\u0627", "\u0625": "\u0627", "\u0671": "\u0627", "\u0622": "\u0627"}.items()}


def _lyr_norm(s):
    out = []
    for ch in unicodedata.normalize("NFKD", s or "").lower():
        cat = unicodedata.category(ch)
        if cat in ("Mn", "Me", "Cf") or ch == "\u0640":
            continue
        if cat == "Nd":
            out.append(str(unicodedata.digit(ch, 0)))
        else:
            out.append(_FA_FIX.get(ord(ch), ch))
    return re.sub(r"[^\w]+", " ", "".join(out)).strip()


def _lyr_compact(s):
    return _lyr_norm(s).replace(" ", "")


def _lyr_script(s):
    for ch in s or "":
        o = ord(ch)
        if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0xFB50 <= o <= 0xFEFF:
            return "ar"
        if ch.isalpha() and o < 0x250:
            return "lat"
    return None


def _lyr_close(a, b, ratio=0.82):
    ca, cb = _lyr_compact(a), _lyr_compact(b)
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    short, long_ = sorted((ca, cb), key=len)
    if len(short) >= 3 and short in long_:
        return True
    import difflib
    return difflib.SequenceMatcher(None, ca, cb).ratio() >= ratio


def _lyr_from_ovh(title, artist, album, dur):
    import urllib.parse
    if not title or not artist:
        return None
    data = _lyr_http_json("https://api.lyrics.ovh/v1/%s/%s" % (
        urllib.parse.quote(artist, safe=""), urllib.parse.quote(title, safe="")))
    text = ((data or {}).get("lyrics") or "").replace("\r\n", "\n").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        return None
    kind, lines = _lyr_parse_plain(text)
    return {"kind": kind, "lines": lines, "src": "lyrics.ovh", "id": "ovh"} if kind else None


def _lyr_ovh_any(title, artist, album, dur):
    for t, a in _lyr_variants(title, artist):
        try:
            res = _lyr_from_ovh(t, a, album, dur)
        except Exception:
            res = None
        if res:
            return res
    return None


def _lyr_genius_page_text(html_text):
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            HTMLParser.__init__(self, convert_charrefs=True)
            self.depth = 0
            self.skip = 0
            self.out = []

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if self.depth == 0:
                if tag == "div" and a.get("data-lyrics-container") == "true":
                    self.depth = 1
                    if self.out:
                        self.out.append("\n")
                return
            if tag == "br":
                if not self.skip:
                    self.out.append("\n")
                return
            if tag in ("img", "hr", "input", "meta", "link", "wbr"):
                return
            self.depth += 1
            if self.skip:
                self.skip += 1
            elif a.get("data-exclude-from-selection") == "true":
                self.skip = 1

        def handle_startendtag(self, tag, attrs):
            if self.depth and tag == "br" and not self.skip:
                self.out.append("\n")

        def handle_endtag(self, tag):
            if not self.depth or tag == "br":
                return
            if tag in ("img", "hr", "input", "meta", "link", "wbr"):
                return
            if self.skip:
                self.skip -= 1
            self.depth -= 1

        def handle_data(self, data):
            if self.depth and not self.skip:
                self.out.append(data)

    p = P()
    p.feed(html_text or "")
    text = "".join(p.out).replace("\r", "").replace("\xa0", " ")
    text = "\n".join(l.rstrip() for l in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_GENIUS = {"wv": False}
_WV_LOCK = threading.Lock()
_JS_JSON = ("(function(){var b=document.body;var t=b?(b.innerText||''):'';t=t.trim();"
            "return t.charAt(0)==='{'?t:'';})()")
_JS_LYRICS = ("(function(){var c=document.querySelectorAll('[data-lyrics-container=\"true\"]');var o='';"
              "for(var i=0;i<c.length;i++){o+=c[i].outerHTML;}return o;})()")


def _lyr_wv_eval(url, js, timeout=20.0):
    ctx = find_class("org.telegram.messenger.ApplicationLoader").applicationContext
    st = {"wv": None, "val": None, "err": None}

    class CB(dynamic_proxy(jclass("android.webkit.ValueCallback"))):
        def __init__(self):
            super().__init__()

        def onReceiveValue(self, v):
            st["val"] = "" if v is None else str(v)

    cb = CB()

    def make():
        try:
            wv = jclass("android.webkit.WebView")(ctx)
            s = wv.getSettings()
            s.setJavaScriptEnabled(True)
            s.setDomStorageEnabled(True)
            try:
                s.setBlockNetworkImage(True)
                s.setUserAgentString(str(s.getUserAgentString()).replace("; wv", ""))
                wv.setWebViewClient(jclass("android.webkit.WebViewClient")())
            except Exception:
                pass
            wv.loadUrl(url)
            st["wv"] = wv
        except Exception as e:
            st["err"] = "%s: %s" % (type(e).__name__, e)

    def ev(script):
        def go():
            try:
                st["val"] = None
                st["wv"].evaluateJavascript(script, cb)
            except Exception as e:
                st["err"] = "%s: %s" % (type(e).__name__, e)
        run_on_ui_thread(go)

    def decode(raw):
        try:
            v = json.loads(raw or "")
        except Exception:
            return ""
        return v if isinstance(v, str) else ""

    def wait_val(sec):
        end = time.time() + sec
        while time.time() < end and st["val"] is None and not st["err"]:
            time.sleep(0.05)
        return decode(st["val"])

    with _WV_LOCK:
        try:
            run_on_ui_thread(make)
            t0 = time.time()
            while time.time() - t0 < 4 and st["wv"] is None and st["err"] is None:
                time.sleep(0.05)
            if st["wv"] is None or st["err"]:
                return None
            time.sleep(1.0)
            end = t0 + timeout
            while time.time() < end and not st["err"]:
                ev(js)
                out = wait_val(1.2)
                if out:
                    return out
                time.sleep(0.5)
            return None
        finally:
            def kill():
                try:
                    wv = st["wv"]
                    if wv is not None:
                        wv.stopLoading()
                        wv.destroy()
                except Exception:
                    pass
            try:
                run_on_ui_thread(kill)
            except Exception:
                pass


def _lyr_genius_json(url):
    if not _GENIUS["wv"]:
        try:
            data = _lyr_http_json(url, {"Accept": "application/json, text/plain, */*", "Referer": "https://genius.com/"})
        except json.JSONDecodeError:
            data = None
        if data is not None:
            return data
        _GENIUS["wv"] = True
    raw = _lyr_wv_eval(url, _JS_JSON, 20.0)
    return json.loads(raw) if raw else None


def _lyr_genius_page(url):
    if not _GENIUS["wv"]:
        try:
            page = _lyr_http_text(url, {"Accept": "text/html,application/xhtml+xml", "Referer": "https://genius.com/"})
        except Exception:
            page = None
        if page and "data-lyrics-container" in page:
            return page
        _GENIUS["wv"] = True
    return _lyr_wv_eval(url, _JS_LYRICS, 25.0)


def _lyr_genius_query(q):
    import urllib.parse
    data = _lyr_genius_json("https://genius.com/api/search/song?per_page=10&q=" + urllib.parse.quote(q))
    hits = []
    for sec in ((data or {}).get("response") or {}).get("sections") or []:
        for h in sec.get("hits") or []:
            r = h.get("result") or {}
            if h.get("type") not in (None, "song") or not r.get("id") or not r.get("url"):
                continue
            hits.append(r)
    return hits


def _lyr_genius_search(title, artist):
    if not title:
        return []
    queries = list(dict.fromkeys(q for q in (("%s %s" % (artist or "", title)).strip(), title.strip()) if q))
    for q in queries:
        scored = []
        for r in _lyr_genius_query(q):
            by_raw = r.get("artist_names") or (r.get("primary_artist") or {}).get("name") or ""
            by = _lyr_norm(by_raw)
            if by.startswith("genius") or r.get("lyrics_state") not in (None, "complete"):
                continue
            rts = [x for x in (r.get("title"), r.get("title_with_featured")) if x]
            t_exact = any(_lyr_compact(x) == _lyr_compact(title) for x in rts)
            if not (t_exact or any(_lyr_close(x, title) for x in rts)):
                continue
            sa, sb = _lyr_script(artist), _lyr_script(by_raw)
            if not artist or not by_raw or (sa and sb and sa != sb):
                a_rank = 1 if t_exact else 2
            elif _lyr_close(artist, by_raw) or any(w in by for w in _lyr_norm(artist).split() if len(w) > 2):
                a_rank = 0
            else:
                continue
            scored.append((0 if t_exact else 1, a_rank, r))
        scored.sort(key=lambda x: (x[0] + x[1], x[0]))
        if scored:
            return [(r["id"], r["url"], ("%s - %s" % (r.get("artist_names") or "", r.get("title") or "")).strip(" -"))
                    for _, _, r in scored]
    return []


def _lyr_genius_result(sid, url):
    page = _lyr_genius_page(url)
    text = _lyr_genius_page_text(page) if page else ""
    if not text or len(text) < 20:
        return None
    kind, lines = _lyr_parse_plain(text)
    return {"kind": kind, "lines": lines, "src": "Genius", "id": "genius:%s" % sid} if kind else None


def _lyr_genius_all(title, artist, limit=2):
    out, seen = [], set()
    for t, a in _lyr_variants(title, artist):
        try:
            hits = _lyr_genius_search(t, a)
        except Exception:
            hits = []
        for sid, url, label in hits:
            if sid in seen:
                continue
            seen.add(sid)
            try:
                res = _lyr_genius_result(sid, url)
            except Exception:
                res = None
            if res:
                res["note"] = label
                out.append(res)
            if len(out) >= limit:
                return out
        if out:
            break
    return out


def _lyr_genius_any(title, artist, album, dur):
    got = _lyr_genius_all(title, artist, 1)
    return got[0] if got else None


def _lyr_word_ends(line):
    ends = line.get("_ends")
    if ends is not None:
        return ends
    text, pos, ends = line["text"], 0, []
    for w in line["w"]:
        wt = re.sub(r"\s+", " ", (w[2] or "")).strip()
        if wt:
            i = text.find(wt, pos)
            pos = i + len(wt) if i >= 0 else min(len(text), pos + len(wt))
        ends.append(pos)
    if ends:
        ends[-1] = len(text)
    line["_ends"] = ends
    return ends
