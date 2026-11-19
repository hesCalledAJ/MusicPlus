import struct

from .lyrics import _lyr_parse_lrc, _lyr_parse_plain, _lyr_finish, _LRC_TS

SRC = "File tags"
_MAX_TAG = 16 * 1024 * 1024
_VORBIS_KEYS = ("SYNCEDLYRICS", "LYRICS", "UNSYNCEDLYRICS", "UNSYNCED LYRICS", "LYRICSENG", "LYRICS_SYNCED")
_ID3_TXXX = ("LYRICS", "UNSYNCEDLYRICS", "SYNCEDLYRICS", "UNSYNCED LYRICS")


def _result(text):
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip("\ufeff\x00 \n")
    if not text.strip():
        return None
    if _LRC_TS.search(text):
        kind, lines = _lyr_parse_lrc(text)
        if kind:
            return {"kind": kind, "lines": lines, "src": SRC}
    kind, lines = _lyr_parse_plain(text)
    return {"kind": kind, "lines": lines, "src": SRC} if kind else None


def _better(a, b):
    rank = {"word": 3, "line": 2, "plain": 1}
    if b is None:
        return a
    if a is None or rank[b["kind"]] > rank[a["kind"]]:
        return b
    return a


def _dec(data, enc):
    try:
        if enc == 0:
            return data.decode("latin-1")
        if enc == 1:
            return data.decode("utf-16")
        if enc == 2:
            return data.decode("utf-16-be")
        return data.decode("utf-8")
    except Exception:
        return data.decode("utf-8", "replace")


def _split_term(data, enc):
    if enc in (1, 2):
        i = 0
        while i + 1 < len(data):
            if data[i] == 0 and data[i + 1] == 0 and i % 2 == 0:
                return data[:i], data[i + 2:]
            i += 1
        return data, b""
    i = data.find(b"\x00")
    return (data, b"") if i < 0 else (data[:i], data[i + 1:])


def _sylt(body):
    enc = body[0]
    fmt = body[4]
    if fmt != 2:
        return None
    _desc, rest = _split_term(body[6:], enc)
    out = []
    while rest:
        if enc in (1, 2):
            i = 0
            while i + 1 < len(rest) and not (rest[i] == 0 and rest[i + 1] == 0 and i % 2 == 0):
                i += 1
            raw, rest = rest[:i], rest[i + 2:]
        else:
            i = rest.find(b"\x00")
            if i < 0:
                break
            raw, rest = rest[:i], rest[i + 1:]
        if len(rest) < 4:
            break
        t = struct.unpack(">I", rest[:4])[0]
        rest = rest[4:]
        text = _dec(raw, enc).replace("\n", " ").strip()
        out.append({"t": t, "e": None, "text": text, "w": None})
    lines = _lyr_finish([l for l in out if l["text"]])
    return {"kind": "line", "lines": lines, "src": SRC} if lines else None


def _uslt(body):
    enc = body[0]
    _desc, rest = _split_term(body[4:], enc)
    return _result(_dec(rest, enc))


def _txxx(body):
    enc = body[0]
    desc, rest = _split_term(body[1:], enc)
    if _dec(desc, enc).strip().upper() in _ID3_TXXX:
        return _result(_dec(rest, enc))
    return None


def _from_id3(f):
    head = f.read(10)
    if len(head) < 10 or head[:3] != b"ID3":
        return None
    ver, flags = head[3], head[5]
    size = (head[6] << 21) | (head[7] << 14) | (head[8] << 7) | head[9]
    if size <= 0 or size > _MAX_TAG:
        return None
    tag = f.read(size)
    if flags & 0x80 and ver < 4:
        tag = tag.replace(b"\xff\x00", b"\xff")
    pos = 0
    if flags & 0x40 and len(tag) >= 4:
        n = (struct.unpack(">I", tag[:4])[0] if ver == 3
             else (tag[0] << 21) | (tag[1] << 14) | (tag[2] << 7) | tag[3])
        pos = n + (4 if ver == 3 else 0)
    idlen, hdr = (3, 6) if ver == 2 else (4, 10)
    names = {"USLT": _uslt, "SYLT": _sylt, "TXXX": _txxx, "USL": _uslt, "SLT": _sylt, "TXX": _txxx}
    best = None
    while pos + hdr <= len(tag):
        fid = tag[pos:pos + idlen]
        if fid[:1] == b"\x00":
            break
        if ver == 2:
            fsz = int.from_bytes(tag[pos + 3:pos + 6], "big")
            fl = 0
        elif ver == 3:
            fsz = struct.unpack(">I", tag[pos + 4:pos + 8])[0]
            fl = int.from_bytes(tag[pos + 8:pos + 10], "big")
        else:
            b = tag[pos + 4:pos + 8]
            fsz = (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]
            fl = int.from_bytes(tag[pos + 8:pos + 10], "big")
        body = tag[pos + hdr:pos + hdr + fsz]
        pos += hdr + fsz
        fn = names.get(fid.decode("latin-1"))
        if fn is None or not body:
            continue
        if ver == 4:
            if fl & 0x000C:
                continue
            if fl & 0x0001:
                body = body[4:]
            if fl & 0x0002:
                body = body.replace(b"\xff\x00", b"\xff")
        elif ver == 3 and fl & 0x00C0:
            continue
        try:
            best = _better(best, fn(body))
        except Exception:
            continue
    return best


