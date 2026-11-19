from elyx import strings

from .android import _mix, _proxy
from .compat import dynamic_proxy, get_last_fragment, jclass, run_on_ui_thread
from .editor import _QueueEditor
from .native_sheets import _NativeSheet
from .safe import tolerated
from . import tabs as _tabs

_TAB_LABEL = "music"
_ANIM = {"chats": "CHATS", "contacts": "CONTACTS", "feed": "FEED", "settings": "SETTINGS", "music": "MUSIC"}
_GLYPH = {"chats": "\U0001F4AC", "contacts": "\U0001F465", "feed": "\U0001F4F0", "settings": "\u2699",
          "profile": "\U0001F464", "music": "\U0001F3B5"}


def tab_label(key):
    return strings(_TAB_LABEL) if key == "music" else strings("tab_" + key)


def tab_index(plugin):
    try:
        ix = int(str(plugin.get_setting("tab_index", "") or "").strip())
    except Exception:
        return None
    return 2 if ix == 1 else ix


def stock_bar():
    slot = "feed" if _tabs.host_feed_tab_on() else "contacts"
    bar = ["chats"]
    if _tabs.host_has_slot() is not False:
        bar.append(slot)
    return bar + ["settings", "profile"], slot


def contacts_off():
    return _tabs.host_has_slot() is False


def bar_for(plugin, style):
    stock, slot = stock_bar()
    notes = []
    if style == 1:
        if contacts_off():
            notes.append(strings("tab_note_contacts_off"))
            return list(stock), notes
        notes.append(strings("tab_note_replace_feed") if slot == "feed" else strings("tab_note_replace"))
        return ["music" if k == slot else k for k in stock], notes
    if style == 3:
        notes.append(strings("tab_note_replace_settings"))
        return ["music" if k == "settings" else k for k in stock], notes
    if style == 2:
        mine = list(stock)
        ix = tab_index(plugin)
        d = (ix - 1) if ix is not None else len(mine)
        mine.insert(max(0, min(d, len(mine))), "music")
        notes.append(strings("tab_note_add_at", ix) if ix is not None else strings("tab_note_add_end"))
        return mine, notes
    notes.append(strings("tab_note_off"))
    return list(stock), notes


def summary(plugin):
    style = plugin._tab_style()
    if style == 1:
        if contacts_off():
            return strings("tab_state_contacts_off")
        return strings("tab_state_replace", tab_label("feed" if _tabs.host_feed_tab_on() else "contacts"))
    if style == 3:
        return strings("tab_state_replace", tab_label("settings"))
    return strings("tab_state_add") if style == 2 else strings("tab_state_off")


def show(plugin):
    def go():
        try:
            fr = get_last_fragment()
            act = fr.getParentActivity() if fr is not None else None
            if act is None:
                plugin._bulletin(strings("tab_preview_failed"), error=True)
                return
            _build(plugin, fr, act)
        except Exception:
            plugin._bulletin(strings("tab_preview_failed"), error=True)
    try:
        run_on_ui_thread(go)
    except Exception:
        go()


