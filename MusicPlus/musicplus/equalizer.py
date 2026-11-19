import json
import math
import time

from .compat import get_private_field, jclass
from .safe import tolerated

EQ_FREQS = (60, 230, 910, 3600, 14000)
EQ_MIN_DB = -12.0
EQ_MAX_DB = 12.0
EQ_STEP_DB = 0.5

EQ_PRESETS = (
 ("flat", "eq_flat", (0, 0, 0, 0, 0)),
 ("bass", "eq_bass_boost", (6, 4, 0, 0, 0)),
 ("treble", "eq_treble_boost", (0, 0, 0, 4, 6)),
 ("vocal", "eq_vocal", (-2, -1, 3, 3, 1)),
 ("rock", "eq_rock", (5, 3, -1, 3, 5)),
 ("pop", "eq_pop", (-1, 2, 4, 2, -1)),
 ("jazz", "eq_jazz", (4, 2, -2, 2, 4)),
 ("classical", "eq_classical", (4, 3, -2, 3, 4)),
 ("electronic", "eq_electronic", (5, 4, 0, 2, 4)),
 ("hiphop", "eq_hip_hop", (6, 4, 0, 1, 3)),
 ("acoustic", "eq_acoustic", (4, 3, 1, 2, 3)),
 ("lounge", "eq_lounge", (-3, -1, 2, 1, -1)),
)

_DEFAULT_GAINS = (0.0,) * len(EQ_FREQS)


def clamp_db(v):
    return max(EQ_MIN_DB, min(EQ_MAX_DB, float(v)))


def preset_gains(key):
    for k, _s, g in EQ_PRESETS:
        if k == key:
            return tuple(float(x) for x in g)
    return None


def match_preset(gains):
    for k, _s, g in EQ_PRESETS:
        if all(abs(float(a) - float(b)) < 0.01 for a, b in zip(g, gains)):
            return k
    return ""


def curve_at(gains, hz):
    f = max(float(hz), 1.0)
    if f <= EQ_FREQS[0]:
        return float(gains[0])
    if f >= EQ_FREQS[-1]:
        return float(gains[-1])
    for i in range(len(EQ_FREQS) - 1):
        lo, hi = EQ_FREQS[i], EQ_FREQS[i + 1]
        if lo <= f <= hi:
            t = (math.log(f) - math.log(lo)) / (math.log(hi) - math.log(lo))
            t = t * t * (3.0 - 2.0 * t)
            return float(gains[i]) * (1.0 - t) + float(gains[i + 1]) * t
    return 0.0


def freq_label(hz):
    return f"{hz / 1000:g} kHz" if hz >= 1000 else f"{hz} Hz"


