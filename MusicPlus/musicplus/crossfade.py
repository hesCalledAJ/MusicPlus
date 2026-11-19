import math
import time
from .compat import (
 MethodHook,
 dynamic_proxy,
 find_class,
 jarray,
 jclass,
 jfloat,
 run_on_ui_thread,
)
from . import reflect
from .safe import tolerated


def _xf_gain(x, eq):
    x = min(max(x, 0.0), 1.0)
    return math.sin(x * math.pi / 2) if eq else x


_XF_MUTE = None


def _xf_mute():
    global _XF_MUTE
    if _XF_MUTE is None:
        D = jclass("org.telegram.ui.Components.VideoPlayer$AudioVisualizerDelegate")
        class Mute(dynamic_proxy(D)):
            def onVisualizerUpdate(self, playing, animate, values):
                pass
            def needUpdate(self):
                return False
        _XF_MUTE = Mute
    return _XF_MUTE()


def _xf_widest(name):
    cls = reflect.jcls("org.telegram.messenger.MediaController")
    best = None
    try:
        for m in cls.getDeclaredMethods():
            if str(m.getName()) == name and (best is None or int(m.getParameterCount()) > int(best.getParameterCount())):
                best = m
    except Exception:
        return None
    if best is not None:
        best.setAccessible(True)
    return best


class _XfHook(MethodHook):
    def __init__(self, before=None, after=None):
        self._before = before
        self._after = after
    def before_hooked_method(self, param):
        if self._before is not None:
            with tolerated():
                self._before(param)
    def after_hooked_method(self, param):
        if self._after is not None:
            with tolerated():
                self._after(param)


class _XfTail:
    def __init__(self, player, vol, ms, eq):
        self.pl = player
        self.v0 = vol
        self.ms = max(int(ms), 1)
        self.eq = eq
        self.t0 = time.monotonic()
        self.done = False
    def left(self):
        return 1.0 - (time.monotonic() - self.t0) * 1000.0 / self.ms
    def rush(self):
        k = self.left()
        if k * self.ms <= 250:
            return
        self.v0 *= _xf_gain(k, self.eq)
        self.ms = 250
        self.eq = False
        self.t0 = time.monotonic()
    def drop(self):
        if self.done:
            return
        self.done = True
        with tolerated():
            self.pl.releasePlayer(True)
    def step(self, duck):
        if self.done:
            return False
        k = self.left()
        if k <= 0 or time.monotonic() - self.t0 > self.ms / 1000.0 + 1.5:
            self.drop()
            return False
        self.pl.setVolume(duck * self.v0 * _xf_gain(k, self.eq))
        return True


class _XfHead:
    def __init__(self, player, ms, eq):
        self.pl = player
        self.ms = max(int(ms), 1)
        self.eq = eq
        self.born = time.monotonic()
        self.t0 = None
        self.v = 0.0
    def apply(self, xf, v):
        self.v = v
        xf.putf("audioVolume", v)
        if not xf.refresh_volume():
            self.pl.setVolume(xf.duck() * v)
    def step(self, xf):
        cur = xf.get("audioPlayer")
        if cur is None or not cur.equals(self.pl):
            return False
        now = time.monotonic()
        if self.t0 is None:
            if self.pl.getCurrentPosition() <= 0 and now - self.born < 3.0:
                self.apply(xf, 0.0)
                return True
            self.t0 = now
        k = (now - self.t0) * 1000.0 / self.ms
        if k >= 1:
            self.apply(xf, 1.0)
            return False
        self.apply(xf, _xf_gain(k, self.eq))
        return True