def _build(plugin, fr, act):
    sh = _NativeSheet(act, strings("tab_sheet_title"), strings("tab_sheet_sub"), 0.9)
    dp = sh.dp
    th = _QueueEditor._theme
    rp = None
    with tolerated():
        rp = fr.getResourceProvider()
    st = {"style": plugin._tab_style()}

    prev = sh.LL(act)
    prev.setOrientation(1)
    prev.setPadding(dp(12), dp(4), dp(12), dp(6))
    sh.root.addView(prev, sh.root.indexOfChild(sh.sv), sh.LP(-1, -2))

    def avatar_view():
        with tolerated():
            v = _tabs.make_preview_avatar(act, rp, tab_label("profile"))
            if v is not None:
                return v, True
        with tolerated():
            box = sh.LL(act)
            box.setGravity(17)
            box.addView(_tabs.make_plain_avatar(act, dp(34)), sh.LP(dp(34), dp(34)))
            return box, False
        return sh.circle(_GLYPH["profile"], 40, False), False

    def tab_view(key):
        if key == "profile":
            return avatar_view()
        with tolerated():
            if key in _ANIM:
                v = _tabs.make_preview_tab(act, rp, _ANIM[key], tab_label(key), key == "music")
                if v is not None:
                    return v, True
        return sh.circle(_GLYPH.get(key, "?"), 40, key == "music"), False

    def render_preview():
        prev.removeAllViews()
        card = sh.LL(act)
        card.setOrientation(1)
        bg = sh.GD()
        bg.setColor(sh.c_item)
        bg.setCornerRadius(float(dp(14)))
        card.setBackground(bg)
        card.setPadding(dp(10), dp(10), dp(10), dp(12))
        mine, notes = bar_for(plugin, st["style"])
        pill = sh.LL(act)
        pill.setOrientation(0)
        pill.setGravity(16)
        pg = sh.GD()
        pg.setColor(_mix(sh.c_item, sh.c_sub, 0.10))
        pg.setCornerRadius(float(dp(30)))
        pill.setBackground(pg)
        pill.setPadding(dp(6), dp(6), dp(6), dp(6))
        for key in mine:
            col = sh.LL(act)
            col.setOrientation(1)
            col.setGravity(17)
            tv, native = tab_view(key)
            col.addView(tv, sh.LP(-1, dp(46)))
            if not native:
                cap = sh.text(tab_label(key), 10, sh.c_accent if key == "music" else sh.c_sub, key == "music", 17, True)
                cap.setPadding(0, dp(2), 0, 0)
                col.addView(cap, sh.LP(-1, -2))
            pill.addView(col, sh.LP(0, -2, 1.0))
        card.addView(pill, sh.LP(-1, -2))
        for n in notes:
            t = sh.text(n, 13, sh.c_sub)
            t.setPadding(dp(6), dp(8), dp(6), 0)
            card.addView(t, sh.LP(-1, -2))
        prev.addView(card, sh.LP(-1, -2))
        with tolerated():
            sh.max_h = int(sh.dm.heightPixels * 0.88) - dp(250)

    def radio(checked):
        with tolerated():
            rb = jclass("org.telegram.ui.Components.RadioButton")(act)
            rb.setSize(dp(20))
            rb.setColor(th("key_radioBackground", sh.c_sub), th("key_radioBackgroundChecked", sh.c_accent))
            rb.setChecked(bool(checked), False)
            return rb
        return sh.text("\u25CF" if checked else "\u25CB", 18, sh.c_accent if checked else sh.c_sub, False, 17)

    def option(card, first, title, sub, checked, cb, enabled=True):
        if not first:
            sh.divider(card, 56)
        row = sh.LL(act)
        row.setOrientation(0)
        row.setGravity(16)
        row.setPadding(dp(16), dp(10), dp(16), dp(10))
        row.addView(radio(checked and enabled), sh.LP(dp(24), dp(24)))
        col = sh.LL(act)
        col.setOrientation(1)
        col.setPadding(dp(16), 0, 0, 0)
        col.addView(sh.text(title, 16, sh.c_text), sh.LP(-1, -2))
        if sub:
            col.addView(sh.text(sub, 13, sh.c_sub), sh.LP(-1, -2))
        row.addView(col, sh.LP(0, -2, 1.0))
        if enabled:
            row.setOnClickListener(sh.Click(lambda v: cb()))
            sh.ripple(row, 0)
        else:
            row.setAlpha(0.45)
        card.addView(row, sh.LP(-1, -2))

    def set_style(i):
        st["style"] = i
        plugin.set_setting("tab_style", int(i))
        refresh()

    def set_index(val):
        plugin.set_setting("tab_index", val)
        refresh()

    def render_options():
        sh.body.removeAllViews()
        sh.section(strings("tab_section_where"))
        card = sh.card()
        stock, slot = stock_bar()
        off = contacts_off()
        option(card, True, strings("tab_opt_off"), strings("tab_opt_off_sub"), st["style"] == 0, lambda: set_style(0))
        option(card, False, strings("tab_opt_replace", tab_label(slot)),
               strings("tab_opt_replace_off") if off else strings("tab_opt_replace_sub"),
               st["style"] == 1, lambda: set_style(1), enabled=not off)
        option(card, False, strings("tab_opt_replace", tab_label("settings")), strings("tab_opt_replace_settings_sub"),
               st["style"] == 3, lambda: set_style(3))
        option(card, False, strings("tab_opt_add"), strings("tab_opt_add_sub"), st["style"] == 2, lambda: set_style(2))
        if st["style"] == 2:
            sh.section(strings("tab_section_position"))
            pc = sh.card()
            cur = tab_index(plugin)
            rows = [(strings("tab_pos_after", tab_label(k)), i + 2) for i, k in enumerate(stock[:-1])]
            rows.append((strings("tab_pos_last"), None))
            for n, (label, val) in enumerate(rows):
                option(pc, n == 0, label, None, cur == val, lambda val=val: set_index("" if val is None else str(val)))
        sh.fit()

    def refresh():
        render_preview()
        render_options()

    def on_dismiss():
        with tolerated():
            plugin.set_setting("tab_style", int(st["style"]), reload_settings=True)
        with tolerated():
            if plugin._tab_cfg() != getattr(plugin, "_tab_loaded_cfg", None):
                run_on_ui_thread(lambda: ask_restart(plugin))

    refresh()
    sh.primary_button(strings("done"), sh.dlg.dismiss)
    with tolerated():
        sh.dlg.setOnDismissListener(_dismiss_listener(on_dismiss))
    sh.show()


