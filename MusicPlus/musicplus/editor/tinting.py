import time

from ..android import _anim_proxy, _cls, _mix
from ..compat import ArrayList, jarray, jfloat, jint
from ..helpers import _argb
from .. import tint
from ..safe import tolerated

_M = 0xFFFFFFFF
_BUDGET_S = 0.006
_MAX_ANIM = 200
_MAX_NATIVE = 500
_P_MINI, _P_ROWS, _P_REST = 0, 1, 2
_ROWS_S, _REST_S = 0.006, 0.002
_MIXES = (0.1, 0.12, 0.14, 0.16, 0.18, 0.2, 0.22, 0.24, 0.26, 0.3, 0.32)


def _s32(c):
    c &= _M
    return c - 0x100000000 if c & 0x80000000 else c


def _at(e, f):
    base, t, o, n, alpha = e
    c = _mix(o, n, f)
    if base is not None:
        c = _mix(base, c, t)
    if alpha is not None:
        c = _argb(alpha, (c >> 16) & 255, (c >> 8) & 255, c & 255)
    return c


class _QueueEditorTinting:
    _tint_jobs = None
    _tint_anim = None
    _tint_nat = None
    _tint_defer = None
    _tint_rect = None
    _tint_lvl = 0

    def _wanted_colors(self):
        t = tint.current()
        if t is None:
            return self.base_accent, self.base_progress
        return t, t

    def _tint_poll(self):
        acc, prog = self._wanted_colors()
        if acc != self.c_accent or prog != self.c_player_progress:
            self._retint(acc, prog)

    def _tint_finish(self):
        anim, jobs, defer, nat = self._tint_anim, self._tint_jobs, self._tint_defer, self._tint_nat
        self._tint_anim = self._tint_jobs = self._tint_defer = self._tint_nat = None
        with tolerated():
            if anim is not None:
                anim.cancel()
        with tolerated():
            if nat is not None:
                nat.cancel()
        for e, fn, _p, _n in jobs or ():
            with tolerated():
                fn(_at(e, 1.0))
        if defer is not None:
            self._tint_drain(defer[0], defer[1], None)
        if getattr(self, "_tab_accent", None) is not None:
            self._tab_accent = None
            with tolerated():
                self.tab_pr.recolor()

    def _tint_drain(self, mp, stack, budget):
        end = None if budget is None else time.monotonic() + budget
        while stack:
            if end is not None and time.monotonic() >= end:
                return True
            v = stack.pop()
            out = []
            with tolerated():
                self._tint_view(v, mp, out)
            for e, fn, _n in out:
                with tolerated():
                    fn(_at(e, 1.0))
            with tolerated():
                if hasattr(v, "getChildCount"):
                    for i in range(int(v.getChildCount())):
                        stack.append(v.getChildAt(i))
        return False

    def _tint_defer_step(self):
        st = self._tint_defer
        if st is None:
            return
        if self._tint_drain(st[0], st[1], _BUDGET_S):
            self.handler.post(self.Run(self._tint_defer_step))
        elif self._tint_defer is st:
            self._tint_defer = None

    def _retint(self, acc, prog):
        self._tint_finish()
        try:
            mode = int(self.p.get_setting("queue_tint_anim", 0))
        except Exception:
            mode = 0
        self._tint_lvl = tint.queue_level(mode)
        old_a, old_p = self.c_accent, self.c_player_progress
        mp = {}
        pairs = [(old_a, acc)]
        if old_p != old_a:
            pairs.append((old_p, prog))
        for o, n in pairs:
            mp[o & _M] = (None, 0.0, o, n, None)
            mp[((o & 0xFFFFFF) | 0x26000000) & _M] = (None, 0.0, o, n, 0x26)
            for base in (self.c_item, self.c_bg, self.c_player_bg):
                for t in _MIXES:
                    mp[_mix(base, o, t) & _M] = (base, t, o, n, None)
        self.c_accent, self.c_player_progress = acc, prog
        self.c_sel = _mix(self.c_item, acc, 0.18)
        anim, deferred = [], []
        self._tint_prios = self._tint_roots()
        self._tint_skip = self._tint_hashes(list(getattr(self, "tab_btns", {}).values()))
        t_walk = time.monotonic()
        with tolerated():
            self._walk_tint(self.root, mp, anim, deferred, _P_REST)
        tint.note_pressure(time.monotonic() - t_walk > 0.03)
        anim.append((mp[old_a & _M], self._tint_tabs, _P_MINI, None))
        anim.sort(key=lambda j: j[2])
        native = [j for j in anim if j[3] is not None][:_MAX_NATIVE]
        keep = {id(j) for j in native}
        py = [j for j in anim if j[3] is None][:_MAX_ANIM]
        keep.update(id(j) for j in py)
        for j in anim:
            if id(j) not in keep:
                with tolerated():
                    j[1](_at(j[0], 1.0))
        anim = native + py
        if deferred:
            self._tint_defer = (mp, deferred)
            self.handler.post(self.Run(self._tint_defer_step))
        if not anim:
            return
        self._tint_jobs = anim
        if native:
            self._tint_native(native)
        if not py:
            return
        try:
            va = tint.ease(_cls("android.animation.ValueAnimator").ofFloat(jarray(jfloat)([0.0, 1.0])))
            prev = {}
            tiers = ([], [], [])
            for e, fn, p, _n in py:
                tiers[p].append((e, fn))
            cur = [0, 0]

            def apply(e, fn, f, cols):
                k = id(e)
                c = cols.get(k)
                if c is None:
                    c = cols[k] = _at(e, f)
                if prev.get(id(fn)) == c:
                    return
                prev[id(fn)] = c
                with tolerated():
                    fn(c)

            def rotate(lst, k, f, cols, end):
                n = len(lst)
                i, done = cur[k], 0
                while done < n:
                    apply(lst[i][0], lst[i][1], f, cols)
                    i = (i + 1) % n
                    done += 1
                    if time.monotonic() >= end:
                        break
                cur[k] = i

            def step(f):
                cols = {}
                if f >= 0.999:
                    for lst in tiers:
                        for e, fn in lst:
                            apply(e, fn, f, cols)
                    self._tab_accent = None
                    with tolerated():
                        self.tab_pr.recolor()
                    return
                for e, fn in tiers[_P_MINI]:
                    apply(e, fn, f, cols)
                now = time.monotonic()
                rotate(tiers[_P_ROWS], 0, f, cols, now + _ROWS_S)
                now = time.monotonic()
                rotate(tiers[_P_REST], 1, f, cols, now + _REST_S)
            va.addUpdateListener(_anim_proxy()(tint.throttled(step, tint._GAP_BY_LVL[self._tint_lvl])))
            self._tint_anim = va
            va.start()
        except Exception:
            self._tint_finish()

    def _tint_native(self, jobs):
        OA = _cls("android.animation.ObjectAnimator")
        items = ArrayList()
        for e, fn, _p, nat in jobs:
            try:
                items.add(OA.ofArgb(nat[0], nat[1], jarray(jint)([_s32(_at(e, 0.0)), _s32(_at(e, 1.0))])))
            except Exception:
                with tolerated():
                    fn(_at(e, 1.0))
        try:
            aset = _cls("android.animation.AnimatorSet")()
            aset.playTogether(items)
            self._tint_nat = tint.ease(aset)
            aset.start()
        except Exception:
            for e, fn, _p, _n in jobs:
                with tolerated():
                    fn(_at(e, 1.0))

    def _tint_visible(self, v):
        try:
            if self._tint_rect is None:
                self._tint_rect = _cls("android.graphics.Rect")()
            return bool(v.getGlobalVisibleRect(self._tint_rect))
        except Exception:
            return True

    def _tint_tabs(self, c):
        self._tab_accent = c
        self.tab_pr.recolor()

    def _tint_hashes(self, views):
        out = set()
        for v in views:
            with tolerated():
                out.add(int(v.hashCode()))
        return out

    def _tint_roots(self):
        out = {}
        for name, p in (("container", _P_ROWS), ("lib_box", _P_ROWS), ("mini_box", _P_MINI)):
            v = getattr(self, name, None)
            if v is not None:
                with tolerated():
                    out[int(v.hashCode())] = p
        return out

    def _walk_tint(self, v, mp, anim, deferred, prio):
        if not self._tint_visible(v):
            deferred.append(v)
            return
        grp = hasattr(v, "getChildCount")
        if grp:
            with tolerated():
                hp = self._tint_prios.get(int(v.hashCode()))
                if hp is not None:
                    prio = min(prio, hp)
                    if hp == _P_ROWS and self._tint_lvl >= 1:
                        deferred.append(v)
                        return
        out = []
        skip = False
        if self._tint_skip and hasattr(v, "getCurrentTextColor"):
            with tolerated():
                skip = int(v.hashCode()) in self._tint_skip
        if not skip:
            self._tint_view(v, mp, out)
        for e, fn, nat in out:
            anim.append((e, fn, prio, nat))
        if grp:
            for i in range(int(v.getChildCount())):
                self._walk_tint(v.getChildAt(i), mp, anim, deferred, prio)

    def _tint_view(self, v, mp, jobs):
        with tolerated():
            if hasattr(v, "getCurrentTextColor"):
                e = mp.get(int(v.getCurrentTextColor()) & _M)
                if e:
                    jobs.append((e, v.setTextColor, (v, "textColor")))
        with tolerated():
            self._tint_drawable(v.getBackground(), mp, jobs, 0)
        with tolerated():
            lb = getattr(self, "mini_like_btn", None)
            nofilter = lb is not None and int(v.hashCode()) == int(lb.hashCode())
            if not nofilter and hasattr(v, "getColorFilter"):
                cf = v.getColorFilter()
                e = mp.get(int(cf.getColor()) & _M) if cf is not None else None
                if e:
                    jobs.append((e, v.setColorFilter, (v, "colorFilter") if hasattr(v, "setImageResource") else None))
        with tolerated():
            if hasattr(v, "getProgressDrawable"):
                self._tint_drawable(v.getProgressDrawable(), mp, jobs, 0)
                self._tint_drawable(v.getThumb(), mp, jobs, 0)
                csl = v.getProgressTintList()
                e = mp.get(int(csl.getDefaultColor()) & _M) if csl is not None else None
                if e:
                    CSL = type(csl)
                    def tl(c, v=v, CSL=CSL):
                        cs = CSL.valueOf(c)
                        v.setProgressTintList(cs)
                        v.setThumbTintList(cs)
                    jobs.append((e, tl, None))

    def _tint_drawable(self, d, mp, jobs, depth):
        if d is None or depth > 4:
            return
        name = str(d.getClass().getName())
        if name.endswith("GradientDrawable"):
            c = d.getColor()
            e = mp.get(int(c.getDefaultColor()) & _M) if c is not None else None
            if e:
                jobs.append((e, d.setColor, (d, "color")))
        elif name.endswith("ColorDrawable"):
            e = mp.get(int(d.getColor()) & _M)
            if e:
                jobs.append((e, d.setColor, (d, "color")))
        elif hasattr(d, "getNumberOfLayers"):
            for i in range(int(d.getNumberOfLayers())):
                self._tint_drawable(d.getDrawable(i), mp, jobs, depth + 1)
        elif hasattr(d, "getDrawable"):
            self._tint_drawable(d.getDrawable(), mp, jobs, depth + 1)
