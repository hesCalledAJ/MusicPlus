import os
import re
import threading
import time
import traceback
from collections import deque

from .compat import dynamic_proxy, find_class, jclass, run_on_ui_thread
from .meta import _PLUGIN_VERSION
from .safe import tolerated

_TRAIL = deque(maxlen=24)
_STATE = {"dir": None, "alive": False, "handler": None, "prev": None, "plugin": None}
_PREFIX = re.compile(r"^\S+\s+\S+\s+\d+\s+\d+\s+\w\s+[^:]*:\s?")


def _dir():
    if _STATE["dir"] is None:
        ctx = find_class("org.telegram.messenger.ApplicationLoader").applicationContext
        d = os.path.join(str(ctx.getFilesDir().getAbsolutePath()), "musicplus_crash")
        os.makedirs(d, exist_ok=True)
        _STATE["dir"] = d
    return _STATE["dir"]


def _write(name, text):
    with open(os.path.join(_dir(), name), "w", encoding="utf-8", errors="replace") as f:
        f.write(text)


def _read(name):
    try:
        with open(os.path.join(_dir(), name), encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def _rm(name):
    with tolerated():
        os.remove(os.path.join(_dir(), name))


def crumb(msg):
    _TRAIL.append(time.strftime("%H:%M:%S ") + str(msg)[:120])


def arm(stage):
    crumb("ARM " + stage)
    with tolerated():
        _write("pending.txt", stage)


def disarm(stage=""):
    _rm("pending.txt")
    crumb("DISARM " + stage)


def _device():
    out = ""
    with tolerated():
        B, V = jclass("android.os.Build"), jclass("android.os.Build$VERSION")
        out = f"{B.MODEL} · Android {V.RELEASE} (API {V.SDK_INT})"
    with tolerated():
        out += f" · TG {find_class('org.telegram.messenger.BuildVars').BUILD_VERSION_STRING}"
    return out


def short_trace(text, frames=12):
    out, n, last, rep = [], 0, None, 0
    for ln in str(text).replace("\r", "").split("\n"):
        ln = _PREFIX.sub("", ln).rstrip()
        if not ln:
            continue
        if ln == last:
            rep += 1
            continue
        if rep:
            out.append(f"  (x{rep + 1})")
            rep = 0
        last = ln
        if ln.lstrip().startswith("at "):
            n += 1
            if n > frames:
                continue
        else:
            n = 0
        out.append(ln)
    if rep:
        out.append(f"  (x{rep + 1})")
    return "\n".join(out)


def compose(kind, trace="", pending=""):
    lines = [f"Music + {_PLUGIN_VERSION} · {time.strftime('%Y-%m-%d %H:%M')}", _device(), kind]
    if pending:
        lines.append("was running: " + pending)
    if trace:
        lines += ["", short_trace(trace)]
    if _TRAIL:
        lines += ["", "last steps:", *list(_TRAIL)[-10:]]
    return "\n".join(lines)


_EXIT_REASONS = {2: "SIGNALED", 3: "LOW_MEMORY", 4: "CRASH", 5: "CRASH_NATIVE", 6: "ANR", 7: "INIT_FAILURE",
                 8: "PERMISSION_CHANGE", 9: "EXCESSIVE_RESOURCES", 12: "DEPENDENCY_DIED", 13: "OTHER", 14: "FREEZER"}


def _exit_tail():
    with tolerated():
        if int(jclass("android.os.Build$VERSION").SDK_INT) < 30:
            return ""
        ctx = find_class("org.telegram.messenger.ApplicationLoader").applicationContext
        am = ctx.getSystemService("activity")
        infos = am.getHistoricalProcessExitReasons(str(ctx.getPackageName()), 0, 6)
        out = []
        for k in range(int(infos.size())):
            e = infos.get(k)
            reason = int(e.getReason())
            if reason not in _EXIT_REASONS:
                continue
            when = time.strftime("%m-%d %H:%M:%S", time.localtime(int(e.getTimestamp()) / 1000.0))
            out.append("%s %s (status %s) %s\n  %s" % (when, _EXIT_REASONS[reason], int(e.getStatus()),
                                                      str(e.getProcessName()), str(e.getDescription() or "")))
            if len(out) >= 2:
                break
        return "\n".join(out)[:1500]
    return ""


def _enabled():
    try:
        return bool(_STATE["plugin"].get_setting("show_crash_reports", False))
    except Exception:
        return False


def install(plugin=None):
    _STATE["alive"] = True
    _STATE["plugin"] = plugin
    with tolerated():
        T = jclass("java.lang.Thread")
        prev = T.getDefaultUncaughtExceptionHandler()

        class _Handler(dynamic_proxy(jclass("java.lang.Thread$UncaughtExceptionHandler"))):
            def __init__(self, nxt):
                super().__init__()
                self.nxt = nxt

            def uncaughtException(self, thread, ex):
                with tolerated():
                    if _STATE["alive"]:
                        tr = str(jclass("android.util.Log").getStackTraceString(ex))
                        _write("crash.txt", compose("Crash on thread " + str(thread.getName()), trace=tr))
                if self.nxt is not None:
                    self.nxt.uncaughtException(thread, ex)

        h = _Handler(prev)
        _STATE["handler"], _STATE["prev"] = h, prev
        T.setDefaultUncaughtExceptionHandler(h)
    with tolerated():
        _check_previous_run()


def uninstall():
    _STATE["alive"] = False
    with tolerated():
        T = jclass("java.lang.Thread")
        if _STATE["handler"] is not None and T.getDefaultUncaughtExceptionHandler() == _STATE["handler"]:
            T.setDefaultUncaughtExceptionHandler(_STATE["prev"])


def _check_previous_run():
    crash, pending = _read("crash.txt"), _read("pending.txt").strip()
    body = crash
    if not body and pending:
        body = compose("The app died while running this (native crash or kill)", pending=pending)
        tail = _exit_tail()
        if tail:
            body += "\n\nprocess exit info:\n" + tail
    _rm("crash.txt")
    _rm("pending.txt")
    if body and _enabled():
        _later(lambda: _show_now(body, "Music + crashed last time"), 2500)


def report(where, exc=None, kind="Error"):
    if not _enabled():
        return
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc is not None else ""
    body = compose(f"{kind}: {where}", trace=tb)
    _later(lambda: _show_now(body, where), 100)


def show_log(title, log_text):
    body = compose(title) + "\n\n" + str(log_text)
    _later(lambda: _show_now(body, title), 100)


def _later(fn, ms):
    def go():
        with tolerated():
            run_on_ui_thread(fn)
    t = threading.Timer(ms / 1000.0, go)
    t.daemon = True
    t.start()


def _activity():
    with tolerated():
        from .compat import get_last_fragment
        f = get_last_fragment()
        return f.getParentActivity() if f is not None else None
    return None


def _show_now(full, title):
    act = _activity()
    if act is None:
        _later(lambda: _show_now(full, title), 1500)
        return
    from .android import _proxies
    Click = _proxies()[1]
    LL = jclass("android.widget.LinearLayout")
    TV = jclass("android.widget.TextView")
    SV = jclass("android.widget.ScrollView")
    GD = jclass("android.graphics.drawable.GradientDrawable")
    LP = jclass("android.widget.LinearLayout$LayoutParams")
    d = float(act.getResources().getDisplayMetrics().density)

    def dp(v):
        return int(round(v * d))

    def color(a, r, g, b):
        v = (a << 24) | (r << 16) | (g << 8) | b
        return v - (1 << 32) if v & 0x80000000 else v

    WHITE, BLUE = color(255, 255, 255, 255), color(255, 0, 90, 158)
    dlg = jclass("android.app.Dialog")(act, 16973831)
    root = LL(act)
    root.setOrientation(1)
    root.setBackgroundColor(BLUE)
    root.setPadding(dp(20), dp(36), dp(20), dp(16))

    def text(s, size, bold=False, mono=False, alpha=255):
        t = TV(act)
        t.setText(str(s))
        t.setTextSize(float(size))
        t.setTextColor(color(alpha, 255, 255, 255))
        if bold:
            t.setTypeface(jclass("android.graphics.Typeface").DEFAULT_BOLD)
        if mono:
            t.setTypeface(jclass("android.graphics.Typeface").MONOSPACE)
        return t

    root.addView(text(":(", 54), LP(-2, -2))
    tt = text("Music + ran into a problem", 20, bold=True)
    tt.setPadding(0, dp(8), 0, 0)
    root.addView(tt, LP(-1, -2))
    st = text(f"{title}\nSend this to the developer.", 13, alpha=220)
    st.setPadding(0, dp(6), 0, dp(10))
    root.addView(st, LP(-1, -2))
    sv = SV(act)
    log = text(full, 11, mono=True)
    log.setTextIsSelectable(True)
    sv.addView(log)
    root.addView(sv, LP(-1, 0, 1.0))
    row = LL(act)
    row.setOrientation(0)
    row.setPadding(0, dp(12), 0, 0)

    def toast(s):
        with tolerated():
            jclass("android.widget.Toast").makeText(act, str(s), 0).show()

    def copy(_v):
        cm = act.getSystemService("clipboard")
        cm.setPrimaryClip(jclass("android.content.ClipData").newPlainText("Music + log", full))
        toast("Log copied")

    def saved(_v):
        def work():
            ok, err = False, "plugin not ready"
            with tolerated():
                from .helpers import _PLUGIN_REF
                p = _PLUGIN_REF.get("plugin")
                ctx = find_class("org.telegram.messenger.ApplicationLoader").applicationContext
                base = ctx.getExternalCacheDir() or ctx.getCacheDir()
                path = os.path.join(str(base.getAbsolutePath()), f"MusicPlus-log-{time.strftime('%Y%m%d-%H%M%S')}.txt")
                with open(path, "w", encoding="utf-8", errors="replace") as f:
                    f.write(full)
                ok, err = p._xfer_send_saved(path, "Music + crash log")
            _later(lambda: toast("Sent to Saved Messages" if ok else "Couldn't send: " + str(err)), 10)
        threading.Thread(target=work, daemon=True).start()

    def button(label, fn, first=False):
        b = TV(act)
        b.setText(label)
        b.setTextSize(13.0)
        b.setTextColor(WHITE)
        b.setGravity(17)
        b.setPadding(dp(6), dp(12), dp(6), dp(12))
        bg = GD()
        bg.setColor(color(60, 255, 255, 255))
        bg.setCornerRadius(float(dp(10)))
        b.setBackground(bg)
        b.setOnClickListener(Click(fn))
        lp = LP(0, -2, 1.0)
        if not first:
            lp.setMargins(dp(8), 0, 0, 0)
        row.addView(b, lp)

    button("Copy", copy, True)
    button("Saved Messages", saved)
    button("Close", lambda _v: dlg.dismiss())
    root.addView(row, LP(-1, -2))
    dlg.setContentView(root)
    dlg.setCancelable(True)
    dlg.show()
