import time

from elyx import strings
from .compat import (
 MethodHook,
 dynamic_proxy,
 jarray,
 jclass,
 jfloat,
 jint,
 run_on_ui_thread,
)
from . import reflect
from .safe import tolerated


_AJ_TAB_ID = "smart_music_queue"
_DESC = "aj_tabs:"
_INJ_CLICK = None
_MT_CLASS = "org.telegram.ui.MainTabsActivity"
_GTV_CLASS = "org.telegram.ui.Components.glass.GlassTabView"
_GTV_ANIM_CLASS = _GTV_CLASS + "$TabAnimation"
_PAGE_CLASS = "org.telegram.ui.CallLogActivity"
_TAB_BASE_TABS = 6
_TAB_BASE_PAGES = 4
_FALLBACK_ICONS = ("MUSIC", "CHATS", "CONTACTS")


def _inj_click():
    global _INJ_CLICK
    if _INJ_CLICK is None:
        OnClick = jclass("android.view.View$OnClickListener")
        class Click(dynamic_proxy(OnClick)):
            def __init__(self, fn):
                super().__init__()
                self.fn = fn
            def onClick(self, v):
                with tolerated():
                    self.fn(v)
        _INJ_CLICK = Click
    return _INJ_CLICK


_LAST_FEED = [False]


def find_main_tabs():
    cls = reflect.jcls(_MT_CLASS)
    if cls is None:
        return None
    with tolerated():
        LA = jclass("org.telegram.ui.LaunchActivity")
        stacks = []
        with tolerated():
            stacks.append(LA.instance.getActionBarLayout().getFragmentStack())
        with tolerated():
            stacks.append(LA.mainFragmentsStack)
        for st in stacks:
            for i in range(st.size()):
                f = st.get(i)
                if cls.isInstance(f):
                    return f
    return None


def host_feed_tab_on():
    act = find_main_tabs()
    if act is not None:
        try:
            _LAST_FEED[0] = bool(reflect.invoke(act, "isFeedTabEnabled"))
        except Exception:
            pass
    return _LAST_FEED[0]


def host_has_slot(act=None):
    act = act if act is not None else find_main_tabs()
    if act is None:
        return None
    try:
        return bool(reflect.invoke(act, "hasContactsOrFeedTab"))
    except Exception:
        return None


def make_preview_tab(ctx, rp, anim_name, label, selected=False):
    amap = {}
    for v in reflect.jcls(_GTV_ANIM_CLASS).getEnumConstants():
        amap[str(v.name()).upper()] = v
    anim = amap.get(anim_name)
    if anim is None:
        return None
    res = int(ctx.getResources().getIdentifier("MainTabsChats", "string", ctx.getPackageName()))
    GTV = jclass(_GTV_CLASS)
    main = GTV.createMainTab(ctx, rp, anim, res)
    view = main
    with tolerated():
        stock = None
        act = find_main_tabs()
        if act is not None:
            stock = list(act.tabs)[0]
        want = bool(reflect.field(stock, "useMainTabSelectedIndicator")) if stock is not None else None
        if want is not None and _has_method(GTV, "createMainNavigationTab"):
            nav = GTV.createMainNavigationTab(ctx, rp, anim, res)
            if bool(reflect.field(nav, "useMainTabSelectedIndicator")) == want and \
                    bool(reflect.field(main, "useMainTabSelectedIndicator")) != want:
                view = nav
    with tolerated():
        view.setText(label)
    with tolerated():
        view.setSelected(bool(selected), False)
    with tolerated():
        view.setClickable(False)
    return view


def _find_view(root, cls_name):
    cls = reflect.jcls(cls_name)
    vg = reflect.jcls("android.view.ViewGroup")
    if cls is None:
        return None
    stack = [root]
    while stack:
        v = stack.pop()
        if cls.isInstance(v):
            return v
        if vg.isInstance(v):
            for i in range(v.getChildCount()):
                stack.append(v.getChildAt(i))
    return None


def _current_user():
    UC = jclass("org.telegram.messenger.UserConfig")
    return int(UC.selectedAccount), UC.getInstance(int(UC.selectedAccount)).getCurrentUser()


def _set_avatar(biv, user):
    AD = jclass("org.telegram.ui.Components.AvatarDrawable")()
    AD.setInfo(user)
    biv.setForUserOrChat(user, AD)


def make_preview_avatar(ctx, rp, label):
    GTV = jclass(_GTV_CLASS)
    account, user = _current_user()
    res = int(ctx.getResources().getIdentifier("MainTabsChats", "string", ctx.getPackageName()))
    nav_first = True
    with tolerated():
        nav_first = bool(reflect.field(list(find_main_tabs().tabs)[0], "mainNavigationTab"))
    names = ["createMainNavigationAvatar", "createAvatar"]
    if not nav_first:
        names.reverse()
    view = None
    for n in names:
        if view is None and _has_method(GTV, n):
            with tolerated():
                view = getattr(GTV, n)(ctx, rp, jint(account), jint(res))
    if view is None:
        return None
    with tolerated():
        view.setText(label)
    with tolerated():
        view.setClickable(False)
    with tolerated():
        biv = _find_view(view, "org.telegram.ui.Components.BackupImageView")
        if biv is not None and user is not None:
            _set_avatar(biv, user)
    return view