def ask_restart(plugin, updated_to=None):
    try:
        fr = get_last_fragment()
        act = fr.getParentActivity() if fr is not None else None
        if act is None:
            return
        builder = jclass("org.telegram.ui.ActionBar.AlertDialog$Builder")(act)
        click = _proxy("org.telegram.ui.ActionBar.AlertDialog$OnButtonClickListener", "onClick")
        if updated_to:
            builder.setTitle(strings("update_restart_title"))
            builder.setMessage(strings("update_restart_msg", updated_to))
        else:
            builder.setTitle(strings("tab_restart_title"))
            builder.setMessage(strings("tab_restart_msg"))
        builder.setPositiveButton(strings("tab_restart_now"), click(lambda d, w: restart_app(act)))
        builder.setNegativeButton(strings("tab_restart_later"), click(lambda d, w: None))
        builder.create().show()
    except Exception:
        with tolerated():
            plugin._bulletin(strings("tab_preview_failed"), error=True)


def restart_app(act):
    ctx = act.getApplicationContext()
    Intent = jclass("android.content.Intent")
    pm = ctx.getPackageManager()
    launch = pm.getLaunchIntentForPackage(ctx.getPackageName())
    with tolerated():
        backup = pm.getLaunchIntentForPackage(ctx.getPackageName())
        backup.addFlags(int(Intent.FLAG_ACTIVITY_NEW_TASK))
        PI = jclass("android.app.PendingIntent")
        pi = PI.getActivity(ctx, 7743, backup, int(PI.FLAG_IMMUTABLE) | int(PI.FLAG_UPDATE_CURRENT))
        am = ctx.getSystemService("alarm")
        am.set(1, int(jclass("java.lang.System").currentTimeMillis()) + 900, pi)
    with tolerated():
        restart = Intent.makeRestartActivityTask(launch.getComponent())
        ctx.startActivity(restart)
    P = jclass("android.os.Process")
    P.killProcess(P.myPid())
    jclass("java.lang.System").exit(0)


_DISMISS = None


def _dismiss_listener(fn):
    global _DISMISS
    if _DISMISS is None:
        Iface = jclass("android.content.DialogInterface$OnDismissListener")
        class _D(dynamic_proxy(Iface)):
            def __init__(self, f):
                super().__init__()
                self.f = f
            def onDismiss(self, d):
                with tolerated():
                    self.f()
        _DISMISS = _D
    return _DISMISS(fn)
