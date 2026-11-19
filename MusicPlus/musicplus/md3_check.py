from .compat import get_last_fragment, jclass, run_on_ui_thread
from .android import _proxy
from .safe import tolerated
from elyx import strings

_LINK = "https://t.me/exteraSettings?s=md3Styles"
_KEY = "md3_player_warn_off"


def md3_player_on():
    with tolerated():
        ctx = jclass("org.telegram.messenger.ApplicationLoader").applicationContext
        return bool(ctx.getSharedPreferences("exteraconfig", 0).getBoolean("newPlayerStyle", False))
    return None


def check_and_warn(plugin):
    with tolerated():
        if bool(plugin.get_setting(_KEY, False)):
            return
        if md3_player_on() is not True:
            return
        run_on_ui_thread(lambda: _show(plugin), 2500)


def _show(plugin):
    with tolerated():
        fragment = get_last_fragment()
        act = fragment.getParentActivity() if fragment is not None else None
        if act is None:
            return
        if md3_player_on() is not True:
            return

        def never():
            with tolerated():
                plugin.set_setting(_KEY, True)

        def go():
            plugin._open_link(_LINK)

        msg = strings("md3_player_msg")
        for tg in (True, False):
            try:
                if tg:
                    b = jclass("org.telegram.ui.ActionBar.AlertDialog$Builder")(act)
                    click = _proxy("org.telegram.ui.ActionBar.AlertDialog$OnButtonClickListener", "onClick")
                else:
                    b = jclass("android.app.AlertDialog$Builder")(act)
                    click = _proxy("android.content.DialogInterface$OnClickListener", "onClick")
                b.setTitle("Music +")
                b.setMessage(str(msg))
                b.setPositiveButton(strings("md3_player_ok"), click(lambda d, w: None))
                b.setNeutralButton(strings("md3_player_settings"), click(lambda d, w: go()))
                b.setNegativeButton(strings("md3_player_never"), click(lambda d, w: never()))
                b.create().show()
                return
            except Exception:
                continue