def make_plain_avatar(ctx, size_px):
    account, user = _current_user()
    biv = jclass("org.telegram.ui.Components.BackupImageView")(ctx)
    biv.setRoundRadius(int(size_px // 2))
    if user is not None:
        _set_avatar(biv, user)
    return biv


def _short_cls(c):
    with tolerated():
        return str(c.getName()).rsplit(".", 1)[-1]
    return "?"


class _Entry:
    def __init__(self, spec, seq):
        self.id = str(spec["id"])
        self.title_key = spec.get("title_key")
        self.title = str(spec.get("title") or self.id)
        self.icon = str(spec.get("icon") or "MUSIC")
        self.index = None
        with tolerated():
            ix = int(spec.get("index"))
            self.index = ix if ix >= 1 else None
        self.on_create = spec.get("on_create")
        self.on_destroy = spec.get("on_destroy")
        self.on_back = spec.get("on_back")
        self.on_resume = spec.get("on_resume")
        self.seq = seq
        self.view = None


def _has_method(obj_or_cls, name):
    with tolerated():
        c = obj_or_cls if hasattr(obj_or_cls, "getDeclaredMethods") else obj_or_cls.getClass()
        while c is not None:
            for m in c.getDeclaredMethods():
                if str(m.getName()) == name:
                    return True
            c = c.getSuperclass()
    return False


class _TabInjector:
    def __init__(self, plugin, mode="add", target="contacts"):
        self.p = plugin
        self.mode = mode
        self.target = target if target in ("contacts", "settings") else "contacts"
        self.hook_report = {}
        self.probe_info = {}
        self._tbase = None
        self._tcls = None
        self._act_ref = None
        self._cidx = None
        self._cpos = None
        self._orig_tab = None
        self._probed = None
        self._hooks = []
        self._entries = {}
        self._seq = 0
        self._hooked = False
        self._tab_mt = None
        with tolerated():
            self._tab_mt = reflect.jcls(_MT_CLASS)
        self._frags = {}
        self._clicks = {}
        self._order = []
        self._sig = None
        self._base = None
        self._map_cache = None
        self._stash = []
        self._busy = set()
        self._adapters = set()
        self._vis_hooked = set()
        self._tok = 0
        self._last_inject = 0.0
        self._rebound = False
        self._anims = None
        self._hopped = False
        self._pending_rebuild = False
        self._hops = 0
        self._apply_tries = 0
        self._clicks_wrapped = set()
        self._slot_missing = False
        self._cm = None
        self._counter_watch = False
    def stop(self):
        self._counter_watch = False
        for unhook in list(self._hooks):
            with tolerated():
                self.p.unhook_method(unhook)
        self._hooks.clear()
        with tolerated():
            self._teardown()
    def add_entry(self, spec):
        if not spec.get("id"):
            return False
        old = self._entries.get(str(spec["id"]))
        if old is None:
            self._pending_rebuild = True
            self._hopped = False
            self._hops = 0
            self._apply_tries = 0
        self._seq += 1
        e = _Entry(spec, old.seq if old else self._seq)
        self._entries[e.id] = e
        run_on_ui_thread(self._activate, 0)
        return True
    def open_entry(self, tab_id):
        e = self._entries.get(str(tab_id))
        if e is None:
            return False
        if self.mode == "replace":
            act = self._find_main()
            if act is None:
                return False
            if self._cpos is None:
                self._resolve_contacts(act)
            if self._cpos is None:
                return False
        elif not self._order or e.view is None:
            return False
        else:
            act = self._find_main()
            if act is None:
                return False
        try:
            LA = jclass("org.telegram.ui.LaunchActivity")
            st = LA.instance.getActionBarLayout().getFragmentStack()
            n = int(st.size())
            if n != 1 or not self._tab_mt.isInstance(st.get(n - 1)):
                return False
        except Exception:
            return False
        self._goto(act, self._cpos if self.mode == "replace" else self._pos_of_entry(e))
        return True
    def _sorted(self):
        return [x for k, x in self._layout() if k == "e"]
    def _pages(self):
        return int(self._base) if self._base else _TAB_BASE_PAGES
    def _layout(self):
        res = [("s", i) for i in range(self._pages())]
        if self.mode == "replace":
            ent = next(iter(self._entries.values()), None)
            cp = self._cpos
            if ent is not None and cp is not None and 0 <= cp < len(res):
                res[cp] = ("e", ent)
            return res
        ents = sorted(self._entries.values(),
       key=lambda e: (e.index if e.index is not None else 10 ** 6, e.seq))
        for e in ents:
            d = (e.index - 1) if e.index is not None else len(res)
            res.insert(max(0, min(d, len(res))), ("e", e))
        return res
    def _pos_of_entry(self, e, lay=None):
        for p, (k, x) in enumerate(lay or self._layout()):
            if k == "e" and x is e:
                return p
        return -1
    def _pos_of_stock(self, s, lay=None):
        for p, (k, x) in enumerate(lay or self._layout()):
            if k == "s" and x == s:
                return p
        return s
    def _anim_map(self):
        if self._anims is None:
            self._anims = {}
            with tolerated():
                for v in reflect.jcls(_GTV_ANIM_CLASS).getEnumConstants():
                    self._anims[str(v.name()).upper()] = v
        return self._anims
    def _make_glass(self, act, e):
        ctx = act.getContext()
        amap = self._anim_map()
        anim = amap.get(e.icon.upper())
        if anim is None:
            for n in _FALLBACK_ICONS:
                if n in amap:
                    anim = amap[n]
                    break
            if anim is None and amap:
                anim = list(amap.values())[0]
            if anim is None:
                raise RuntimeError("no tab icons available in this build")
        res = int(ctx.getResources().getIdentifier("MainTabsChats", "string", ctx.getPackageName()))
        if res == 0:
            res = int(getattr(jclass("org.telegram.messenger.R$string"), "MainTabsChats"))
        try:
            rp = act.getResourceProvider()
        except Exception:
            rp = reflect.field(act, "resourceProvider")
        GTV = jclass(_GTV_CLASS)
        stock = None
        with tolerated():
            stock = list(act.tabs)[0]
        want = None
        with tolerated():
            want = bool(reflect.field(stock, "useMainTabSelectedIndicator"))
        main = GTV.createMainTab(ctx, rp, anim, res)
        if want is None or not _has_method(GTV, "createMainNavigationTab"):
            return main
        nav = None
        with tolerated():
            nav = GTV.createMainNavigationTab(ctx, rp, anim, res)
        flags = {}
        for name, v in (("createMainTab", main), ("createMainNavigationTab", nav)):
            with tolerated():
                flags[name] = bool(reflect.field(v, "useMainTabSelectedIndicator"))
        pick = "createMainNavigationTab" if (nav is not None and flags.get("createMainNavigationTab") == want
                                              and flags.get("createMainTab") != want) else "createMainTab"
        if not getattr(self, "_factory_noted", False):
            self._factory_noted = True
        return nav if pick == "createMainNavigationTab" else main
    def _set_label(self, view, text):
        with tolerated():
            for m in view.getClass().getMethods():
                if m.getName() in ("setText", "setTitle", "setLabel", "setName", "setTitleText") \
             and m.getParameterCount() == 1:
                    pt = m.getParameterTypes()[0].getName()
                    if pt in ("java.lang.CharSequence", "java.lang.String"):
                        m.invoke(view, text)
                        return
        with tolerated():
            tv_cls = reflect.jcls("android.widget.TextView")
            vg_cls = reflect.jcls("android.view.ViewGroup")
            stack = [view]
            while stack:
                v = stack.pop()
                if tv_cls.isInstance(v):
                    v.setText(text)
                    return
                if vg_cls.isInstance(v):
                    for i in range(v.getChildCount()):
                        stack.append(v.getChildAt(i))
    def _text_views(self, view):
        out = []
        with tolerated():
            tv_cls = reflect.jcls("android.widget.TextView")
            vg_cls = reflect.jcls("android.view.ViewGroup")
            stack = [view]
            while stack:
                v = stack.pop()
                if tv_cls.isInstance(v):
                    out.append(v)
                elif vg_cls.isInstance(v):
                    for i in range(int(v.getChildCount())):
                        stack.append(v.getChildAt(i))
        return out
    def _label_shown(self, t):
        try:
            if int(t.getVisibility()) != 0 or float(t.getAlpha()) < 0.05:
                return False
            return len(str(t.getText())) > 0
        except Exception:
            return True
    def _stock_titles_hidden(self, act):
        votes = []
        for s in list(act.tabs)[:self._nbase()]:
            try:
                if int(s.getVisibility()) != 0:
                    continue
            except Exception:
                continue
            tvs = self._text_views(s)
            if tvs:
                votes.append(not any(self._label_shown(t) for t in tvs))
                continue
            for g in ("getText", "getTitle", "getLabel"):
                try:
                    r = getattr(s, g)()
                except Exception:
                    continue
                if r is not None:
                    votes.append(len(str(r)) == 0)
                    break
        if not votes:
            return None
        return sum(1 for x in votes if x) * 2 > len(votes)
    def _mirror_title_fields(self, src, dst):
        changed = False
        with tolerated():
            Mod = jclass("java.lang.reflect.Modifier")
            c = src.getClass()
            while c is not None and not str(c.getName()).startswith("android."):
                for f in c.getDeclaredFields():
                    with tolerated():
                        if Mod.isStatic(int(f.getModifiers())) or str(f.getType().getName()) != "boolean":
                            continue
                        n = str(f.getName()).lower()
                        if not any(k in n for k in ("title", "label", "text", "icononly", "compact", "hide")):
                            continue
                        if any(k in n for k in ("select", "anim", "press", "touch", "enabled", "check",
                                                "active", "dark", "theme", "blur", "glass", "color", "focus")):
                            continue
                        f.setAccessible(True)
                        a, b = bool(f.getBoolean(src)), bool(f.getBoolean(dst))
                        if a != b:
                            f.setBoolean(dst, a)
                            changed = True
                c = c.getSuperclass()
        return changed
    def _mirror_geometry(self, src, dst):
        changed = False
        with tolerated():
            Mod = jclass("java.lang.reflect.Modifier")
            keep = ("offset", "height", "top", "bottom", "size", "pad", "margin", "gap", "shift",
                    "center", "inset", "title", "label", "text", "icon")
            skip = ("scale", "alpha", "progress", "anim", "select", "press", "touch", "color", "rot",
                    "frame", "time", "count", "index", "width", "id", "state")
            c = src.getClass()
            while c is not None and not str(c.getName()).startswith("android."):
                for f in c.getDeclaredFields():
                    with tolerated():
                        tn = str(f.getType().getName())
                        if Mod.isStatic(int(f.getModifiers())) or tn not in ("int", "float"):
                            continue
                        n = str(f.getName()).lower()
                        if not any(k in n for k in keep) or any(k in n for k in skip):
                            continue
                        f.setAccessible(True)
                        if tn == "int":
                            a, b = int(f.getInt(src)), int(f.getInt(dst))
                            if a != b:
                                f.setInt(dst, a)
                                changed = True
                        else:
                            a, b = float(f.getFloat(src)), float(f.getFloat(dst))
                            if abs(a - b) > 0.001:
                                f.setFloat(dst, a)
                                changed = True
                c = c.getSuperclass()
        with tolerated():
            if int(src.getPaddingTop()) != int(dst.getPaddingTop()) or int(src.getPaddingBottom()) != int(dst.getPaddingBottom()):
                dst.setPadding(int(dst.getPaddingLeft()), int(src.getPaddingTop()),
                               int(dst.getPaddingRight()), int(src.getPaddingBottom()))
                changed = True
        with tolerated():
            vg = reflect.jcls("android.view.ViewGroup")
            if vg.isInstance(src) and vg.isInstance(dst) and int(src.getChildCount()) == int(dst.getChildCount()):
                for i in range(int(src.getChildCount())):
                    a, b = src.getChildAt(i), dst.getChildAt(i)
                    if int(a.getVisibility()) == 8 and int(b.getVisibility()) != 8:
                        b.setVisibility(8)
                        changed = True
                    la, lb = a.getLayoutParams(), b.getLayoutParams()
                    if la is None or lb is None:
                        continue
                    diff = False
                    for nm in ("topMargin", "bottomMargin", "height", "gravity"):
                        try:
                            va, vb = int(getattr(la, nm)), int(getattr(lb, nm))
                        except Exception:
                            continue
                        if va != vb:
                            setattr(lb, nm, va)
                            diff = True
                    if diff:
                        b.setLayoutParams(lb)
                        changed = True
                    if int(a.getPaddingTop()) != int(b.getPaddingTop()) or int(a.getPaddingBottom()) != int(b.getPaddingBottom()):
                        b.setPadding(int(b.getPaddingLeft()), int(a.getPaddingTop()),
                                     int(b.getPaddingRight()), int(a.getPaddingBottom()))
                        changed = True
        return changed
    def _sync_titles(self, act):
        with tolerated():
            hidden = self._stock_titles_hidden(act)
            src = None
            for s in list(act.tabs)[:self._nbase()]:
                with tolerated():
                    if int(s.getVisibility()) == 0:
                        src = s
                        break
            for e in list(self._entries.values()):
                v = e.view
                if v is None:
                    continue
                same = False
                with tolerated():
                    same = src is not None and bool(src.getClass().equals(v.getClass()))
                changed = self._mirror_title_fields(src, v) if same else False
                if same and self._mirror_geometry(src, v):
                    changed = True
                if hidden is not None and getattr(e, "title_hidden", None) != hidden:
                    e.title_hidden = hidden
                    text = "" if hidden else (strings(e.title_key) if e.title_key else e.title)
                    self._set_label(v, text)
                    for t in self._text_views(v):
                        with tolerated():
                            t.setVisibility(8 if hidden else 0)
                    changed = True
                if changed:
                    with tolerated():
                        v.requestLayout()
                        v.invalidate()
    def _hook(self, cls, name, nparams, handler):
        c = cls
        while c is not None:
            with tolerated():
                for m in c.getDeclaredMethods():
                    if str(m.getName()) == name and int(m.getParameterCount()) == nparams:
                        m.setAccessible(True)
                        r = self.p.hook_method(m, handler)
                        if r:
                            self._hooks.append(r)
                        self.hook_report[name] = bool(r)
                        return True
            c = c.getSuperclass()
        self.hook_report[name] = False
        return False
    def _activate(self):
        self._ensure_hooks()
        if not self._hooked:
            return
        for d in (0, 400, 1500, 3500):
            run_on_ui_thread(self._apply_existing, d)
    def _ensure_hooks(self):
        if self._hooked or self.mode == "diag":
            return
        mt = reflect.jcls(_MT_CLASS)
        if mt is None:
            return
        self._tab_mt = mt
        self._hooked = True
        H = lambda before=None, after=None: _TabHook(self, before, after)
        self._hook(mt, "createView", 1, H(after=lambda p: self._on_view(p.thisObject)))
        self._hook(mt, "onResume", 0, H(after=lambda p: self._on_host_resume(p.thisObject)))
        self._hook(mt, "createBaseFragmentAt", 1, H(before=self._h_create))
        if self.mode == "replace":
            self._hook(mt, "checkContactsTabBadge", 0, H(before=lambda p: p.setResult(None)))
            seen = set()
            with tolerated():
                for m in mt.getDeclaredMethods():
                    n = str(m.getName())
                    nl = n.lower()
                    key = (n, int(m.getParameterCount()))
                    if (key not in seen and "$" not in n and n != "checkContactsTabBadge"
                            and str(m.getReturnType().getName()) == "void"
                            and any(w in nl for w in ("unread", "counter", "badge", "feed"))):
                        seen.add(key)
                        self._hook(mt, n, key[1], H(after=lambda p: self._suppress_counter_now()))
        if self.mode == "add":
            self._hook(mt, "getFragmentsCount", 0, H(after=self._h_count))
            self._hook(mt, "getStartPosition", 0, H(after=self._h_start))
            self._hook(mt, "selectTab", 2, H(before=lambda p: self._h_sel_before(p, False),
           after=lambda p: self._h_sel_after(p, False)))
            self._hook(mt, "setGestureSelectedOverride", 2, H(before=lambda p: self._h_sel_before(p, True),
           after=lambda p: self._h_sel_after(p, True)))
        page = reflect.jcls(_PAGE_CLASS)
        if page is not None:
            self._hook(page, "createView", 1, H(after=self._h_page_view))
            self._hook(page, "onFragmentDestroy", 0, H(before=self._h_page_destroy))
        self._hook_back(mt, page)
    def _on_view(self, act):
        self._remember(act)
        if self.mode == "replace":
            self._apply_replace(act)
        else:
            self._inject(act)
    def _remember(self, act):
        with tolerated():
            self._act_ref = jclass("java.lang.ref.WeakReference")(act)
    def _hook_back(self, *classes):
        done = set()
        for cls in classes:
            c = cls
            while c is not None:
                found = None
                with tolerated():
                    for m in c.getDeclaredMethods():
                        if (str(m.getName()) == "onBackPressed"
                   and str(m.getReturnType().getName()) == "boolean"):
                            found = m
                            break
                if found is not None:
                    sig = str(found.toString())
                    if sig not in done:
                        done.add(sig)
                        with tolerated():
                            found.setAccessible(True)
                            r = self.p.hook_method(found, _TabHook(self, self._h_back))
                            if r:
                                self._hooks.append(r)
                    break
                c = c.getSuperclass()
    def _h_count(self, param):
        orig = int(param.getResult())
        if self._base is not None and self._base != orig:
            self._map_cache = None
            self._schedule_resync(350)
        self._base = orig
        param.setResult(jint(orig + len(self._entries)))
    def _h_start(self, param):
        r = int(param.getResult())
        if self._entries and 0 <= r < self._pages():
            param.setResult(jint(self._pos_of_stock(r)))
    def _h_create(self, param):
        if "createBaseFragmentAt" in self._busy or not self._entries:
            return
        if self.mode == "replace":
            self._refresh_cpos(param.thisObject)
        p = int(param.args[0])
        lay = self._layout()
        if not (0 <= p < len(lay)):
            return
        kind, x = lay[p]
        if kind == "e":
            frag = self._make_page(x)
            if frag is not None:
                param.setResult(frag)
        elif x != p:
            self._busy.add("createBaseFragmentAt")
            try:
                r = reflect.invoke(param.thisObject, "createBaseFragmentAt", jint(x))
            finally:
                self._busy.discard("createBaseFragmentAt")
            param.setResult(r)
    def _h_sel_before(self, param, gesture):
        act = param.thisObject
        if gesture:
            self._rebound = True
        live = None
        try:
            cur = act.tabs
            if self._order and len(cur) > self._nbase():
                live = cur
                act.tabs = jarray(self._arr_cls())(list(cur)[:self._nbase()])
        except Exception:
            live = None
        if len(self._stash) > 16:
            del self._stash[:]
        try:
            val = float(param.args[0]) if gesture else int(param.args[0])
        except Exception:
            val = 0
        self._stash.append((live, val))
        with tolerated():
            if gesture:
                param.args[0] = jfloat(-1000.0)
            else:
                p = int(param.args[0])
                lay = self._layout()
                if 0 <= p < len(lay):
                    kind, x = lay[p]
                    param.args[0] = jint(-1 if kind == "e" else x)
    def _h_sel_after(self, param, gesture):
        act = param.thisObject
        if not self._stash:
            return
        live, orig = self._stash.pop()
        with tolerated():
            if live is not None and len(act.tabs) == self._nbase():
                act.tabs = live
        self._select(act, orig, bool(param.args[1]), gesture)
        if not gesture:
            with tolerated():
                kind, x = self._layout()[int(orig)]
                if kind == "e" and x.on_resume is not None:
                    x.on_resume()
                    self.p._update_schedule()
    def _make_page(self, e):
        Bundle = jclass("android.os.Bundle")
        args = Bundle()
        args.putBoolean("hasMainTabs", True)
        args.putBoolean("needFinishFragment", False)
        frag = jclass(_PAGE_CLASS)(args)
        self._frags[reflect.identity_hash(frag)] = (jclass("java.lang.ref.WeakReference")(frag), e.id)
        return frag
    def _entry_of_page(self, frag):
        h = reflect.identity_hash(frag)
        ref = self._frags.get(h)
        if ref is None:
            return None
        with tolerated():
            cur = ref[0].get()
            if cur is not None and bool(cur.equals(frag)):
                return self._entries.get(ref[1])
        self._frags.pop(h, None)
        return None
    def _h_page_view(self, param):
        frag = param.thisObject
        e = self._entry_of_page(frag)
        if e is None:
            return
        view = param.getResult()
        with tolerated():
            view.removeAllViews()
        with tolerated():
            frag.actionBar.setVisibility(8)
        ctx = None
        with tolerated():
            ctx = frag.getParentActivity()
        if ctx is None:
            ctx = view.getContext()
        if e.on_create is not None:
            with tolerated():
                e.on_create(view, frag, ctx)
    def _h_page_destroy(self, param):
        frag = param.thisObject
        e = self._entry_of_page(frag)
        if e is None:
            return
        self._frags.pop(reflect.identity_hash(frag), None)
        if e.on_destroy is not None:
            with tolerated():
                e.on_destroy(frag)
    def _h_back(self, param):
        th = param.thisObject
        e = self._entry_of_page(th)
        frag = th
        if e is None:
            try:
                if not bool(self._tab_mt.isInstance(th)):
                    return
                vp = reflect.field(th, "viewPager")
                lay = self._layout()
                cur = int(reflect.invoke(vp, "getCurrentPosition"))
                if not (0 <= cur < len(lay)) or lay[cur][0] != "e":
                    return
                e = lay[cur][1]
                frag = None
            except Exception:
                return
        if e.on_back is not None:
            with tolerated():
                if e.on_back(frag):
                    param.setResult(False)
    def _on_host_resume(self, act):
        with tolerated():
            self._remember(act)
            if self.mode == "replace":
                self._converge_replace(act)
            else:
                self._inject(act)
            for e in list(self._entries.values()):
                if e.on_resume is not None:
                    with tolerated():
                        e.on_resume()
    def _find_main(self):
        cls = self._tab_mt
        if cls is None:
            return None
        with tolerated():
            ref = self._act_ref
            a = ref.get() if ref is not None else None
            if a is not None and cls.isInstance(a):
                return a
        with tolerated():
            LA = jclass("org.telegram.ui.LaunchActivity")
            stacks = []
            with tolerated():
                stacks.append(LA.instance.getActionBarLayout().getFragmentStack())
            with tolerated():
                stacks.append(LA.mainFragmentsStack)
            for st in stacks:
                for i in range(st.size()):
                    f = st.get(i)
                    if cls.isInstance(f):
                        return f
        return None
    def _is_ours(self, c):
        try:
            return str(c.getContentDescription()).startswith(_DESC)
        except Exception:
            return False
    def _stock_visible(self, tv):
        out = []
        for i in range(int(tv.getChildCount())):
            c = tv.getChildAt(i)
            with tolerated():
                if self._is_ours(c):
                    continue
                if int(c.getVisibility()) == 0 and float(c.getAlpha()) > 0.05:
                    out.append(c)
        return out
    def _has_ours(self, act, tv):
        try:
            ids = set()
            n = 0
            for i in range(int(tv.getChildCount())):
                d = str(tv.getChildAt(i).getContentDescription())
                if d.startswith(_DESC):
                    ids.add(d[len(_DESC):])
                    n += 1
            sig = tuple(e.id for e in self._sorted())
            return (n == len(self._entries) and ids == set(self._entries)
          and len(act.tabs) == self._nbase() + n and sig == self._sig)
        except Exception:
            return False
    def _expected(self, tv):
        stock = self._stock_visible(tv)
        out, si = [], 0
        for kind, x in self._layout():
            if kind == "s":
                if si < len(stock):
                    out.append(stock[si])
                    si += 1
            elif x.view is not None:
                out.append(x.view)
        out.extend(stock[si:])
        return out
    def _place_all(self, tv):
        exp = self._expected(tv)
        mine = set(reflect.identity_hash(e.view) for e in self._entries.values() if e.view is not None)
        ids = set(reflect.identity_hash(v) for v in exp)
        cur = [reflect.identity_hash(tv.getChildAt(i)) for i in range(int(tv.getChildCount()))
       if reflect.identity_hash(tv.getChildAt(i)) in ids]
        if cur == [reflect.identity_hash(v) for v in exp]:
            return
        for e in self._entries.values():
            if e.view is not None and int(tv.indexOfChild(e.view)) >= 0:
                tv.removeView(e.view)
        for i, v in enumerate(exp):
            if reflect.identity_hash(v) not in mine:
                continue
            nxt = next((w for w in exp[i + 1:] if reflect.identity_hash(w) not in mine), None)
            tgt = int(tv.indexOfChild(nxt)) if nxt is not None else int(tv.getChildCount())
            tv.addView(v, max(0, min(tgt, int(tv.getChildCount()))))
        with tolerated():
            tv.requestLayout()
    def _show_all(self, tv):
        for e in self._entries.values():
            v = e.view
            if v is None:
                continue
            try:
                shown = int(v.getVisibility()) == 0 and float(v.getAlpha()) > 0.05
            except Exception:
                shown = True
            if shown:
                continue
            with tolerated():
                reflect.invoke(tv, "setViewVisible", v, True, False)
            with tolerated():
                reflect.invoke(tv, "addTabToIgnoreClick", v)
            with tolerated():
                v.setVisibility(0)
                v.setAlpha(1.0)
    def _get_adapter(self, act):
        vp = reflect.field(act, "viewPager")
        if vp is None:
            return None
        ad = reflect.field(vp, "adapter")
        if ad is None:
            c = vp.getClass()
            while c is not None and ad is None:
                for f in c.getDeclaredFields():
                    if "adapter" in str(f.getName()).lower():
                        f.setAccessible(True)
                        ad = f.get(vp)
                        if ad is not None:
                            break
                c = c.getSuperclass()
        return ad
    def _refresh_adapter(self, act):
        with tolerated():
            ad = self._get_adapter(act)
            if ad is None:
                return
            if _has_method(ad, "notifyDataSetChanged"):
                ad.notifyDataSetChanged()
            elif not getattr(self, "_no_notify", False):
                self._no_notify = True
    def _hook_adapter(self, act):
        ad = self._get_adapter(act)
        if ad is None:
            return
        name = str(ad.getClass().getName())
        if name in self._adapters:
            return
        mt = self._tab_mt
        def after(param):
            outer = reflect.field(param.thisObject, "this$0")
            if outer is None or not mt.isInstance(outer):
                return
            r = int(param.getResult())
            if self._base is None:
                self._base = r
            if r == self._base:
                param.setResult(jint(r + len(self._entries)))
        c = ad.getClass()
        while c is not None:
            try:
                m = c.getDeclaredMethod("getItemCount")
                m.setAccessible(True)
                r = self.p.hook_method(m, _TabHook(self, None, after))
                if r:
                    self._hooks.append(r)
                self._adapters.add(name)
                return
            except Exception:
                c = c.getSuperclass()
    def _hook_visibility(self, tv):
        cls = tv.getClass()
        name = str(cls.getName())
        if name in self._vis_hooked:
            return
        self._vis_hooked.add(name)
        def after(param):
            if self._order:
                self._schedule_resync(450)
        self._hook(cls, "setViewVisible", 3, _TabHook(self, None, after))
    def _inject(self, act, refresh=False):
        if act is None or not self._hooked or not self._entries or self.mode != "add":
            return
        if not self._probe_ok(act):
            return
        tv = reflect.field(act, "tabsView")
        if tv is None:
            return
        if self._has_ours(act, tv):
            if refresh:
                self._refresh_adapter(act)
            self._schedule_resync(150)
            return
        with tolerated():
            self._do_inject(act, tv)
            if refresh:
                self._refresh_adapter(act)
    def _strip(self, act, tv):
        for i in range(int(tv.getChildCount()) - 1, -1, -1):
            c = tv.getChildAt(i)
            if self._is_ours(c):
                with tolerated():
                    tv.removeView(c)
        with tolerated():
            if len(act.tabs) > self._nbase():
                act.tabs = jarray(self._arr_cls())(list(act.tabs)[:self._nbase()])
        for e in self._entries.values():
            e.view = None
        self._order = []
        self._sig = None
    def _do_inject(self, act, tv):
        for i in range(int(tv.getChildCount()) - 1, -1, -1):
            if self._is_ours(tv.getChildAt(i)):
                tv.removeView(tv.getChildAt(i))
        order = self._sorted()
        views = []
        for e in order:
            v = self._make_glass(act, e)
            self._set_label(v, strings(e.title_key) if e.title_key else e.title)
            with tolerated():
                v.setContentDescription(_DESC + e.id)
            v.setOnClickListener(_inj_click()(
          lambda _v, e=e: self._goto(self._find_main() or act, self._pos_of_entry(e))))
            e.view = v
            e.title_hidden = None
            views.append(v)
        with tolerated():
            self._hook_adapter(act)
        with tolerated():
            reflect.invoke(act, "getFragmentsCount")
        base = list(act.tabs)[:self._nbase()]
        act.tabs = jarray(self._arr_cls())(base + views)
        self._order = order
        self._sig = tuple(e.id for e in order)
        for v in views:
            tv.addView(v, int(tv.getChildCount()))
        self._place_all(tv)
        for v in views:
            with tolerated():
                reflect.invoke(tv, "setViewVisible", v, True, False)
            with tolerated():
                reflect.invoke(tv, "addTabToIgnoreClick", v)
        with tolerated():
            try:
                margin = int(jclass("org.telegram.ui.DialogsActivity").MAIN_TABS_MARGIN)
            except Exception:
                margin = 8
            dp = lambda x: int(jclass("org.telegram.messenger.AndroidUtilities").dp(float(x)))
            fill = False
            with tolerated():
                fill = bool(reflect.field(tv, "fillAvailableWidth"))
            cur = 0
            with tolerated():
                cur = int(reflect.field(tv, "maxWidthPx") or 0)
            want = dp(328 + margin * 2 + 64 * len(views))
            if not fill and want > cur:
                reflect.invoke(tv, "setMaxWidth", want)
        with tolerated():
            self._hook_visibility(tv)
        self._bind_stock_clicks(base)
        self._last_inject = time.time()
        self._schedule_resync(700, keep=True)
        with tolerated():
            cur = int(reflect.invoke(reflect.field(act, "viewPager"), "getCurrentPosition"))
            self._select(act, cur, False, False, all_tabs=True)
        self._sync_titles(act)

    def _nbase(self):
        return int(self._tbase) if self._tbase else _TAB_BASE_TABS
    def _arr_cls(self):
        return self._tcls if self._tcls is not None else jclass(_GTV_CLASS)
    def _probe_ok(self, act):
        key = reflect.identity_hash(act)
        if self._probed is not None and self._probed[0] == key:
            return self._probed[1]
        info = {}
        problems = []
        tabs = tv = vp = None
        with tolerated():
            tabs = reflect.field(act, "tabs")
        with tolerated():
            tv = reflect.field(act, "tabsView")
        with tolerated():
            vp = reflect.field(act, "viewPager")
        info["tabs"] = "missing" if tabs is None else "%d x %s" % (len(tabs), _short_cls(tabs[0].getClass()) if len(tabs) else "?")
        info["tabsView"] = "missing" if tv is None else str(tv.getClass().getName())
        info["viewPager"] = "missing" if vp is None else str(vp.getClass().getName())
        if tabs is None or len(tabs) == 0:
            problems.append("tabs array missing")
        if tv is None:
            problems.append("tabsView missing")
        if vp is None:
            problems.append("viewPager missing")
        gtv = reflect.jcls(_GTV_CLASS)
        if gtv is None:
            problems.append("GlassTabView class missing")
        else:
            if not any(str(m.getName()) == "createMainTab" for m in gtv.getMethods()):
                problems.append("GlassTabView.createMainTab missing")
            if tabs is not None and len(tabs) and not gtv.isInstance(tabs[0]):
                problems.append("stock tabs are %s, not GlassTabView (Material 3 bar?)" % str(tabs[0].getClass().getName()))
        if tv is not None:
            for need in ("setViewVisible", "addTabToIgnoreClick"):
                if not _has_method(tv, need):
                    problems.append("tabsView.%s missing" % need)
        for name in ("getFragmentsCount", "createBaseFragmentAt", "selectTab"):
            if not _has_method(act, name):
                problems.append("MainTabsActivity.%s missing" % name)
        if not problems:
            ours = 0
            for t in tabs:
                if self._is_ours(t):
                    ours += 1
            self._tbase = len(tabs) - ours
            with tolerated():
                self._tcls = jclass(str(act.getClass().getDeclaredField("tabs").getType().getComponentType().getName()))
            info["base tabs"] = self._tbase
        info["result"] = "ok" if not problems else "UNSUPPORTED: " + "; ".join(problems)
        self.probe_info = info
        self._probed = (key, not problems)
        if problems:
            if not getattr(self, "_warned", False):
                self._warned = True
                with tolerated():
                    run_on_ui_thread(lambda: self.p._bulletin(strings("tab_add_unsupported"), error=True), 800)
        return not problems


    def _contacts_labels(self, act):
        want = set()
        with tolerated():
            ctx = act.getContext()
            res = ctx.getResources()
            pkg = ctx.getPackageName()
            names = ("MainTabsSettings", "Settings") if self.target == "settings" else ("MainTabsContacts", "Contacts")
            for name in names:
                rid = int(res.getIdentifier(name, "string", pkg))
                if rid:
                    want.add(str(ctx.getString(rid)).strip().lower())
        return want
    def _contacts_tab_index(self, act, tabs, pos=None):
        if pos is not None:
            cands = []
            for i in range(len(tabs)):
                with tolerated():
                    if int(reflect.invoke(act, "indexToPosition", jint(i))) == pos:
                        cands.append(i)
            vis = []
            for i in cands:
                with tolerated():
                    if int(tabs[i].getVisibility()) == 0:
                        vis.append(i)
            if vis:
                return vis[0], "position, visible"
            if cands:
                return cands[0], "position, hidden"
        want = self._contacts_labels(act)
        for i, t in enumerate(tabs):
            vals = []
            for tvw in self._text_views(t):
                with tolerated():
                    vals.append(str(tvw.getText()).strip().lower())
            if want and any(v in want for v in vals):
                return i, "label"
        if self._cidx is not None and self._cidx < len(tabs):
            return self._cidx, "cached"
        d = 2 if self.target == "settings" else 1
        return (d, "default") if len(tabs) > d else (None, "none")
    def _refresh_cpos(self, act):
        with tolerated():
            self._base = int(reflect.invoke(act, "getFragmentsCount"))
        self._slot_missing = False
        if self.target == "contacts":
            with tolerated():
                if not bool(reflect.invoke(act, "hasContactsOrFeedTab")):
                    self._slot_missing = True
                    self._cpos = None
                    return None
        with tolerated():
            r = int(reflect.invoke(act, "getPositionCallsOrSettings" if self.target == "settings" else "getPositionContacts"))
            self._cpos = r if r >= 0 else None
            return self._cpos
        return self._cpos
    def _resolve_contacts(self, act):
        tabs = []
        with tolerated():
            tabs = list(act.tabs)
        pos = self._refresh_cpos(act)
        if self._slot_missing:
            self._cidx = None
            sig = ("hidden", None, None, self._pages())
            if sig != getattr(self, "_last_sig", None):
                self._last_sig = sig
            return
        idx, how = self._contacts_tab_index(act, tabs, pos)
        self._cidx = idx
        if pos is None and idx is not None:
            stock = self._stock_pages(act, fresh=True)
            if stock is not None and idx < len(stock):
                pos = stock[idx]
            if pos is None and idx < self._pages():
                pos = idx
            self._cpos = pos
        sig = (idx, how, self._cpos, self._pages())
        if sig != getattr(self, "_last_sig", None):
            self._last_sig = sig
    def _title_text(self):
        e = next(iter(self._entries.values()), None)
        if e is None:
            return ""
        return strings(e.title_key) if e.title_key else e.title
    def _tab_anim_member(self, tab):
        fld = setter = None
        c = tab.getClass()
        while c is not None and not str(c.getName()).startswith("android."):
            with tolerated():
                for f in c.getDeclaredFields():
                    if fld is None and str(f.getType().getName()).endswith("$TabAnimation") \
                            and not (int(f.getModifiers()) & 8):
                        f.setAccessible(True)
                        fld = f
            with tolerated():
                for m in c.getDeclaredMethods():
                    ps = m.getParameterTypes()
                    if setter is None and str(m.getName()) == "setTabAnimation" and len(ps) == 1:
                        m.setAccessible(True)
                        setter = m
            c = c.getSuperclass()
        return fld, setter
    def _set_icon(self, tab):
        amap = self._anim_map()
        music = amap.get("MUSIC") or (list(amap.values())[0] if amap else None)
        if music is not None:
            fld, setter = self._tab_anim_member(tab)
            orig = None
            with tolerated():
                orig = fld.get(tab) if fld is not None else None
            if setter is not None:
                with tolerated():
                    setter.invoke(tab, music)
                    self._orig_tab["icon"] = ("method", setter, orig)
                    return "setTabAnimation()"
            if fld is not None:
                with tolerated():
                    fld.set(tab, music)
                    tab.invalidate()
                    self._orig_tab["icon"] = ("field", fld, orig)
                    return "field " + str(fld.getName()) + " (no setter, may not redraw)"
        with tolerated():
            ctx = tab.getContext()
            rid = int(ctx.getResources().getIdentifier("files_music", "drawable", ctx.getPackageName()))
            if rid:
                dr = ctx.getDrawable(rid).mutate()
                for iv in self._image_views(tab):
                    self._orig_tab.setdefault("drawables", []).append((iv, iv.getDrawable()))
                    iv.setImageDrawable(dr)
                    return "ImageView drawable"
        return "unchanged (no icon hook found)"
    def _image_views(self, view):
        out = []
        with tolerated():
            iv = reflect.jcls("android.widget.ImageView")
            vg = reflect.jcls("android.view.ViewGroup")
            stack = [view]
            while stack:
                v = stack.pop()
                if iv.isInstance(v):
                    out.append(v)
                elif vg.isInstance(v):
                    for i in range(int(v.getChildCount())):
                        stack.append(v.getChildAt(i))
        return out
    def _counter_members(self, tab):
        cname = str(tab.getClass().getName())
        if self._cm is not None and self._cm[0] == cname:
            return self._cm[1], self._cm[2]
        anims, objs = [], []
        c = tab.getClass()
        while c is not None and not str(c.getName()).startswith("android."):
            for f in c.getDeclaredFields():
                with tolerated():
                    if int(f.getModifiers()) & 8:
                        continue
                    tn = str(f.getType().getName())
                    if "ounter" in tn or "ounter" in str(f.getName()):
                        f.setAccessible(True)
                        (anims if tn.endswith("BoolAnimator") else objs).append(f)
            c = c.getSuperclass()
        self._cm = (cname, anims, objs)
        return anims, objs
    def _suppress_counter(self, tab):
        anims, objs = self._counter_members(tab)
        for f in anims:
            with tolerated():
                a = f.get(tab)
                if a is not None:
                    reflect.invoke(a, "setValue", False, False)
        View = reflect.jcls("android.view.View")
        for f in objs:
            with tolerated():
                o = f.get(tab)
                if o is None:
                    continue
                if View.isInstance(o):
                    o.setVisibility(8)
                    o.setAlpha(0.0)
                else:
                    reflect.invoke(o, "setCount", jint(0), False)
        with tolerated():
            vg = reflect.jcls("android.view.ViewGroup")
            stack = [tab]
            while stack:
                v = stack.pop()
                if vg.isInstance(v):
                    for i in range(v.getChildCount()):
                        ch = v.getChildAt(i)
                        if "ounter" in str(ch.getClass().getSimpleName()):
                            ch.setVisibility(8)
                        stack.append(ch)
        with tolerated():
            tab.invalidate()
    def _suppress_counter_now(self):
        if self.mode != "replace" or not self._orig_tab:
            return
        tab = self._orig_tab.get("tab")
        if tab is None:
            return
        self._suppress_counter(tab)
        run_on_ui_thread(lambda: self._suppress_counter(tab), 300)
    def _counter_tick(self):
        if not self._counter_watch:
            return
        with tolerated():
            if self._orig_tab and self._orig_tab.get("tab") is not None:
                self._suppress_counter(self._orig_tab["tab"])
        run_on_ui_thread(self._counter_tick, 2000)
    def _style_contacts_tab(self, act):
        tabs = list(act.tabs)
        idx = self._cidx
        if idx is None or idx >= len(tabs):
            return
        tab = tabs[idx]
        h = reflect.identity_hash(tab)
        if self._orig_tab is not None and self._orig_tab.get("h") != h:
            self._unstyle_contacts_tab(act)
        if self._orig_tab is None:
            self._orig_tab = {"h": h, "tab": tab, "texts": []}
            for tvw in self._text_views(tab):
                with tolerated():
                    self._orig_tab["texts"].append((tvw, str(tvw.getText())))
            self._set_icon(tab)
        self._set_label(tab, self._title_text())
        with tolerated():
            tab.setContentDescription(self._title_text())
        self._suppress_counter(tab)
        if not self._counter_watch:
            self._counter_watch = True
            run_on_ui_thread(self._counter_tick, 2000)
    def _unstyle_contacts_tab(self, act):
        o = self._orig_tab
        self._orig_tab = None
        if not o:
            return
        for tvw, text in o.get("texts", []):
            with tolerated():
                tvw.setText(text)
        ic = o.get("icon")
        if ic is not None and ic[2] is not None:
            with tolerated():
                if ic[0] == "method":
                    ic[1].invoke(o["tab"], ic[2])
                else:
                    ic[1].set(o["tab"], ic[2])
                    o["tab"].invalidate()
        for iv, dr in o.get("drawables", []):
            with tolerated():
                iv.setImageDrawable(dr)
    def _apply_replace(self, act, fallback=True):
        if self.mode != "replace" or act is None or not self._entries:
            return
        with tolerated():
            self._resolve_contacts(act)
            self._style_contacts_tab(act)
            if fallback and (self._cpos is None or not self.hook_report.get("createBaseFragmentAt")):
                tabs = list(act.tabs)
                if self._cidx is not None and self._cidx < len(tabs):
                    k = reflect.identity_hash(tabs[self._cidx])
                    if k not in self._clicks:
                        self._clicks[k] = (tabs[self._cidx], self._orig_click(tabs[self._cidx]))
                    tabs[self._cidx].setOnClickListener(_inj_click()(lambda _v: self.p._open_queue_editor()))

    def _wrap_contacts_click(self, act):
        tabs = list(act.tabs)
        if self._cidx is None or self._cidx >= len(tabs):
            return
        tab = tabs[self._cidx]
        key = reflect.identity_hash(tab)
        if key in self._clicks_wrapped:
            return
        ent = self._clicks.get(key)
        orig = ent[1] if ent else self._orig_click(tab)
        if orig is None:
            return
        self._clicks[key] = (tab, orig)
        self._clicks_wrapped.add(key)
        def click(v, orig=orig):
            orig.onClick(v)
            if self._pending_rebuild:
                self._schedule_resync(350)
        tab.setOnClickListener(_inj_click()(click))
    def _holds_ours(self, state):
        if self._entry_of_page(state) is not None:
            return True
        c = state.getClass()
        while c is not None and not str(c.getName()).startswith("java."):
            for f in c.getDeclaredFields():
                with tolerated():
                    f.setAccessible(True)
                    v = f.get(state)
                    if v is not None and self._entry_of_page(v) is not None:
                        return True
            c = c.getSuperclass()
        return False
    def _page_at(self, act, pos):
        with tolerated():
            arr = reflect.field(act, "fragmentsArr")
            if arr is not None:
                return arr.get(jint(pos))
        return None
    def _converge_replace(self, act, tries=0):
        if self.mode != "replace" or act is None or not self._entries:
            return
        self._apply_replace(act, fallback=False)
        def again(delay=400):
            if tries < 10:
                run_on_ui_thread(lambda: self._converge_replace(self._find_main() or act, tries + 1), delay)
        if self._slot_missing:
            return
        if self._cpos is None:
            again(350)
            return
        with tolerated():
            self._wrap_contacts_click(act)
        if not self._pending_rebuild:
            return
        vp = reflect.field(act, "viewPager")
        if vp is None:
            return
        if reflect.invoke(vp, "isManualScrolling") or reflect.invoke(vp, "isTouch"):
            again(400)
            return
        frag = self._page_at(act, self._cpos)
        if frag is not None and self._holds_ours(frag):
            self._pending_rebuild = False
            return
        if frag is None:
            return
        if self._hops >= 3:
            self._pending_rebuild = False
            return
        self._hops += 1
        with tolerated():
            reflect.invoke(act, "dropFragmentAtPosition", jint(self._cpos))
        with tolerated():
            reflect.invoke(act, "checkFragmentsVisibility")
        again(450)

    def _apply_existing(self):
        with tolerated():
            act = self._find_main()
            if act is None:
                return
            if self.mode == "replace":
                self._converge_replace(act)
                return
            self._inject(act, refresh=True)
            if self._hopped or not self._order:
                return
            vp = reflect.field(act, "viewPager")
            if vp is None:
                return
            lay = self._layout()
            cur = int(reflect.invoke(vp, "getCurrentPosition"))
            if 0 <= cur < len(lay) and lay[cur][0] == "e":
                e = lay[cur][1]
                away = self._pos_of_stock(0, lay)
                if away == cur:
                    away = max(0, cur - 1)
                if not self._goto(act, away):
                    self._apply_tries += 1
                    if self._apply_tries < 10:
                        run_on_ui_thread(self._apply_existing, 450)
                    return
                self._hopped = True
                def back():
                    a = self._find_main()
                    if a is not None:
                        self._refresh_adapter(a)
                        self._goto(a, self._pos_of_entry(e))
                        self._schedule_resync(250)
                run_on_ui_thread(back, 220)
    def _stock_pages(self, act, fresh=True):
        base = self._pages()
        cache = self._map_cache
        if not fresh and cache is not None and cache[0] == base:
            return cache[1]
        tabs = act.tabs
        n = min(len(tabs), self._nbase())
        vis = []
        for i in range(n):
            with tolerated():
                t = tabs[i]
                if int(t.getVisibility()) == 0 and float(t.getAlpha()) > 0.05:
                    vis.append(i)
        raw = None
        try:
            raw = [int(reflect.invoke(act, "indexToPosition", jint(i))) for i in range(n)]
        except Exception:
            raw = None
        mapping = None
        if len(vis) == base:
            mapping = [None] * n
            for rank, i in enumerate(vis):
                mapping[i] = rank
        elif raw is not None:
            real = [p for p in raw if p >= 0]
            if len(real) == base and len(set(real)) == base and max(real) < base:
                mapping = [p if p >= 0 else None for p in raw]
        if mapping is None:
            if cache is not None and cache[0] == base:
                return cache[1]
            return None
        self._map_cache = (base, mapping)
        return mapping
    def _page_of(self, i, lay, stock):
        if i >= self._nbase():
            k = i - self._nbase()
            return self._pos_of_entry(self._order[k], lay) if k < len(self._order) else -99
        if stock is None:
            return -99
        sp = stock[i] if i < len(stock) else None
        return -99 if sp is None else self._pos_of_stock(sp, lay)
    def _select(self, act, pos, flag, gesture, all_tabs=False):
        tabs = act.tabs
        if len(tabs) <= self._nbase():
            return
        lay = self._layout()
        stock = self._stock_pages(act, fresh=not gesture)
        skip_stock = stock is None
        if skip_stock:
            self._schedule_resync(300)
        for i in range(len(tabs)):
            if not (gesture or all_tabs) and i < self._nbase():
                continue
            if skip_stock and i < self._nbase():
                continue
            page = self._page_of(i, lay, stock)
            if gesture:
                tabs[i].setGestureSelectedOverride(max(0.0, 1.0 - abs(page - pos)), flag)
            else:
                tabs[i].setSelected(int(round(pos)) == page, flag)
        if gesture:
            with tolerated():
                act.tabsView.invalidate()
    def _orig_click(self, view):
        try:
            li = reflect.field(view, "mListenerInfo")
            return reflect.field(li, "mOnClickListener") if li is not None else None
        except Exception:
            return None
    def _bind_stock_clicks(self, base):
        live = set(reflect.identity_hash(t) for t in base)
        for k in [k for k in self._clicks if k not in live]:
            del self._clicks[k]
        for i, tab in enumerate(base):
            key = reflect.identity_hash(tab)
            if key not in self._clicks:
                self._clicks[key] = (tab, self._orig_click(tab))
            tab.setOnClickListener(_inj_click()(lambda v, i=i: self._stock_click(v, i)))
    def _stock_click(self, v, i):
        ent = self._clicks.get(reflect.identity_hash(v))
        orig = ent[1] if ent else None
        act = self._find_main()
        stock = self._stock_pages(act) if act is not None else None
        if act is None or stock is None or not self._entries:
            if stock is None:
                self._schedule_resync(300)
            if orig is not None:
                orig.onClick(v)
            return
        lay = self._layout()
        pg = self._page_of(i, lay, stock)
        if pg < 0:
            return
        if pg == stock[i] and orig is not None:
            orig.onClick(v)
            return
        self._goto(act, pg)
    def _goto(self, act, pos):
        vp = reflect.field(act, "viewPager")
        if vp is None or pos < 0:
            return False
        self._rebound = True
        if reflect.invoke(vp, "isManualScrolling") or reflect.invoke(vp, "isTouch"):
            return False
        if int(reflect.invoke(vp, "getCurrentPosition")) == pos:
            return True
        reflect.invoke(act, "selectTab", jint(pos), True)
        reflect.invoke(vp, "scrollToPosition", jint(pos))
        return True
    def open_chats_search(self, query, search_type):
        def fail():
            self.p._bulletin(strings("couldnt_open_artist_search"), error=True)
        try:
            act = self._find_main()
            page = reflect.invoke(act, "getDialogsActivity") if act is not None else None
            if page is None:
                raise RuntimeError("Chats page unavailable")
            arr = reflect.field(act, "fragmentsArr")
            def holds(state):
                if state is None:
                    return False
                if bool(page.equals(state)):
                    return True
                c = state.getClass()
                while c is not None:
                    for fld in c.getDeclaredFields():
                        with tolerated():
                            fld.setAccessible(True)
                            v = fld.get(state)
                            if v is not None and bool(page.equals(v)):
                                return True
                    c = c.getSuperclass()
                return False
            keys = [int(arr.keyAt(i)) for i in range(int(arr.size())) if holds(arr.valueAt(i))]
            if len(keys) != 1:
                raise RuntimeError("Chats position unavailable")
            target = self._pos_of_stock(keys[0])
            self._goto(act, target)
            vp = reflect.field(act, "viewPager")
        except Exception:
            fail()
            return
        def has(name, n):
            c = page.getClass()
            while c is not None:
                for m in c.getDeclaredMethods():
                    if str(m.getName()) == name and int(m.getParameterCount()) == n:
                        return True
                c = c.getSuperclass()
            return False
        tries = [0]
        def run():
            try:
                if int(reflect.invoke(vp, "getCurrentPosition")) != target:
                    if tries[0] >= 30:
                        raise RuntimeError("tab switch timeout")
                    tries[0] += 1
                    run_on_ui_thread(run, 100)
                    return
                if has("search", 2) and has("setInitialSearchType", 1):
                    reflect.invoke(page, "setInitialSearchType", jint(int(search_type)))
                    reflect.invoke(page, "search", query, False)
                else:
                    reflect.invoke(page, "setShowSearch", query, jint(int(search_type)))
            except Exception:
                fail()
        run_on_ui_thread(run)
    def owns(self):
        try:
            st = jclass("org.telegram.ui.LaunchActivity").instance.getActionBarLayout().getFragmentStack()
            n = int(st.size())
            return n > 0 and bool(self._tab_mt.isInstance(st.get(n - 1)))
        except Exception:
            return False
    def _schedule_resync(self, delay=300, keep=False):
        tok = None
        if not keep:
            self._tok += 1
            tok = self._tok
        def run():
            if tok is None or self._tok == tok:
                self._resync()
        with tolerated():
            run_on_ui_thread(run, delay)
    def _resync(self):
        with tolerated():
            if not self._hooked or not self._entries:
                return
            act = self._find_main()
            if self.mode == "replace":
                self._converge_replace(act)
                return
            tv = reflect.field(act, "tabsView") if act is not None else None
            if tv is None:
                return
            if not self._has_ours(act, tv):
                if time.time() - self._last_inject < 2.0:
                    self._schedule_resync(2000)
                    return
                self._inject(act)
                return
            self._stash = []
            self._bind_stock_clicks(list(act.tabs)[:self._nbase()])
            self._map_cache = None
            self._place_all(tv)
            self._show_all(tv)
            self._sync_titles(act)
            vp = reflect.field(act, "viewPager")
            if vp is None:
                return
            if reflect.invoke(vp, "isManualScrolling") or reflect.invoke(vp, "isTouch"):
                self._schedule_resync(400)
                return
            self._select(act, int(reflect.invoke(vp, "getCurrentPosition")), False, False, all_tabs=True)
    def _teardown(self):
        if self.mode == "replace":
            act = self._find_main()
            if act is not None:
                self._unstyle_contacts_tab(act)
        for view, listener in list(self._clicks.values()):
            if listener is None:
                continue
            with tolerated():
                view.setOnClickListener(listener)
        self._clicks = {}
        self._map_cache = None
        act = self._find_main()
        tv = reflect.field(act, "tabsView") if act is not None else None
        if tv is not None:
            self._strip(act, tv)
            self._refresh_adapter(act)
        self._order = []
        self._sig = None


_TAB_LABEL = "music"
_TAB_BAR_DP = 56
_TAB_GAP_DP = 14


class _TabHook(MethodHook):
    def __init__(self, plugin, before=None, after=None):
        self.plugin = plugin
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


class _TabDialog:
    def __init__(self, editor):
        self.ed = editor
        self.dead = False
    def isShowing(self):
        return not self.dead
    def dismiss(self):
        pass
    def kill(self):
        if self.dead:
            return
        self.dead = True
        with tolerated():
            self.ed._on_dismiss()


_PROGRESSIVE_PREV_TRACKS = 25
