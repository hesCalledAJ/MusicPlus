import json
import time
from .compat import Any, BasePlugin, BulletinHelper, Divider, Header, List, Selector, Switch, Text, find_class, get_last_fragment, jclass, run_on_ui_thread
from .helpers import _PLUGIN_REF
from .meta import _PLUGIN_VERSION
from . import crashlog as _crashlog
from elyx import strings
from .helpers import _fmt_time, _rd_index
from .android import _cls, _proxies
from .glass import _selector_sub
from .mini_row import _MiniRows
from .chat_card import _Card
from .tabs import _AJ_TAB_ID, _TAB_LABEL, _TabInjector
from . import tab_sheet as _tab_sheet
from . import md3_check as _md3_check
from .telegram_io import _MsgResolver
from .stores import _MessageIndex, _SongStore, _TrackCache, _TrackStore
from .editor import _QueueEditor
from .native_sheets import _NativeSheet
from .features.library_sync import _PluginLibrarySync
from .features.sync_settings import _PluginSyncSettings
from .features.transfer_playback import _PluginTransferPlayback
from .features.archive_share import _PluginArchiveShare
from .features.downloads_profile import _PluginDownloadsProfile
from .features.profile_sync import _PluginProfileSync
from .features.playlists import _PluginPlaylists
from .features.equalizer import _PluginEqualizer
from .features.playback_fx import _PluginPlaybackFx
from .features.queue_ghosts import _PluginQueueGhosts
from .features.cover_cache import _PluginCoverCache
from .features.queue_cache_search import _PluginQueueCacheSearch
from .features.queue_resume import _PluginQueueResume
from .features.undo_filters import _PluginUndoFilters
from . import reflect
from .safe import tolerated