def _vorbis_comments(buf):
    best = None
    try:
        n = struct.unpack("<I", buf[:4])[0]
        pos = 4 + n
        count = struct.unpack("<I", buf[pos:pos + 4])[0]
        pos += 4
        for _ in range(count):
            ln = struct.unpack("<I", buf[pos:pos + 4])[0]
            item = buf[pos + 4:pos + 4 + ln].decode("utf-8", "replace")
            pos += 4 + ln
            key, _, val = item.partition("=")
            if key.strip().upper() in _VORBIS_KEYS:
                best = _better(best, _result(val))
    except Exception:
        pass
    return best


def _from_flac(f):
    if f.read(4) != b"fLaC":
        return None
    best = None
    while True:
        h = f.read(4)
        if len(h) < 4:
            break
        last, typ = h[0] & 0x80, h[0] & 0x7F
        ln = int.from_bytes(h[1:4], "big")
        if ln > _MAX_TAG:
            break
        if typ == 4:
            best = _better(best, _vorbis_comments(f.read(ln)))
        else:
            f.seek(ln, 1)
        if last:
            break
    return best


def _from_ogg(f):
    packet, packets, read = b"", [], 0
    while len(packets) < 2 and read < _MAX_TAG:
        h = f.read(27)
        if len(h) < 27 or h[:4] != b"OggS":
            break
        segs = f.read(h[26])
        body = f.read(sum(segs))
        read += 27 + len(segs) + len(body)
        o = 0
        for s in segs:
            packet += body[o:o + s]
            o += s
            if s < 255:
                packets.append(packet)
                packet = b""
    for p in packets:
        if p[:7] == b"\x03vorbis":
            return _vorbis_comments(p[7:])
        if p[:8] == b"OpusTags":
            return _vorbis_comments(p[8:])
    return None


def _mp4_boxes(buf, start=0, end=None):
    end = len(buf) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, typ = struct.unpack(">I4s", buf[pos:pos + 8])
        hdr = 8
        if size == 1 and pos + 16 <= end:
            size, hdr = struct.unpack(">Q", buf[pos + 8:pos + 16])[0], 16
        elif size == 0:
            size = end - pos
        if size < hdr:
            break
        yield typ, pos + hdr, min(pos + size, end)
        pos += size


def _from_mp4(f):
    f.seek(0, 2)
    total = f.tell()
    f.seek(0)
    pos = 0
    while pos + 8 <= total:
        f.seek(pos)
        h = f.read(16)
        size, typ = struct.unpack(">I4s", h[:8])
        if size == 1:
            size = struct.unpack(">Q", h[8:16])[0]
        elif size == 0:
            size = total - pos
        if size < 8:
            return None
        if typ == b"moov":
            if size > _MAX_TAG:
                return None
            f.seek(pos)
            return _mp4_lyrics(f.read(size))
        pos += size
    return None


def _mp4_lyrics(moov):
    best = None
    def find(start, end, path):
        for typ, s, e in _mp4_boxes(moov, start, end):
            if typ == path[0]:
                if len(path) == 1:
                    yield s, e
                else:
                    yield from find(s + (4 if typ == b"meta" else 0), e, path[1:])
    for s, e in find(0, len(moov), [b"moov", b"udta", b"meta", b"ilst", b"\xa9lyr"]):
        for typ, ds, de in _mp4_boxes(moov, s, e):
            if typ == b"data":
                best = _better(best, _result(moov[ds + 8:de].decode("utf-8", "replace")))
    return best


def read(path):
    try:
        with open(path, "rb") as f:
            head = f.read(12)
            f.seek(0)
            if head[:3] == b"ID3":
                return _from_id3(f)
            if head[:4] == b"fLaC":
                return _from_flac(f)
            if head[:4] == b"OggS":
                return _from_ogg(f)
            if head[4:8] == b"ftyp":
                return _from_mp4(f)
    except Exception:
        pass
    return None