class _EqEngine:

    def __init__(self, plugin):
        self.p = plugin
        self.session = 0
        self.player_id = None
        self.eq = None
        self.bass = None
        self.virt = None
        self.loud = None
        self.supported = None
        self.alive = True
        self._key = None
        self.why = ""

    def _get(self, key, default):
        try:
            return self.p.get_setting(key, default)
        except Exception:
            return default

    def is_on(self):
        return bool(self._get("eq_on", False))

    def set_on(self, v):
        self.p.set_setting("eq_on", bool(v))

    def gains(self):
        try:
            raw = [float(x) for x in str(self._get("eq_gains", "")).split(",") if x.strip() != ""]
        except Exception:
            raw = []
        if len(raw) != len(EQ_FREQS):
            raw = list(_DEFAULT_GAINS)
        return tuple(clamp_db(x) for x in raw)

    def set_gains(self, gains, preset=None):
        g = tuple(round(clamp_db(x) / EQ_STEP_DB) * EQ_STEP_DB for x in gains)
        self.p.set_setting("eq_gains", ",".join(f"{x:g}" for x in g))
        self.p.set_setting("eq_preset", match_preset(g) if preset is None else preset)

    def set_band(self, i, db):
        g = list(self.gains())
        g[i] = db
        self.set_gains(g)

    USER_MAX = 30

    def user_presets(self):
        try:
            raw = json.loads(self._get("eq_user_presets", "") or "[]")
        except Exception:
            raw = []
        out = []
        for d in raw if isinstance(raw, list) else []:
            try:
                g = tuple(clamp_db(x) for x in d["gains"])
                if len(g) == len(EQ_FREQS) and str(d["id"]) and str(d["name"]).strip():
                    out.append({"id": str(d["id"]), "name": str(d["name"]).strip(), "gains": g})
            except Exception:
                continue
        return out

    def _store_user(self, lst):
        self.p.set_setting("eq_user_presets", json.dumps(
            [{"id": d["id"], "name": d["name"], "gains": list(d["gains"])} for d in lst], separators=(",", ":")))

    def user_preset(self, key):
        for d in self.user_presets():
            if "u:" + d["id"] == key:
                return d
        return None

    def save_user_preset(self, name, gains):
        name = str(name).strip()[:60]
        g = tuple(round(clamp_db(x) / EQ_STEP_DB) * EQ_STEP_DB for x in gains)
        lst = self.user_presets()
        hit = next((d for d in lst if d["name"].lower() == name.lower()), None)
        if hit is not None:
            lst.remove(hit)
            hit = {"id": hit["id"], "name": name, "gains": g}
        else:
            n = int(time.time() * 1000)
            used = {d["id"] for d in lst}
            while "%x" % n in used:
                n += 1
            hit = {"id": "%x" % n, "name": name, "gains": g}
        lst.insert(0, hit)
        self._store_user(lst[:self.USER_MAX])
        return "u:" + hit["id"]

    def delete_user_preset(self, key):
        self._store_user([d for d in self.user_presets() if "u:" + d["id"] != key])
        if str(self._get("eq_preset", "") or "") == key:
            self.p.set_setting("eq_preset", match_preset(self.gains()))

    def preset(self):
        g = self.gains()
        key = str(self._get("eq_preset", "") or "")
        if key.startswith("u:"):
            d = self.user_preset(key)
            if d is not None and d["gains"] == g:
                return key
        elif key and preset_gains(key) == g:
            return key
        m = match_preset(g)
        if m:
            return m
        for d in self.user_presets():
            if d["gains"] == g:
                return "u:" + d["id"]
        return ""

    def level(self, name):
        try:
            return max(0, min(100, int(self._get(name, 0))))
        except Exception:
            return 0

    def set_level(self, name, v):
        self.p.set_setting(name, max(0, min(100, int(round(v)))))

    def is_default(self):
        return (not self.is_on() and all(abs(x) < 0.01 for x in self.gains())
          and not (self.level("eq_bass") or self.level("eq_virt") or self.level("eq_loud")))

    def reset(self):
        self.set_on(False)
        self.set_gains(_DEFAULT_GAINS, "flat")
        for k in ("eq_bass", "eq_virt", "eq_loud"):
            self.p.set_setting(k, 0)
        self.sync()

    def _player(self):
        xf = getattr(self.p, "_xf", None)
        pl = xf.get("audioPlayer") if xf is not None else None
        if pl is None:
            with tolerated():
                mc = self.p._get_mc()
                pl = get_private_field(mc, "audioPlayer")
        return pl


    @staticmethod
    def _field(obj, name, kind="int"):
        if obj is None:
            return None
        c = obj.getClass()
        while c is not None:
            try:
                f = c.getDeclaredField(name)
                f.setAccessible(True)
                return f.getInt(obj) if kind == "int" else f.get(obj)
            except Exception:
                pass
            c = c.getSuperclass()
        return None


    def _exo(self, pl):
        ex = None
        with tolerated():
            ex = get_private_field(pl, "player")
        return ex

    def _session_of(self, pl):
        ex = self._exo(pl)
        if ex is None:
            self.why = "no player field"
            return 0
        with tolerated():
            f = ex.getClass().getDeclaredField("audioSessionIdState")
            f.setAccessible(True)
            v = f.get(ex)
            if v is not None and not isinstance(v, (int, float)):
                v = v.get()
            sid = int(v) if v is not None else 0
            if sid > 0:
                self.why = ""
                return sid
        self.why = "no session id"
        return 0

    def release(self):
        for name in ("eq", "bass", "virt", "loud"):
            fx = getattr(self, name)
            setattr(self, name, None)
            if fx is not None:
                with tolerated():
                    fx.setEnabled(False)
                with tolerated():
                    fx.release()
        self.session = 0
        self.player_id = None
        self._key = None

    def active(self):
        return bool(self._wanted())

    def _wanted(self):
        return self.is_on()

    def _make(self, cls_name, sid, *a):
        try:
            return jclass("android.media.audiofx." + cls_name)(*a, sid) if a else jclass("android.media.audiofx." + cls_name)(sid)
        except Exception:
            return None

    def _attach(self, pl, sid):
        self.release()
        self.eq = self._make("Equalizer", sid, 0)
        self.bass = self._make("BassBoost", sid, 0)
        self.virt = self._make("Virtualizer", sid, 0)
        self.loud = self._make("LoudnessEnhancer", sid)
        self.session = sid
        self.player_id = str(pl.hashCode())
        self.supported = any(x is not None for x in (self.eq, self.bass, self.virt, self.loud))
        if not self.supported:
            self.why = "effects not supported on this device"
        elif self.eq is None:
            self.why = "equalizer effect missing"
        else:
            self.why = ""

    def sync(self):
        if not self.alive:
            return
        with tolerated():
            if not self._wanted():
                if self.eq or self.bass or self.virt or self.loud:
                    self.release()
                return
            pl = self._player()
            if pl is None:
                return
            sid = self._session_of(pl)
            if sid <= 0:
                self.supported = False
                return
            if sid != self.session or str(pl.hashCode()) != self.player_id:
                self._attach(pl, sid)
            key = (sid, self.player_id, self.is_on(), self.gains(),
              self.level("eq_bass"), self.level("eq_virt"), self.level("eq_loud"))
            if key == self._key:
                return
            self._push()
            self._key = key

    def _push(self):
        on = self.is_on()
        if self.eq is not None:
            with tolerated():
                self._push_bands(on)
        if self.bass is not None:
            with tolerated():
                lv = self.level("eq_bass")
                if self.bass.getStrengthSupported():
                    self.bass.setStrength(lv * 10)
                self.bass.setEnabled(lv > 0)
        if self.virt is not None:
            with tolerated():
                lv = self.level("eq_virt")
                if self.virt.getStrengthSupported():
                    self.virt.setStrength(lv * 10)
                self.virt.setEnabled(lv > 0)
        if self.loud is not None:
            with tolerated():
                lv = self.level("eq_loud")
                self.loud.setTargetGain(int(lv * 8))
                self.loud.setEnabled(lv > 0)

    def _push_bands(self, on):
        eq = self.eq
        rng = eq.getBandLevelRange()
        lo, hi = int(rng[0]), int(rng[1])
        g = self.gains()
        for b in range(int(eq.getNumberOfBands())):
            hz = float(eq.getCenterFreq(b)) / 1000.0
            mb = int(round(curve_at(g, hz) * 100.0)) if on else 0
            eq.setBandLevel(b, max(lo, min(hi, mb)))
        eq.setEnabled(bool(on))

    def stop(self):
        self.alive = False
        self.release()