class SmartMusicQueue(
    _PluginUndoFilters,
    _PluginQueueCacheSearch,
    _PluginQueueResume,
    _PluginPlaylists,
    _PluginEqualizer,
    _PluginPlaybackFx,
    _PluginQueueGhosts,
    _PluginCoverCache,
    _PluginDownloadsProfile,
    _PluginProfileSync,
    _PluginTransferPlayback,
    _PluginArchiveShare,
    _PluginSyncSettings,
    _PluginLibrarySync,
    BasePlugin,
):
    def _bulletin(self, text: str, error: bool = False):
        def _toast():
            with tolerated():
                ctx = find_class("org.telegram.messenger.ApplicationLoader").applicationContext
                jclass("android.widget.Toast").makeText(ctx, str(text), 1 if error else 0).show()
        def _show():
            with tolerated():
                if get_last_fragment() is None:
                    _toast()
                    return
            try:
                if error:
                    BulletinHelper.show_error(text)
                else:
                    BulletinHelper.show_info(text)
            except Exception:
                try:
                    if error:
                        BulletinHelper.error(text)
                    else:
                        BulletinHelper.info(text)
                except Exception:
                    _toast()
        try:
            run_on_ui_thread(_show)
        except Exception:
            _show()

    def _notify_once(self, text: str):
        now = time.time()
        if text == getattr(self, "_last_note", None) and now - getattr(self, "_last_note_t", 0) < 1.5:
            return
        self._last_note = text
        self._last_note_t = now
        self._bulletin(text)

    def _migrate_locked_queue_behavior(self):
        with tolerated():
            if not self.get_setting("locked_queue_behavior_v2_migrated", False):
                old = int(self.get_setting("locked_queue_behavior", 3))
                new = {0: 0, 1: 1, 2: 2, 3: 2, 4: 3, 5: 4}.get(old, 2)
                self.set_setting("locked_queue_behavior", new)
                self.set_setting("locked_queue_behavior_v2_migrated", True)
            if not self.get_setting("locked_queue_behavior_v3_migrated", False):
                current = int(self.get_setting("locked_queue_behavior", 2))
                if current not in (0, 1, 2):
                    self.set_setting("locked_queue_behavior", 2)
                self.set_setting("locked_queue_behavior_v3_migrated", True)

    def on_plugin_load(self):
        _PLUGIN_REF["plugin"] = self
        self._hooks = []
        self._menu_ids = []
        self._active_filter = None
        self._queue_name = None
        self._queue_scope_key = None
        self._queue_cover_key = None
        self._lib_owned = None
        self._lib_cache = None
        self._lib_bypass = False
        self._tstore = _TrackStore(self)
        self._sstore = _SongStore(self)
        self._msg_cache = _MessageIndex(self._tstore, self._sstore)
        self._chat_track_cache = _TrackCache(self, self._tstore)
        self._friend_track_cache = {}
        self._msg_missing = set()
        self._resolver = _MsgResolver(self)
        self._topic_hydration_scope = None
        self._topic_hydration_generation = 0
        self._topic_fetcher = None
        self._topic_progress_sheet = None
        with tolerated():
            _crashlog.install(self)
        self._migrate_locked_queue_behavior()
        with tolerated():
            if not self.get_setting("hq_thumbs_default_migrated", False):
                self.set_setting("hq_thumbs", True)
                self.set_setting("hq_thumbs_default_migrated", True)
        with tolerated():
            self._install_hooks()
        with tolerated():
            self._install_menu_items()
        with tolerated():
            self._install_transfer_open_hook()
        with tolerated():
            self._install_chat_menu_items()
        with tolerated():
            self._install_offline_hook()
        with tolerated():
            self._install_forward_hook()
        with tolerated():
            self._install_playfail_hook()
        with tolerated():
            self._install_player_hooks()
        with tolerated():
            self._mini_rows = _MiniRows(self)
            self._mini_rows.install()
            self._mini_rows.install_theme_listener()
        with tolerated():
            self._chat_card = _Card(self)
            self._chat_card.install()
        with tolerated():
            self._tab_init()
        with tolerated():
            self._pp_initial_sync()
        with tolerated():
            _md3_check.check_and_warn(self)
        with tolerated():
            self._drop_last_queue_data()
            self._rs_start()
        with tolerated():
            self._rs_boot()
        with tolerated():
            self._install_shuffle_hooks()
        with tolerated():
            self._install_repeat_hook()
        with tolerated():
            self._install_crossfade()
        with tolerated():
            self._install_equalizer()
        with tolerated():
            self._install_playback_fx()
        with tolerated():
            self._install_playback_guards()
        with tolerated():
            self._prompt_restart_if_updated()

    @staticmethod
    def _build_id():
        ver = str(_PLUGIN_VERSION)
        try:
            import os
            root = os.path.dirname(os.path.abspath(__file__))
            total = n = 0
            for base, _dirs, files in os.walk(root):
                for f in files:
                    if f.endswith(".py"):
                        total += os.path.getsize(os.path.join(base, f))
                        n += 1
            return f"{ver}:{n}:{total}" if n else ver
        except Exception:
            return ver

    def _prompt_restart_if_updated(self):
        System = jclass("java.lang.System")
        key = "aj.musicplus.build"
        cur = self._build_id()
        prev = System.getProperty(key)
        System.setProperty(key, cur)
        if prev is None or str(prev) == cur:
            return
        self._post(lambda: _tab_sheet.ask_restart(self, str(_PLUGIN_VERSION)), 1500)

    def _sleep_h(self):
        h = getattr(self, "_sleep_handler", None)
        if h is None:
            h = jclass("android.os.Handler")(jclass("android.os.Looper").getMainLooper())
            self._sleep_handler = h
            self._sleep_run = _proxies()[2](self._sleep_tick)
        return h

    def sleep_status(self) -> str:
        mode = getattr(self, "_sleep_mode", None)
        if mode == "min":
            left = max(0, int(self._sleep_end - time.time()))
            return strings("pauses_in_n", _fmt_time(left))
        if mode == "eot":
            return strings("pauses_at_the_end_of_this")
        return ""

    def _sleep_start(self):
        h = self._sleep_h()
        with tolerated():
            h.removeCallbacks(self._sleep_run)
        h.postDelayed(self._sleep_run, 500)

    def sleep_set_minutes(self, minutes):
        self._sleep_mode = "min"
        self._sleep_end = time.time() + int(minutes) * 60
        self._sleep_start()

    def sleep_set_eot(self):
        mc = self._get_mc()
        pm = mc.getPlayingMessageObject() if mc is not None else None
        if pm is None:
            self._bulletin(strings("nothing_is_playing"), error=True)
            return
        self._sleep_mode = "eot"
        self._sleep_key = _QueueEditor._key(pm)
        self._sleep_start()

    def sleep_cancel(self):
        self._sleep_mode = None
        with tolerated():
            self._sleep_h().removeCallbacks(self._sleep_run)

    def _sleep_tick(self):
        mode = getattr(self, "_sleep_mode", None)
        if mode is None:
            return
        with tolerated():
            mc = self._get_mc()
            pm = mc.getPlayingMessageObject() if mc is not None else None
            playing = pm is not None and not bool(mc.isMessagePaused())
            fire = False
            if mode == "min":
                if time.time() >= self._sleep_end:
                    if bool(self.get_setting("sleep_wait_for_last_track", False)) and playing:
                        self._sleep_mode = "eot"
                        self._sleep_key = _QueueEditor._key(pm)
                        self._bulletin(strings("sleep_timer_pausing_after_this_track"))
                    else:
                        fire = True
            elif pm is None or _QueueEditor._key(pm) != self._sleep_key:
                fire = True
            else:
                dur = int(pm.getDuration())
                fire = dur > 0 and dur - int(pm.audioProgressSec) <= 1
            if fire:
                self._sleep_mode = None
                if pm is not None and playing:
                    mc.pauseMessage(pm)
                self._bulletin(strings("sleep_timer_playback_paused"))
                return
        self._sleep_h().postDelayed(self._sleep_run, 500)

    def _expire_caches(self):
        with tolerated():
            now = time.time()
            if now - getattr(self, "_cache_ts", 0.0) > 600.0:
                self._cache_ts = now
                self._msg_missing.clear()
                self._resolver.failed.clear()
                self._resolver.gone.clear()
                self._resolver.gone_loaded = False
                self._resolver._load_gone()

    def _tab_style(self):
        with tolerated():
            v = self.get_setting("tab_style", None)
            if v is not None:
                return max(0, min(3, int(v)))
        with tolerated():
            if bool(self.get_setting("tab_replace", False)):
                return 1
            if bool(self.get_setting("tab_enabled", False)):
                return 2
        return 1

    def _tab_mode_now(self):
        style = self._tab_style()
        return "replace" if style in (1, 3) else ("add" if style == 2 else "")

    def _tab_cfg(self):
        style = self._tab_style()
        ix = None
        if style == 2:
            with tolerated():
                ix = int(str(self.get_setting("tab_index", "") or "").strip())
        return (style, ix)

    def _show_tab_sheet(self, *_a):
        _tab_sheet.show(self)

    def _tab_rows(self):
        rows = []
        opener = None
        if Text is not None:
            with tolerated():
                opener = Text(text=strings("tab_row", _tab_sheet.summary(self)), icon="msg_list", accent=True,
                              on_click=self._show_tab_sheet)
        if opener is None:
            opener = Switch(key="tab_sheet_open", text=strings("tab_row", _tab_sheet.summary(self)), default=False,
                            on_change=lambda v: self._show_tab_sheet() if v else None)
        rows.append(opener)
        return rows

    def _tab_init(self):
        self._tab_active = False
        with tolerated():
            if self.get_setting("tab_style", None) is None:
                self.set_setting("tab_style", self._tab_style())
        self._tab_loaded = self._tab_mode_now()
        self._tab_loaded_cfg = self._tab_cfg()
        if not self._tab_loaded:
            return
        ix = None
        if self._tab_loaded == "add":
            try:
                ix = int(str(self.get_setting("tab_index", "") or "").strip())
            except Exception:
                ix = None
            if ix == 1:
                ix = 2
        if getattr(self, "_tabinj", None) is None:
            self._tabinj = _TabInjector(self, self._tab_loaded, "settings" if self._tab_style() == 3 else "contacts")
        self._tabinj.add_entry(dict(
       id=_AJ_TAB_ID, title=strings(_TAB_LABEL), title_key=_TAB_LABEL, icon="MUSIC", index=ix,
       on_create=self._tab_on_create, on_destroy=self._tab_on_destroy,
       on_back=self._tab_on_back, on_resume=self._tab_on_resume))
        self._tab_active = True
        self._tab_prewarm_schedule(4000)

    def _tab_index_subtext(self):
        return strings("position_in_the_bottom_bar_empty")

    def _tab_open(self) -> bool:
        if not getattr(self, "_tab_active", False):
            return False
        return self._tabinj.open_entry(_AJ_TAB_ID)

    def _tab_on_create(self, host, frag, ctx):
        old = getattr(self, "_editor", None)
        if old is not None:
            old._cancelled = True
            with tolerated():
                if old.tabmode:
                    old.dialog.kill()
                else:
                    old.dialog.dismiss()
            self._editor = None
        ed = self._tab_take_prewarmed(ctx)
        warm = ed is not None
        if not warm:
            ed = _QueueEditor(self, ctx)
            ed.tabmode = True
        ed.host_frame = host
        try:
            ed.tab_frag_hash = reflect.identity_hash(frag) if frag is not None else None
        except Exception:
            ed.tab_frag_hash = None
        with tolerated():
            host.setBackgroundColor(ed.c_bg)
        if not warm:
            with tolerated():
                ed.stage_placeholder(host)
        self._editor = ed
        def _go():
            if getattr(self, "_editor", None) is not ed or getattr(ed, "_cancelled", False):
                return
            def _guard():
                return getattr(self, "_editor", None) is ed and not getattr(ed, "_cancelled", False)
            try:
                if not warm:
                    ed._build_shell()
                    def _prep():
                        if _guard():
                            try:
                                ed._prepare_rest()
                                ed.handler.post(ed.Run(lambda: _guard() and ed.attach_prewarmed(host)))
                            except Exception as e:
                                with tolerated():
                                    ed._queue_loading_hide()
                                with tolerated():
                                    self._bulletin(strings("couldnt_open_the_queue_n", e), error=True)
                    ed.handler.post(ed.Run(_prep))
                    return
                ed.attach_prewarmed(host)
            except Exception as e:
                with tolerated():
                    ed._queue_loading_hide()
                with tolerated():
                    self._bulletin(strings("couldnt_open_the_queue_n", e), error=True)
        ed.handler.postDelayed(ed.Run(_go), 16 if warm else 120)


    def _tab_prewarm_schedule(self, delay=4000):
        if getattr(self, "_tab_active", False):
            run_on_ui_thread(self._tab_prewarm, delay)

    def _tab_prewarm(self, _waited=0):
        if getattr(self, "_rs_loading", False) and _waited < 12:
            run_on_ui_thread(lambda: self._tab_prewarm(_waited + 1), 500)
            return
        with tolerated():
            if (not getattr(self, "_tab_active", False) or getattr(self, "_pre_editor", None) is not None
                    or getattr(self, "_editor", None) is not None):
                return
            LA = find_class("org.telegram.ui.LaunchActivity")
            act = LA.instance if LA is not None else None
            if act is None:
                return
            ed = _QueueEditor(self, act)
            ed.tabmode = True
            ed._pre_act = reflect.identity_hash(act)
            self._pre_editor = ed
            def _finish():
                ed._prep_finish()
                ed._pre_sig = ed.theme_sig()
                ed._pre_done = True
            def _live():
                return (getattr(self, "_pre_editor", None) is ed and not getattr(ed, "_cancelled", False)
                        and not ed.__dict__.get("_attached"))
            def _library():
                if _live():
                    ed._lib_pre = True
                    ed._lib_render()
            def _fill():
                ed.prefill(lambda: ed.handler.postDelayed(ed.Run(_library), 60))
            steps = (lambda: ed._build_shell(staged=True),
                     lambda: ed._build_shell_pages(("library",)),
                     lambda: ed._build_shell_pages(("lyrics",)),
                     ed._build_shell_end,
                     ed._prep_glass,
                     ed._prep_mini,
                     _finish,
                     _fill)
            def _run(i=0):
                if getattr(self, "_pre_editor", None) is not ed or getattr(ed, "_cancelled", False):
                    return
                try:
                    steps[i]()
                except Exception:
                    if getattr(self, "_pre_editor", None) is ed and not getattr(ed, "_pre_done", False):
                        self._pre_editor = None
                    return
                if i + 1 < len(steps):
                    ed.handler.postDelayed(ed.Run(lambda: _run(i + 1)), 40)
            _run(0)

    def _tab_take_prewarmed(self, ctx):
        ed, self._pre_editor = getattr(self, "_pre_editor", None), None
        if ed is None:
            return None
        ok = False
        with tolerated():
            ok = (getattr(ed, "_pre_done", False) and ed._pre_act == reflect.identity_hash(ctx)
                  and ed._pre_sig == ed.theme_sig() and getattr(ed, "root", None) is not None)
        if not ok:
            ed._cancelled = True
        return ed if ok else None

    def _tab_on_destroy(self, frag):
        ed = getattr(self, "_editor", None)
        if ed is not None and frag is not None:
            with tolerated():
                mine = getattr(ed, "tab_frag_hash", None)
                if mine is not None and mine != reflect.identity_hash(frag):
                    return
        if ed is not None and getattr(ed, "tabmode", False):
            ed._cancelled = True
            with tolerated():
                ed.dialog.kill()
            if getattr(self, "_editor", None) is ed:
                self._editor = None
            self._tab_prewarm_schedule(1500)

    def _tab_on_back(self, frag):
        ed = getattr(self, "_editor", None)
        if ed is None or not getattr(ed, "tabmode", False) or getattr(ed, "root", None) is None or not ed._lib_can_back():
            return False
        return bool(ed._lib_back())

    def _tab_on_resume(self):
        self._expire_caches()
        ed = getattr(self, "_editor", None)
        if ed is not None and getattr(ed, "tabmode", False):
            ed._queue_library_refresh()

    def _tab_teardown(self):
        inj = getattr(self, "_tabinj", None)
        if inj is not None:
            inj.stop()
        self._tab_active = False
        self._pre_editor = None
        self._tab_on_destroy(None)


    def on_plugin_unload(self):
        with tolerated():
            _crashlog.uninstall()
        self._kept_editor = None
        with tolerated():
            if getattr(self, "_chat_card", None) is not None:
                self._chat_card.stop()
                self._chat_card = None
        with tolerated():
            if getattr(self, "_mini_rows", None) is not None:
                self._mini_rows.stop()
                self._mini_rows = None
        self._rs_stop()
        with tolerated():
            if getattr(self, "_xf", None) is not None:
                self._xf.stop()
                self._xf = None
        with tolerated():
            self._eq_teardown()
        with tolerated():
            self._net_events_teardown()
        with tolerated():
            self._pundo_hide()
        for unhook in list(self._hooks):
            with tolerated():
                self.unhook_method(unhook)
        self._hooks.clear()
        with tolerated():
            self._tab_teardown()
        with tolerated():
            self._cancel_topic_hydration()
        with tolerated():
            self._sleep_mode = None
            self._sleep_h().removeCallbacks(self._sleep_run)
        for unhook in self._hooks:
            with tolerated():
                self.unhook_method(unhook)
        self._hooks.clear()
        for mid in list(self._menu_ids):
            with tolerated():
                self.remove_menu_item(mid)
        self._menu_ids.clear()
        self._active_filter = None


    def _open_link(self, url):
        def _go():
            with tolerated():
                act = get_last_fragment().getParentActivity()
                find_class("org.telegram.messenger.browser.Browser").openUrl(act, url)
        run_on_ui_thread(_go)

    def _link_rows(self):
        rows = []
        for text, icon, url in ((strings("channel_t_me_aj_plugins"), "msg_channel", "https://t.me/AJ_Plugins"),):
            cb = lambda *_a, u=url: self._open_link(u)
            if Text is not None:
                with tolerated():
                    rows.append(Text(text=text, icon=icon, accent=True, on_click=cb))
                    continue
            rows.append(Switch(key="link_" + icon, text=text, default=False,
          on_change=lambda v, u=url: self._open_link(u) if v else None))
        return rows

    _LIB_SECTION_DEFAULT_ORDER = ("playlists", "chats", "friends", "artists")
    _LIB_SECTION_LABELS = {
    "playlists": ("playlists", "saved_playlists"),
    "chats": ("chats", "music_saved_from_chats_and_topics"),
    "friends": ("friends", "profile_music_shortcuts"),
    "artists": ("artists", "generated_from_your_cached_music"),
    }

    def _library_section_order(self):
        allowed = list(self._LIB_SECTION_DEFAULT_ORDER)
        raw = self.get_setting("lib_section_order", "")
        try:
            requested = [str(item).strip().lower() for item in str(raw or "").split(",")]
        except Exception:
            requested = []
        order = []
        for item in requested:
            if item in allowed and item not in order:
                order.append(item)
        order.extend(item for item in allowed if item not in order)
        return order

    def _library_section_order_row(self):
        if Text is not None:
            with tolerated():
                return Text(text=strings("reorder_library_sections"), icon="msg_list", accent=True,
             on_click=self._show_library_section_order_dialog)
        return Switch(key="lib_section_order_open", text=strings("reorder_library_sections"), default=False,
       subtext=strings("tap_to_open_the_section_order"),
       on_change=lambda value: self._show_library_section_order_dialog()
       if value else None)

    def _show_library_section_order_dialog(self, *_args):
        def show_dialog():
            try:
                fragment = get_last_fragment()
                act = fragment.getParentActivity() if fragment is not None else None
                if act is None:
                    self._bulletin(strings("cant_open_library_section_order_here"), error=True)
                    return
                sh = _NativeSheet(act, strings("library_sections"), strings("choose_the_order_they_appear_in"))
                order = list(self._library_section_order())
                names = {k: (strings(v[0]), strings(v[1])) for k, v in self._LIB_SECTION_LABELS.items()}
                def move(i, delta):
                    j = i + delta
                    if 0 <= j < len(order):
                        order[i], order[j] = order[j], order[i]
                        render()
                def arrow(glyph, cb, enabled):
                    rd = _rd_index()
                    rid = 0
                    for nm in ("msg_go_down", "arrow_down_float", "msg_arrow_down", "ic_arrow_drop_down", "ic_expand_more"):
                        if rd.get(nm):
                            rid = int(rd[nm])
                            break
                    if rid:
                        tv = _cls("android.widget.ImageView")(act)
                        tv.setImageResource(rid)
                        tv.setColorFilter(sh.c_accent)
                        if glyph == "up":
                            tv.setRotation(180.0)
                    else:
                        tv = _cls("android.widget.TextView")(act)
                        tv.setText("\u25B2" if glyph == "up" else "\u25BC")
                        tv.setTextColor(sh.c_accent)
                        tv.setTextSize(14.0)
                        tv.setGravity(17)
                    tv.setPadding(sh.dp(8), sh.dp(8), sh.dp(8), sh.dp(8))
                    tv.setEnabled(bool(enabled))
                    if enabled:
                        tv.setOnClickListener(sh.Click(lambda v: cb()))
                        sh.ripple(tv, circle=True)
                    else:
                        tv.setAlpha(0.28)
                    return tv
                def render():
                    sh.body.removeAllViews()
                    card = sh.card()
                    for i, key in enumerate(order):
                        title, detail = names[key]
                        if i:
                            sh.divider(card, 68)
                        row = sh.LL(act)
                        row.setOrientation(0)
                        row.setGravity(16)
                        row.setPadding(sh.dp(16), sh.dp(10), sh.dp(8), sh.dp(10))
                        rank = sh.circle(str(i + 1))
                        row.addView(rank, sh.LP(sh.dp(36), sh.dp(36)))
                        col = sh.LL(act)
                        col.setOrientation(1)
                        col.setPadding(sh.dp(16), 0, sh.dp(8), 0)
                        col.addView(sh.text(title, 16, sh.c_text), sh.LP(-1, -2))
                        col.addView(sh.text(detail, 13, sh.c_sub), sh.LP(-1, -2))
                        row.addView(col, sh.LP(0, -2, 1.0))
                        row.addView(arrow("up", lambda i=i: move(i, -1), i > 0), sh.LP(sh.dp(38), sh.dp(38)))
                        row.addView(arrow("down", lambda i=i: move(i, 1), i < len(order) - 1),
                   sh.LP(sh.dp(38), sh.dp(38)))
                        card.addView(row, sh.LP(-1, -2))
                    sh.fit()
                def reset():
                    order[:] = list(self._LIB_SECTION_DEFAULT_ORDER)
                    render()
                def save():
                    self.set_setting("lib_section_order", ",".join(order))
                    with tolerated():
                        editor = getattr(self, "_editor", None)
                        if editor is not None and editor.lib_state == ("home", None):
                            editor._lib_render()
                    sh.dlg.dismiss()
                render()
                sh.primary_button(strings("save"), save)
                sh.secondary_row((strings("reset_to_default"), reset), (strings("cancel"), sh.dlg.dismiss))
                sh.show()
            except Exception:
                self._bulletin(strings("couldnt_open_library_section_order"), error=True)
        try:
            run_on_ui_thread(show_dialog)
        except Exception:
            show_dialog()

    def _excluded_artists_row(self):
        excluded = self._lib_excluded_artists_for_settings()
        label = strings("excluded_artists_n", len(excluded))
        if Text is not None:
            with tolerated():
                return Text(text=label, icon="msg_list", accent=True,
             on_click=self._show_excluded_artists_dialog)
        return Switch(
       key="excluded_artists_open",
       text=label,
       default=False,
       subtext=strings("manage_artists_hidden_from_the_library"),
       on_change=lambda value: self._show_excluded_artists_dialog() if value else None,
       )

    def _lib_excluded_artists_for_settings(self):
        try:
            raw = self.get_setting("excluded_artists", "[]")
            values = json.loads(raw) if isinstance(raw, str) else raw
            return sorted(set(str(x).casefold() for x in (values or [])))
        except Exception:
            return []

    def _show_excluded_artists_dialog(self, *_args):
        def show_dialog():
            try:
                fragment = get_last_fragment()
                act = fragment.getParentActivity() if fragment is not None else None
                if act is None:
                    self._bulletin(strings("cant_open_excluded_artists_here"), error=True)
                    return
                sh = _NativeSheet(act, strings("excluded_artists"),
             strings("hidden_from_the_library_restore_an"))
                def current_items():
                    excluded = self._lib_excluded_artists_for_settings()
                    artist_names = {}
                    with tolerated():
                        data = self._lib_data().get("artists", {})
                        for artist in data.get("list", []):
                            artist_names[str(artist.get("k", "")).casefold()] = str(
                      artist.get("n") or artist.get("k") or strings("unknown_artist"))
                    return [(k, artist_names.get(k, k), k in artist_names) for k in excluded]
                def restore(k, artist_name):
                    excluded = set(self._lib_excluded_artists_for_settings())
                    excluded.discard(k)
                    self.set_setting("excluded_artists", json.dumps(sorted(excluded)))
                    with tolerated():
                        editor = getattr(self, "_editor", None)
                        if editor is not None:
                            if editor.lib_state and editor.lib_state[0] == "artist":
                                editor._lib_go("home")
                            else:
                                editor._lib_render()
                    render()
                    self._bulletin(strings("restored_n_to_library", artist_name))
                def render():
                    sh.body.removeAllViews()
                    items = current_items()
                    if not items:
                        box = sh.LL(act)
                        box.setOrientation(1)
                        box.setGravity(17)
                        box.setPadding(sh.dp(24), sh.dp(36), sh.dp(24), sh.dp(36))
                        box.addView(sh.text(strings("no_excluded_artists"), 16, sh.c_text, True, 17), sh.LP(-1, -2))
                        hint = sh.text(strings("artists_you_remove_from_the_library"), 13, sh.c_sub, False, 17)
                        hint.setPadding(0, sh.dp(4), 0, 0)
                        box.addView(hint, sh.LP(-1, -2))
                        sh.body.addView(box, sh.LP(-1, -2))
                        sh.fit()
                        return
                    sh.section(strings("hidden_artists_n", len(items)))
                    card = sh.card()
                    for i, (k, name, found) in enumerate(items):
                        if i:
                            sh.divider(card, 68)
                        row = sh.LL(act)
                        row.setOrientation(0)
                        row.setGravity(16)
                        row.setPadding(sh.dp(16), sh.dp(10), sh.dp(8), sh.dp(10))
                        letter = (name.strip()[:1] or "?").upper()
                        row.addView(sh.circle(letter), sh.LP(sh.dp(40), sh.dp(40)))
                        col = sh.LL(act)
                        col.setOrientation(1)
                        col.setPadding(sh.dp(14), 0, sh.dp(8), 0)
                        col.addView(sh.text(name, 16, sh.c_text, single=True), sh.LP(-1, -2))
                        if not found:
                            col.addView(sh.text(strings("not_in_the_latest_scan"), 13, sh.c_sub, single=True),
                      sh.LP(-1, -2))
                        row.addView(col, sh.LP(0, -2, 1.0))
                        row.addView(sh.text_button(strings("restore"), lambda k=k, n=name: restore(k, n)),
                   sh.LP(-2, -2))
                        card.addView(row, sh.LP(-1, -2))
                    sh.fit()
                render()
                sh.primary_button(strings("done"), sh.dlg.dismiss)
                sh.show()
            except Exception:
                self._bulletin(strings("couldnt_open_excluded_artists"), error=True)
        try:
            run_on_ui_thread(show_dialog)
        except Exception:
            show_dialog()


    def create_settings(self) -> List[Any]:
        settings = [
       Header(text=strings("appearance")),
       Switch(
       key="move_tabs_to_top",
       text=strings("move_tabs_to_top"),
       default=False,
       on_change=lambda v: setattr(self, "_kept_editor", None),
       ),
       Switch(
       key="glass_follow_tg",
       text=strings("follow_telegram_blur_glass"),
       default=True,
       ),
       Switch(
       key="sheet_expand_first",
       text=strings("expand_the_sheet_on_first_scroll"),
       default=False,
       subtext=strings("expand_the_player_sheet_before_scrolling"),
       ),
       _selector_sub(
       key="sheet_min_height",
       text=strings("minimum_sheet_height"),
       default=4,
       subtext=strings("applies_in_portrait_mode_only"),
       items=[
       strings("n_of_screen", 30),
       strings("n_of_screen", 40),
       strings("n_of_screen", 50),
       strings("n_of_screen", 60),
       strings("n_of_screen", 70),
       strings("n_of_screen", 80),
       ],
       ),
       Switch(
       key="replace_row",
       text=strings("custom_player_bar"),
       default=True,
       subtext=strings("replaces_the_music_bar_above_chats"),
       ),
       _selector_sub(
       key="bar_height",
       text=strings("player_bar_height"),
       default=2,
       subtext=strings("applies_to_the_custom_player_bar"),
       items=[strings("n_dp", n) for n in (36, 42, 48, 56)],
       ),
       Switch(
       key="dynamic_tint",
       text=strings("artwork_tint"),
       default=True,
       subtext=strings("tints_the_player_with_the_tracks_artwork_color"),
       ),
       _selector_sub(
       key="queue_tint_anim",
       text=strings("queue_color_animation"),
       default=0,
       subtext=strings("queue_color_animation_hint"),
       items=[strings("queue_anim_auto"), strings("queue_anim_always"), strings("queue_anim_never")],
       ),
       Switch(
       key="chat_music_card",
       text=strings("music_card_in_chats"),
       default=True,
       subtext=strings("music_card_in_chats_sub"),
       ),
       ]
        settings.extend([
       Divider(),
       Header(text=strings("navigation")),
       *self._tab_rows(),
       Switch(
       key="drawer_enabled",
       text=strings("show_music_in_navigation_drawer"),
       default=True,
       subtext=strings("adds_music_to_the_side_menu"),
       on_change=self._drawer_setting_changed,
       ),
       Divider(),
       Header(text=strings("library")),
       Switch(
       key="persist_track_cache",
       text=strings("offline_library_cache"),
       default=True,
       subtext=strings("saves_each_library_chats_tracks_on"),
       ),
       Selector(
       key="artist_min_tracks",
       text=strings("minimum_tracks_per_artist"),
       default=1,
       items=[strings("1_track"), strings("n_tracks", 2), strings("n_tracks", 3), strings("n_tracks", 4), strings("n_tracks", 5), strings("n_tracks", 10)],
       ),
       Selector(
       key="lib_grid_columns",
       text=strings("library_grid_columns"),
       default=2,
       items=[strings("n_columns", 2), strings("n_columns", 3), strings("n_columns", 4), strings("n_columns", 5)],
       ),
       self._library_section_order_row(),
       self._excluded_artists_row(),
       self._cache_clear_row(),
       Divider(),
       Header(text=strings("export_data")),
       *self._backup_rows(),
       Divider(),
       Header(text=strings("playback_queue")),
       Selector(
       key="max_queue_songs",
       text=strings("max_queue_songs"),
       default=2,
       items=[strings("n_songs", 250), strings("n_songs", 500), strings("n_songs", 1000), strings("n_songs", 2000), strings("n_songs", 5000), strings("n_songs", 10000), strings("unlimited")],
       ),
       Switch(
       key="resume_queue",
       text=strings("resume_the_queue"),
       default=True,
       subtext=strings("offers_the_last_started_queue_up_to"),
       ),
       Switch(
       key="resume_show_bar",
       text=strings("show_player_bar_on_start"),
       default=True,
       subtext=strings("show_player_bar_on_start_sub"),
       ),
       Switch(
       key="show_crash_reports",
       text=strings("show_crash_reports"),
       default=False,
       subtext=strings("show_crash_reports_sub"),
       ),
       Switch(
       key="keep_sheet_alive",
       text=strings("keep_the_player_sheet_ready"),
       default=True,
       subtext=strings("opens_faster_uses_a_little_more"),
       ),
       Switch(
       key="respect_topic",
       text=strings("respect_forum_topic"),
       default=True,
       ),
       Switch(
       key="respect_hashtag",
       text=strings("respect_hashtag_chat_search"),
       default=True,
       ),
       Switch(
       key="sleep_wait_for_last_track",
       text=strings("better_sleep_timer"),
       default=True,
       subtext=strings("pause_after_the_playing_track_finishes"),
       ),
       Divider(),
       Header(text=strings("lock_queue_behavior")),
       Selector(
       key="locked_queue_behavior",
       text=strings("when_tapping_music_outside_the_queue"),
       default=2,
       items=[
       strings("play_next"),
       strings("add_to_end"),
       strings("ask_every_time"),
       ],
       ),
       Divider(),
       Header(text=strings("network")),
       Selector(
       key="stall_timeout_v5",
       text=strings("stall_timeout"),
       default=3,
       items=[strings("state_off")] + [strings("n_seconds", n) for n in (5, 8, 12, 15)],
       ),
       Switch(
       key="cancel_skipped_download",
       text=strings("cancel_skipped_download"),
       default=True,
       subtext=strings("cancel_skipped_download_sub"),
       ),
       Switch(
       key="preload_next_track",
       text=strings("preload_next_track"),
       default=True,
       subtext=strings("preload_next_track_sub"),
       ),
       Switch(
       key="hq_thumbs",
       text=strings("high_quality_album_covers"),
       default=True,
       subtext=strings("loads_better_queue_covers_too_uses"),
       ),
       Switch(
       key="lib_auto_refresh",
       text=strings("auto_refresh_chats_on_open"),
       default=False,
       subtext=strings("reloads_a_chats_or_friends_tracks"),
       ),
       Divider(),
       Header(text=strings("updates")),
       Switch(
       key="update_check",
       text=strings("notify_latest_updates"),
       default=True,
       subtext=strings("checks_for_a_new_version_when"),
       on_change=lambda v: self._update_schedule(True) if v else None,
       ),
       Divider(),
       Header(text=strings("links")),
       *self._link_rows(),
       ])
        return settings

    def _dialog_title(self, dialog_id, acc=0) -> str:
        with tolerated():
            did = int(dialog_id)
            Long = jclass("java.lang.Long")
            MCtl = find_class("org.telegram.messenger.MessagesController").getInstance(int(acc))
            if did < 0:
                chat = MCtl.getChat(Long.valueOf(-did))
                return str(chat.title).strip() if chat is not None else ""
            if int(find_class("org.telegram.messenger.UserConfig").getInstance(int(acc)).getClientUserId()) == did:
                return strings("saved_messages")
            user = MCtl.getUser(Long.valueOf(did))
            if user is not None:
                return str(find_class("org.telegram.messenger.UserObject").getUserName(user)).strip()
        return ""