class _Blend:
    def __init__(self, plugin):
        self.p = plugin
        self.tails = []
        self.head = None
        self.fields = {}
        self.gen = 0
        self.ticking = False
        self.alive = True
        self.auto = 0
        self.want = 0
        self.took = 0
        self.spent = None
        self.last = None
    def sec(self):
        try:
            return max(0, int(self.p.get_setting("crossfade_sec", 0)))
        except Exception:
            return 0
    def set_sec(self, v):
        self.p.set_setting("crossfade_sec", int(v))
    def flag(self, key, default):
        return bool(self.p.get_setting(key, default))
    def flip(self, key, default):
        self.p.set_setting(key, not self.flag(key, default))
    def _fld(self, mc, name):
        f = self.fields.get(name)
        if f is None:
            f = mc.getClass().getDeclaredField(name)
            f.setAccessible(True)
            self.fields[name] = f
        return f
    def get(self, name):
        try:
            mc = self.p._get_mc()
            return self._fld(mc, name).get(mc)
        except Exception:
            return None
    def put(self, name, value):
        mc = self.p._get_mc()
        self._fld(mc, name).set(mc, value)
    def getn(self, name, default, kind):
        try:
            mc = self.p._get_mc()
            f = self._fld(mc, name)
            return {"f": f.getFloat, "i": f.getInt, "b": f.getBoolean}[kind](mc)
        except Exception:
            return default
    def putf(self, name, value):
        with tolerated():
            mc = self.p._get_mc()
            self._fld(mc, name).setFloat(mc, float(value))
    def refresh_volume(self):
        try:
            mc = self.p._get_mc()
            m = self.fields.get("#setPlayerVolume")
            if m is None:
                m = mc.getClass().getDeclaredMethod("setPlayerVolume")
                m.setAccessible(True)
                self.fields["#setPlayerVolume"] = m
            m.invoke(mc)
            return True
        except Exception:
            return False
    def duck(self):
        return 0.2 if self.getn("audioFocus", 2, "i") == 1 else 1.0
    def cast(self):
        try:
            return bool(jclass("org.telegram.ui.CastSync").isActive())
        except Exception:
            return False
    def kick(self):
        if not self.ticking and self.alive:
            self.ticking = True
            run_on_ui_thread(self._run, 30)
    def _run(self):
        if not self.alive:
            self.ticking = False
            self.settle()
            return
        try:
            duck = self.duck()
            self.tails = [t for t in self.tails if t.step(duck)]
            if self.head is not None and not self.head.step(self):
                self.head = None
        except Exception:
            self.settle()
        if self.tails or self.head is not None:
            run_on_ui_thread(self._run, 30)
        else:
            self.ticking = False
    def settle(self):
        for t in self.tails:
            t.drop()
        self.tails = []
        h, self.head = self.head, None
        if h is not None:
            with tolerated():
                h.apply(self, 1.0)
    def stop(self):
        self.alive = False
        self.gen += 1
        run_on_ui_thread(self.settle, 0)
    def start(self):
        self.gen += 1
        g = self.gen
        run_on_ui_thread(lambda: self._watch(g), 0)
    def _watch(self, g):
        if g != self.gen or not self.alive:
            return
        try:
            d = self._probe()
        except Exception:
            d = 1000
        if d is not None:
            run_on_ui_thread(lambda: self._watch(g), int(d))
    def _has_next(self, mc):
        cfg = find_class("org.telegram.messenger.SharedConfig")
        shuffle, rev = self.p._read_order()
        lst = self.get("shuffledPlaylist") if shuffle else mc.getPlaylist()
        if lst is None or int(lst.size()) < 2:
            return False
        loop = self.getn("forceLoopCurrentPlaylist", False, "b")
        mode = int(getattr(cfg, "repeatMode", 0))
        if mode == 2 and not loop:
            return False
        n = int(lst.size())
        i = int(mc.getPlayingMessageObjectNum())
        if not 0 <= i < n:
            return False
        j = i + (1 if rev else -1)
        if not 0 <= j < n:
            if mode == 0 and not loop:
                return False
            j = 0 if j >= n else n - 1
        nxt = lst.get(j)
        return nxt is not None and bool(nxt.isMusic()) and self.p._track_ready(nxt)
    def _probe(self):
        mc = self.p._get_mc()
        msg = mc.getPlayingMessageObject()
        if msg is None or not msg.isMusic():
            return None
        if not self.sec():
            return 1500
        if mc.isMessagePaused() or self.cast() or getattr(self.p, "_sleep_mode", None) == "eot":
            return 500
        pl = self.get("audioPlayer")
        if pl is None:
            return 500
        dur = pl.getDuration()
        pos = pl.getCurrentPosition()
        if dur <= 0 or pos < 0:
            return 250
        spd = max(pl.getPlaybackSpeed(), 0.1)
        left = (dur - pos) / spd
        ms = min(self.sec() * 1000, dur / spd / 3)
        if ms < 500:
            return 1000
        gap = left - ms
        if gap > 0:
            return min(max(gap / 2, 40), 1000)
        key = (msg.getId(), msg.getDialogId())
        if self.spent == key or not self._has_next(mc):
            return 500
        self.spent = key
        self.auto = int(max(min(ms, left), 250))
        try:
            mc.playNextMessage()
        finally:
            self.auto = 0
        return 500
    def play_pre(self, param):
        self.want = 0
        self.took = 0
        msg = param.args[0]
        if msg is None or not msg.isMusic():
            return
        now = param.thisObject.getPlayingMessageObject()
        if now is None or not now.isMusic() or self.cast() or not self.sec():
            return
        self.want = self.auto or (1000 if self.flag("crossfade_skip", True) else 0)
    def cleanup_pre(self, param):
        ms, self.want = self.want, 0
        for t in self.tails:
            t.rush()
        self.head = None
        if ms <= 0:
            return
        pl = self.get("audioPlayer")
        if pl is None or not pl.isPlaying():
            return
        vol = self.getn("audioVolume", 1.0, "f")
        try:
            self.put("audioPlayer", None)
        except Exception:
            return
        with tolerated():
            anim = self.get("audioVolumeAnimator")
            if anim is not None:
                anim.removeAllUpdateListeners()
                anim.removeAllListeners()
                anim.cancel()
            rep = self.get("reporter")
            if rep is not None:
                m = rep.getClass().getDeclaredMethod("destroy")
                m.setAccessible(True)
                m.invoke(rep)
                self.put("reporter", None)
            pl.allowMultipleInstances = True
            pl.setAudioVisualizerDelegate(_xf_mute())
            find_class("org.telegram.ui.ActionBar.Theme").unrefAudioVisualizeDrawable(
          param.thisObject.getPlayingMessageObject())
        self.tails.append(_XfTail(pl, vol, ms, True))
        self.took = ms
        self.kick()
    def play_post(self, param):
        ms, self.took, self.want = self.took, 0, 0
        msg = param.args[0]
        if msg is not None and msg.isMusic():
            self.start()
        if not self.auto:
            self.spent = None
        if ms <= 0:
            return
        pl = self.get("audioPlayer")
        if pl is None or not param.getResult():
            for t in self.tails:
                t.rush()
            return
        anim = self.get("audioVolumeAnimator")
        if anim is not None:
            anim.removeAllUpdateListeners()
            anim.removeAllListeners()
            anim.cancel()
        self.last = (ms, time.monotonic())
        self.head = _XfHead(pl, ms, True)
        self.head.apply(self, 0.0)
        self.kick()
    def switch_delay(self):
        try:
            return max([max(t.left(), 0.0) * t.ms / 1000.0 for t in self.tails if not t.done] or [0.0])
        except Exception:
            return 0.0
    def pause_post(self, param):
        if not param.getResult():
            return
        for t in self.tails:
            t.drop()
        self.tails = []
        h, self.head = self.head, None
        if h is None:
            return
        anim = self.get("audioVolumeAnimator")
        if anim is not None and anim.isRunning():
            anim.setFloatValues(jarray(jfloat)([h.v, 0.0]))
        pl = self.get("audioPlayer")
        if pl is not None:
            self.putf("audioVolume", h.v)
            if not self.refresh_volume():
                pl.setVolume(self.duck() * h.v)
