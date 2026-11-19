from ..compat import (
 dynamic_proxy,
 find_class,
 get_last_fragment,
 jarray,
 jclass,
 jfloat,
 run_on_ui_thread,
)
import threading
from elyx import strings
from ..helpers import _argb
from ..android import (
 _cls,
 _dismiss_proxy,
 _key_proxy,
 _layoutchg_proxy,
 _mix,
 _proxies,
 _scrollchg_proxy,
 _wide_px,
)
from ..glass import _PillRow, _attach_sheet_drag, _glass_note, _sheet_glass
from ..tabs import _TAB_BAR_DP, _TAB_GAP_DP, _TabDialog
from ..safe import tolerated
from .. import tint


class _QueueEditorCore:
    ROW_DP = 56
    COVER_DP = 44
    QUEUE_BATCH_ROWS = 60
    QUEUE_PREPEND_ROWS = 30
    QUEUE_CHUNK_ROWS = 12
    QUEUE_EDGE_ROWS = 10
    ROW_PAD_START = 16
    VIEW_DEFAULTS = {"playlists": "list", "artists": "grid", "chats": "list", "friends": "list"}
    ARTIST_MINS = (1, 2, 3, 4, 5, 10)
    ARTIST_PAGE = 5
    BAR_BTN_DP = 48
    BAR_END_DP = 12
    tabmode = False
    host_frame = None
    ghost = False

    def __init__(self, plugin, activity):
        self.p = plugin
        self.act = activity
        dm = activity.getResources().getDisplayMetrics()
        self.density = float(dm.density)
        self.screen_h = int(dm.heightPixels)
        self.H = self.dp(self.ROW_DP)
        self.items = []
        self.rows = []
        self.reversed = False
        self.keys = []
        self.key_index = {}
        self.win_start = 0
        self.win_end = 0
        self.queue_lazy_ready = False
        self.queue_load_pending = False
        self.queue_data_token = 0
        self.row_meta_cache = {}
        self.row_refs = {}
        self.dl_cache = {}
        self.pl_size = -1
        self._styled_playing = None
        self._tf = None
        self._cover_key = None
        self._cover_ok = False
        self._cover_retry = 0
        self._cover_repeat_tries = 0
        self.undo_snap = None
        self.playing_key = None
        self.drag = None
        self.ticking = False
        self.sel = set()
        self.sel_mode = False
        self.sized = False
        self._closing = False
        self._anim_id = 0
        self.sheet_lock = False
        self.cur_h = 0
        self.h_min = 0
        self.h_max = 0
        self.sh = None
        self._out = False
        self.tab = "queue"
        self.tab_btns = {}
        self.tab_pages = {}
        self.Touch, self.Click, self.Run = _proxies()
        Handler = jclass("android.os.Handler")
        Looper = jclass("android.os.Looper")
        self.handler = Handler(Looper.getMainLooper())
        self.tick_run = self.Run(self._auto_tick)
        self.LP = jclass("android.widget.LinearLayout$LayoutParams")
        self.c_bg = self._theme("key_windowBackgroundGray", self._theme("key_dialogBackground", -1))
        self.c_item = self._theme("key_windowBackgroundWhite", self.c_bg)
        self.c_text = self._theme("key_windowBackgroundWhiteBlackText", _argb(255, 33, 33, 33))
        self.c_sub = self._theme("key_windowBackgroundWhiteGrayText2", _argb(255, 138, 138, 138))
        self.c_accent = self._theme("key_player_buttonActive",
       self._theme("key_windowBackgroundWhiteBlueText", _argb(255, 42, 139, 234)))
        self.c_line = self._theme("key_divider", _argb(40, 128, 128, 128))
        self.c_sel = _mix(self.c_item, self.c_accent, 0.18)
        self.c_player_bg = self._theme("key_player_background", self.c_item)
        self.c_player_text = self._theme("key_player_actionBarTitle", self.c_text)
        self.c_player_sub = self._theme("key_player_actionBarSubtitle", self.c_sub)
        self.c_player_button = self._theme("key_player_button", self.c_sub)
        self.c_player_progress = self._theme("key_player_progress", self.c_accent)
        self.base_accent, self.base_progress = self.c_accent, self.c_player_progress
        t = tint.current()
        if t is not None:
            self.c_accent = self.c_player_progress = t
            self.c_sel = _mix(self.c_item, t, 0.18)
        self.c_player_progress_bg = self._theme("key_player_progressBackground",
       _mix(self.c_player_bg, self.c_player_sub, 0.34))
        self.R_BIG = 18
        self.R_SMALL = 5
        self.c_red = self._theme("key_text_RedBold", _argb(255, 229, 57, 53))

    def dp(self, v) -> int:
        return int(round(v * self.density))

    def _hold(self, fn):
        def wrapped(v, e):
            if int(e.getActionMasked()) == 0:
                self.sheet_lock = True
            return fn(v, e)
        return self.Touch(wrapped)

    _DRAG_HOLD_MS = 200

    def _hold_drag(self, fn):
        st = {"x": 0.0, "y": 0.0, "armed": False, "run": None, "view": None}
        slop = float(self.dp(8))
        def cancel():
            r = st["run"]
            st["run"] = None
            if r is not None:
                with tolerated():
                    self.handler.removeCallbacks(r)
        def arm():
            st["run"] = None
            v = st["view"]
            if v is None:
                return
            st["armed"] = True
            self.sheet_lock = True
            with tolerated():
                v.getParent().requestDisallowInterceptTouchEvent(True)
                v.performHapticFeedback(0)
            ME = jclass("android.view.MotionEvent")
            now = int(jclass("android.os.SystemClock").uptimeMillis())
            ev = ME.obtain(now, now, 0, float(st["x"]), float(st["y"]), 0)
            try:
                fn(v, ev)
            finally:
                with tolerated():
                    ev.recycle()
        def wrapped(v, e):
            a = int(e.getActionMasked())
            if st["armed"]:
                if a in (1, 3):
                    st["armed"] = False
                return fn(v, e)
            if a == 0:
                cancel()
                st["x"], st["y"] = float(e.getRawX()), float(e.getRawY())
                st["x0"], st["y0"] = st["x"], st["y"]
                st["view"] = v
                st["run"] = self.Run(arm)
                self.handler.postDelayed(st["run"], self._DRAG_HOLD_MS)
                return True
            if a == 2:
                st["x"], st["y"] = float(e.getRawX()), float(e.getRawY())
                if st["run"] is not None and (abs(st["x"] - st["x0"]) > slop or abs(st["y"] - st["y0"]) > slop):
                    cancel()
                return True
            if a in (1, 3):
                cancel()
                return True
            return False
        return self.Touch(wrapped)

    def _group_bg(self, color, first, last, inset=None):
        GD = _cls("android.graphics.drawable.GradientDrawable")
        big, small = float(self.dp(self.R_BIG)), float(self.dp(self.R_SMALL))
        t = big if first else small
        b = big if last else small
        g = GD()
        g.setColor(color)
        g.setCornerRadii(jarray(jfloat)([t, t, t, t, b, b, b, b]))
        if inset:
            Inset = _cls("android.graphics.drawable.InsetDrawable")
            l, tp, r, bt = [self.dp(v) for v in inset]
            return Inset(g, l, tp, r, bt)
        return g

    @staticmethod
    def _theme(name, fallback):
        try:
            Theme = find_class("org.telegram.ui.ActionBar.Theme")
            return int(Theme.getColor(int(getattr(Theme, name))))
        except Exception:
            return fallback

    @staticmethod
    def _key(m):
        try:
            return (int(m.getId()), int(m.getDialogId()))
        except Exception:
            return None

    def _text(self, text, size, color, bold=False, gravity=None, single=False):
        TextView = _cls("android.widget.TextView")
        tv = TextView(self.act)
        tv.setText(str(text))
        tv.setTextSize(float(size))
        tv.setTextColor(color)
        if bold:
            tv.setTypeface(jclass("android.graphics.Typeface").DEFAULT_BOLD)
        g = 51 if gravity is None else int(gravity)
        if not (g & 0x00800007):
            g |= 3
        elif (g & 0x00800007) == 0x00800003:
            g = (g & ~0x00800007) | 3
        tv.setGravity(g)
        if single:
            tv.setSingleLine(True)
            tv.setEllipsize(jclass("android.text.TextUtils$TruncateAt").END)
        return tv

    @staticmethod
    def _title_of(m) -> str:
        for getter in ("getMusicTitle", "getFileName"):
            with tolerated():
                t = getattr(m, getter)()
                if t and str(t).strip():
                    return str(t)
        return "Audio"

    @staticmethod
    def _author_of(m) -> str:
        with tolerated():
            a = m.getMusicAuthor()
            if a and str(a).strip():
                return str(a)
        return ""

    def _load(self) -> bool:
        mc = self.p._get_mc()
        pl = self.p._get_playlist(mc) if mc is not None else None
        closed = getattr(self.p, "_closed", None)
        empty = pl is None or pl.size() == 0
        if not empty:
            self.p._closed = closed = None
        if empty and closed is None:
            self.row_meta_cache, self.dl_cache = {}, {}
            self.ghost = False
            self.items, self.keys, self.key_index = [], [], {}
            self.playing_key, self.pl_size, self.reversed = None, 0, False
            if not getattr(self, "_resume_tried", False) and self.p._resume_available():
                self._resume_tried = True
                self._resuming = True
                def done():
                    self._resuming = False
                    self._reload()
                    with tolerated():
                        self._mini_update()
                if self.p._resume_restore(play=False, done=done):
                    return True
                self._resuming = False
            return False
        self._resume_tried = False
        self.ghost = False
        shuffle_on, rev = self.p._read_order()
        self.reversed = bool(rev and not shuffle_on)
        raw = list(closed["msgs"]) if empty else [pl.get(i) for i in range(pl.size())]
        self.items = raw if self.reversed else raw[::-1]
        self.row_meta_cache = {}
        playing = None
        with tolerated():
            playing = closed["first"] if empty else mc.getPlayingMessageObject()
        self.playing_key = self._key(playing) if playing is not None else None
        self.keys = [self._key(m) for m in self.items]
        self._rebuild_key_index()
        self.dl_cache = {}
        self.pl_size = len(raw) if empty else int(pl.size())
        return True

    def _rebuild_key_index(self):
        index = {}
        for i, key in enumerate(self.keys):
            if key is not None and key not in index:
                index[key] = i
        self.key_index = index

    def _playing_pos(self) -> int:
        if self.playing_key is None:
            return -1
        return int(self.key_index.get(self.playing_key, -1))

    def _commit(self, new_items) -> bool:
        mc = self.p._get_mc()
        pl = self.p._get_playlist(mc) if mc is not None else None
        if pl is None or pl.size() != len(new_items):
            self.p._bulletin(strings("queue_changed_meanwhile_reopen_the_editor"), error=True)
            return False
        shuffle_on, _ = self.p._read_order()
        if shuffle_on:
            self.p._bulletin(strings("shuffle_is_on_order_applies_once"))
        order = new_items if self.reversed else new_items[::-1]
        for i, m in enumerate(order):
            pl.set(i, m)
        if not shuffle_on:
            self.p._resync_current(mc, pl)
        return True

    def show(self):
        self._load()
        self._build_shell()
        self._show_rest()

    def _build_shell(self, staged=False):
        act = self.act
        LinearLayout = jclass("android.widget.LinearLayout")
        ScrollView = jclass("android.widget.ScrollView")
        Dialog = jclass("android.app.Dialog")
        GradientDrawable = jclass("android.graphics.drawable.GradientDrawable")
        LP = self.LP
        tab = bool(self.tabmode)
        if tab:
            dlg = None
            self.dialog = _TabDialog(self)
        else:
            dlg = Dialog(act)
            dlg.requestWindowFeature(1)
            self.dialog = dlg
        root = LinearLayout(act)
        root.setOrientation(1)
        bg = GradientDrawable()
        bg.setColor(self.c_bg)
        r = float(self.dp(16))
        if not tab:
            bg.setCornerRadii(jarray(jfloat)([r, r, r, r, 0.0, 0.0, 0.0, 0.0]))
        root.setBackground(bg)
        View = jclass("android.view.View")
        grab = LinearLayout(act)
        grab.setGravity(17)
        self.grab_view = grab
        grab.setOnTouchListener(self.Touch(self._grab_touch))
        pill = View(act)
        pg = GradientDrawable()
        pg.setColor(_mix(self.c_bg, self.c_sub, 0.5))
        pg.setCornerRadius(float(self.dp(2)))
        pill.setBackground(pg)
        grab.addView(pill, LP(self.dp(36), self.dp(4)))
        if not tab:
            root.addView(grab, LP(-1, self.dp(22)))
        header_h = self.dp(56 if tab else 48)
        hdr_left = LinearLayout(act)
        hdr_left.setOrientation(0)
        hdr_left.setGravity(16)
        if tab:
            hdr_left.addView(self._lib_progress_make(4), LP(self.dp(96), header_h))
        else:
            hdr_left.addView(self._header_btn(("ic_close_white", "msg_close"),
          self._header_close), LP(self.dp(48), header_h))
            progress_lp = LP(self.dp(80), header_h)
            progress_lp.setMargins(self.dp(1), 0, self.dp(2), 0)
            hdr_left.addView(self._lib_progress_make(8), progress_lp)
        title_col = LinearLayout(act)
        title_col.setOrientation(1)
        title_col.setGravity(17)
        self.title_overline = self._text("0 TRACKS FROM", 11 if tab else 10, self.c_sub, bold=True, gravity=17, single=True)
        self.title = self._text(strings("queue"), 20 if tab else 16, self.c_text, bold=True, gravity=17, single=True)
        title_col.addView(self.title_overline, LP(-1, -2))
        title_row = LinearLayout(act)
        title_row.setOrientation(0)
        title_row.setGravity(17)
        av_sz = self.dp(19 if tab else 16)
        self.hdr_avatar_box = jclass("android.widget.FrameLayout")(act)
        self.hdr_avatar_box.setVisibility(8)
        alp = LP(av_sz, av_sz)
        alp.setMargins(0, 0, self.dp(6), 0)
        title_row.addView(self.hdr_avatar_box, alp)
        with tolerated():
            _wpx = int(act.getResources().getDisplayMetrics().widthPixels)
            _rl, _rr = (108, 108) if tab else (124, 124)
            _decor = (19 if tab else 16) + 6 + (17 if tab else 16) + 5 + 4
            self.title.setMaxWidth(max(self.dp(60), _wpx - self.dp(_rl + _rr + _decor)))
        title_row.addView(self.title, LP(-2, -2))
        self.hdr_type = jclass("android.widget.ImageView")(act)
        self.hdr_type.setVisibility(8)
        self.hdr_type.setColorFilter(self.c_sub)
        tlp = LP(self.dp(17 if tab else 16), self.dp(17 if tab else 16))
        tlp.setMargins(self.dp(5), 0, 0, 0)
        title_row.addView(self.hdr_type, tlp)
        title_col.addView(title_row, LP(-1, -2))
        self._hdr_key = None
        title_col.setOnClickListener(self.Click(lambda v: self._open_queue_source()))
        title_col.setContentDescription(strings("open_the_source_of_the_current"))
        self.hdr_more = self._header_btn(("ic_ab_other", "msg_more"), self._open_menu)
        hdr_right = LinearLayout(act)
        hdr_right.setOrientation(0)
        hdr_right.setGravity(16)
        bsz = self.dp(self.BAR_BTN_DP)
        hdr_right.addView(self.hdr_more, LP(bsz, bsz))
        self.hdr_search = self._header_btn(
       ("msg_search", "ic_ab_search", "msg2_search", "ic_search"),
       self._toggle_library_search)
        self.hdr_search.setVisibility(8)
        with tolerated():
            self.hdr_search.setContentDescription(strings("search_library"))
        hdr_right.addView(self.hdr_search, LP(bsz, bsz))
        header = self._centered_bar(hdr_left, title_col, hdr_right, 108 if tab else 124,
       side_dp=8 if tab else 4)
        root.addView(header, LP(-1, header_h if tab else -2))
        self.main_header = header
        activity = LinearLayout(act)
        activity.setOrientation(0)
        activity.setGravity(16)
        activity.setPadding(self.dp(14), 0, self.dp(14), 0)
        activity.setClickable(False)
        activity.setFocusable(False)
        activity_pb = jclass("android.widget.ProgressBar")(act)
        with tolerated():
            activity_pb.getIndeterminateDrawable().setColorFilter(
          self.c_accent, jclass("android.graphics.PorterDuff$Mode").SRC_IN)
        activity.addView(activity_pb, LP(self.dp(16), self.dp(16)))
        activity_text = self._text("", 12, self.c_sub, gravity=16, single=False)
        with tolerated():
            activity_text.setMaxLines(2)
        activity_text.setPadding(self.dp(10), 0, 0, 0)
        activity.addView(activity_text, LP(0, -2, 1.0))
        activity.setVisibility(8)
        root.addView(activity, LP(-1, self.dp(34)))
        self.activity_status_box = activity
        self.activity_status_text = activity_text
        self._build_tabs()
        self.scroll = ScrollView(act)
        with tolerated():
            self.scroll.setOnScrollChangeListener(_scrollchg_proxy()(self._on_scroll))
        self.container = LinearLayout(act)
        self.container.setOrientation(1)
        outer = LinearLayout(act)
        outer.setOrientation(1)
        try:
            clp = _cls("android.widget.LinearLayout$LayoutParams")(-1, 0, jfloat(1.0))
        except Exception:
            clp = LP(-1, -2)
        outer.addView(self.container, clp)
        self.ghost_box = LinearLayout(act)
        self.ghost_box.setOrientation(1)
        outer.addView(self.ghost_box, LP(-1, -2))
        self.scroll.addView(outer)
        sbg = GradientDrawable()
        sbg.setColor(self.c_bg)
        sbg.setCornerRadius(float(self.dp(self.R_BIG)))
        self.scroll.setBackground(sbg)
        self._scroll_fill = sbg
        with tolerated():
            self.scroll.setClipToOutline(True)
        FLc = jclass("android.widget.FrameLayout")
        self.stage = FLc(act)
        self.stage.setClipChildren(False)
        self.stage.addView(self.scroll, jclass("android.widget.FrameLayout$LayoutParams")(-1, -1))
        self._shell_part = (root, dlg)
        if staged:
            return
        self._build_shell_pages(("library", "lyrics"))
        self._build_shell_end()

    def _build_shell_pages(self, which):
        for name in which:
            page = self._build_library_page() if name == "library" else self._build_lyrics_page()
            page.setVisibility(8)
            self.stage.addView(page, jclass("android.widget.FrameLayout$LayoutParams")(-1, -1))
            self.tab_pages[name] = page

    def _build_shell_end(self):
        root, dlg = self._shell_part
        LP = self.LP
        self._style_tabs()
        move_tabs_to_top = bool(self.p.get_setting("move_tabs_to_top", False))
        if move_tabs_to_top:
            root.addView(self.tabs_row, self._tabs_lp())
        slp = LP(-1, 0, 1.0)
        slp.setMargins(self.dp(10), 0, self.dp(10), 0)
        root.addView(self.stage, slp)
        self.root = root
        self._shell = (move_tabs_to_top, dlg)


    def _prep_glass(self):
        act = self.act
        root = self.root
        move_tabs_to_top, dlg = self._shell
        self._glass = _sheet_glass(act, root, self.c_bg)
        with tolerated():
            self._glass.top_solid = move_tabs_to_top
        _dm = act.getResources().getDisplayMetrics()
        self._screen_sz = (int(_dm.widthPixels), int(_dm.heightPixels))
        root.addOnLayoutChangeListener(_layoutchg_proxy()(self._on_resize))
        self.undo_bulletin = None
        self.undo_action_run = None
        self.undo_expire_run = None
        self.undo_token = 0
        if not move_tabs_to_top:
            root.addView(self.tabs_row, self._tabs_lp())

    def _prep_mini(self):
        root = self.root
        move_tabs_to_top, dlg = self._shell
        self._build_mini(root)

    def _prep_finish(self):
        tab = bool(self.tabmode)
        root = self.root
        move_tabs_to_top, dlg = self._shell
        self._glass_surfaces()
        if tab:
            top_in, bot_in = 0, 0
            with tolerated():
                AU = find_class("org.telegram.messenger.AndroidUtilities")
                top_in = int(AU.statusBarHeight)
                bot_in = int(AU.navigationBarHeight)
            self._root_pad_b = self.dp(_TAB_BAR_DP + _TAB_GAP_DP) + bot_in
            root.setPadding(0, top_in, 0, self._root_pad_b)
        else:
            self._root_pad_b = self.dp(12)
            root.setPadding(0, 0, 0, self._root_pad_b)
        with tolerated():
            if getattr(self, "_glass", None) is not None:
                self._glass.set_flat_cb(self._flat_layout)
        if tab:
            self.h_max = self.h_min = self.cur_h = self.screen_h
            self.sized = True
        self._rest_prepared = True

    def _prepare_rest(self):
        if getattr(self, "_rest_prepared", False):
            return
        self._prep_glass()
        self._prep_mini()
        self._prep_finish()

    def _show_rest(self, defer_data=False):
        act = self.act
        tab = bool(self.tabmode)
        root = self.root
        move_tabs_to_top, dlg = self._shell
        ColorDrawable = jclass("android.graphics.drawable.ColorDrawable")
        self._prepare_rest()
        fade = tab and bool(self.__dict__.pop("_fade_in", False))
        if tab:
            if fade:
                root.setAlpha(0.0)
            self.host_frame.addView(root, jclass("android.widget.FrameLayout$LayoutParams")(
          _wide_px(act, 840) or -1, -1, 1))
            self._style_tabs()
        else:
            with tolerated():
                dlg.setOnDismissListener(_dismiss_proxy()(self._on_dismiss))
            with tolerated():
                dlg.setOnKeyListener(_key_proxy()(self._lib_on_key))
            self.h_max = int(self.screen_h * 0.94)
            self.h_min = self._calc_min_h()
            self.cur_h = self.h_min
            self.sized = True
            frame = jclass("android.widget.FrameLayout")(act)
            frame.addView(root, jclass("android.widget.FrameLayout$LayoutParams")(-1, self.h_min, 80))
            frame.setOnTouchListener(self.Touch(lambda v, e: self._frame_touch(e)))
            dlg.setContentView(frame)
            dlg.setCanceledOnTouchOutside(True)
            win = dlg.getWindow()
            if win is not None:
                win.setBackgroundDrawable(ColorDrawable(0))
                win.setLayout(self._sheet_w(), self.h_max)
                win.setGravity(80)
            _attach_sheet_drag(
          self, dlg, lambda: [self.scroll, self.lib_sv],
          lambda: int(self.root.getTop()), self._sd_can_start, self._sd_can_up,
          self._sd_begin, self._sd_move, self._sd_end)
        self.queue_lazy_ready = False
        self.queue_load_pending = False
        self.p._editor = self
        self._attached = True
        with tolerated():
            ph = self.__dict__.pop("_placeholder", None)
            if ph is not None and self.host_frame is not None:
                host = self.host_frame
                ph.animate().alpha(0.0).setDuration(140).withEndAction(
              self.Run(lambda: host.removeView(ph))).start()
        self._fast_first = True
        build = getattr(self.p, "_queue_build_state", None)
        if build is not None and build.get("token") == getattr(self.p, "_queue_build_token", None):
            self._set_progressive_items(build)
        elif tab and self.__dict__.pop("_pre_filled", False) and self.items:
            self._adopt_prefill()
        elif defer_data:
            self._defer_data()
            self._queue_loading_show_once()
        else:
            self._refresh()
            self._queue_loading_show_once()
        try:
            _of = get_last_fragment()
            self._origin_fragment = None
            self._origin_fragment_token = (str(_of.getClass().getName()),
          int(_of.hashCode())) if _of is not None else None
        except Exception:
            self._origin_fragment = None
            self._origin_fragment_token = None
        self.mini_run = self.Run(self._mini_tick)
        self._mini_update()
        self.handler.postDelayed(self.mini_run, 500)
        if not tab:
            try:
                dlg.show()
            except Exception as e:
                if getattr(self.p, "_editor", None) is self:
                    self.p._editor = None
                self.p._bulletin(strings("couldnt_open_the_queue_n", e), error=True)
                return
            with tolerated():
                win = dlg.getWindow()
                win.setLayout(self._sheet_w(), self.h_max)
                win.setGravity(80)
        self.handler.postDelayed(self.Run(self._scroll_to_playing), 120)
        if fade:
            self.handler.post(self.Run(self._fade_root_in))
        self.p._update_schedule()

    def _fade_root_in(self):
        r = self.root
        with tolerated():
            r.setLayerType(2, None)
        def end():
            with tolerated():
                r.setLayerType(0, None)
        try:
            r.animate().alpha(1.0).setDuration(170).withEndAction(self.Run(end)).start()
        except Exception:
            r.setAlpha(1.0)
            end()

    def _adopt_prefill(self):
        self.__dict__.pop("_fast_first", None)
        self.queue_load_pending = False
        self._q_revealed = True
        with tolerated():
            self._update_title()
        self._snap_to_playing_predraw()
        self.handler.postDelayed(self.Run(self._load_visible_covers), 60)
        with tolerated():
            self._update_locate_visibility()
        self._prefetch_queue_neighbors()

    def prefill(self, finished):
        with tolerated():
            mc = self.p._get_mc()
            pl = self.p._get_playlist(mc) if mc is not None else None
            if pl is not None and int(pl.size()) > 0:
                def loaded(ok):
                    live = not getattr(self, "_cancelled", False) and not self.__dict__.get("_attached")
                    if not (live and ok and self.items):
                        finished()
                        return
                    self.queue_data_token += 1
                    tok = self.queue_data_token
                    pi = self._playing_pos()
                    self._choose_initial_loaded_range(pi)
                    self.container.removeAllViews()
                    self.rows, self.row_refs = [], {}
                    start, end = self.win_start, self.win_end
                    self.win_end = start
                    self.queue_load_pending = True
                    self.QUEUE_CHUNK_ROWS = 12
                    self._row_budget = 0.006
                    def fin():
                        if tok != self.queue_data_token:
                            return
                        for k in ("QUEUE_CHUNK_ROWS", "_row_budget"):
                            self.__dict__.pop(k, None)
                        self.queue_load_pending = False
                        self._styled_playing = pi
                        with tolerated():
                            self._ghost_render()
                        with tolerated():
                            self._update_title()
                        with tolerated():
                            self._mini_update()
                        self._pre_filled = True
                        finished()
                    self._append_queue_rows(start, end, fin)
                self._load_async(loaded)
                return
        finished()

    def _defer_data(self):
        self.queue_load_pending = True
        def done(_ok):
            if getattr(self, "_cancelled", False) or getattr(self.p, "_editor", None) is not self:
                return
            self.queue_load_pending = False
            self._refresh()
        self._load_async(done)

    def _load_async(self, done):
        mc = self.p._get_mc()
        pl = self.p._get_playlist(mc) if mc is not None else None
        if pl is None or int(pl.size()) == 0:
            done(self._load())
            return
        def work():
            ok = False
            with tolerated():
                ok = self._load()
            run_on_ui_thread(lambda: done(ok))
        threading.Thread(target=work, daemon=True, name="MusicPlus-queue-load").start()

    _SIG_SETTINGS = ("bar_height", "dynamic_tint", "glass_follow_tg", "keep_sheet_alive", "lock_queue",
                     "lyrics_keep_awake", "mini_compact", "move_tabs_to_top", "queue_tint_anim", "replace_row",
                     "sheet_expand_first", "sheet_min_height", "hq_thumbs", "lib_grid_columns")

    def theme_sig(self):
        cols = tuple(self._theme(n, -1) for n in (
            "key_windowBackgroundGray", "key_dialogBackground", "key_windowBackgroundWhite",
            "key_windowBackgroundWhiteBlackText", "key_windowBackgroundWhiteGrayText2", "key_player_buttonActive",
            "key_player_background", "key_divider"))
        sets = tuple(str(self.p.get_setting(k, None)) for k in self._SIG_SETTINGS)
        return cols + (tint.current(),) + sets

    def attach_prewarmed(self, host):
        self.host_frame = host
        self._show_rest(defer_data=True)

    TABS = (("library", "library"), ("queue", "queue"), ("lyrics", "lyrics"))

    def _queue_loading_show(self):
        with tolerated():
            LL = jclass("android.widget.LinearLayout")
            ov = LL(self.act)
            ov.setOrientation(1)
            ov.setGravity(17)
            ov.setBackgroundColor(self.c_bg)
            ov.setClickable(True)
            pb = jclass("android.widget.ProgressBar")(self.act)
            with tolerated():
                pb.setIndeterminateTintList(jclass("android.content.res.ColorStateList").valueOf(self.c_accent))
            ov.addView(pb, self.LP(self.dp(36), self.dp(36)))
            t = self._text(strings("loading_queue"), 14, self.c_sub, gravity=17)
            t.setPadding(0, self.dp(14), 0, 0)
            ov.addView(t, self.LP(-2, -2))
            self.stage.addView(ov, jclass("android.widget.FrameLayout$LayoutParams")(-1, -1))
            self._queue_loading = ov
            self.scroll.setVisibility(4)
            self.handler.postDelayed(self.Run(self._loading_failsafe), 4000)

    def _loading_failsafe(self, n=0):
        if self.__dict__.get("_queue_loading") is None and self.__dict__.get("_placeholder") is None:
            return
        if (getattr(self, "queue_load_pending", False) or getattr(self, "_resuming", False)) and n < 6:
            self.handler.postDelayed(self.Run(lambda: self._loading_failsafe(n + 1)), 2000)
            return
        self._queue_loading_hide()

    def stage_placeholder(self, host):
        LL = jclass("android.widget.LinearLayout")
        ov = LL(self.act)
        ov.setOrientation(1)
        ov.setGravity(17)
        ov.setBackgroundColor(self.c_bg)
        pb = jclass("android.widget.ProgressBar")(self.act)
        with tolerated():
            pb.setIndeterminateTintList(jclass("android.content.res.ColorStateList").valueOf(self.c_accent))
        ov.addView(pb, self.LP(self.dp(36), self.dp(36)))
        t = self._text(strings("loading_queue"), 14, self.c_sub, gravity=17)
        t.setPadding(0, self.dp(14), 0, 0)
        ov.addView(t, self.LP(-2, -2))
        ov.setClickable(True)
        ov.setAlpha(0.0)
        host.addView(ov, jclass("android.widget.FrameLayout$LayoutParams")(-1, -1))
        with tolerated():
            ov.animate().alpha(1.0).setDuration(120).start()
        self._placeholder = ov
        return ov

    def _queue_loading_show_once(self):
        if (getattr(self, "queue_load_pending", False) or getattr(self, "_resuming", False)) \
                and self.__dict__.get("_queue_loading") is None and self.tab == "queue":
            self._queue_loading_show()

    def _queue_loading_hide(self):
        self._q_revealed = True
        ov = self.__dict__.pop("_queue_loading", None)
        ph = self.__dict__.pop("_placeholder", None)
        if ov is None and ph is None:
            return
        with tolerated():
            if self.tab == "queue":
                self.scroll.setVisibility(0)
        for v, parent in ((ov, getattr(self, "stage", None)), (ph, getattr(self, "host_frame", None))):
            if v is None or parent is None:
                continue
            with tolerated():
                v.animate().alpha(0.0).setDuration(180).withEndAction(
              self.Run(lambda v=v, parent=parent: parent.removeView(v))).start()

    def _glass_surfaces(self):
        g = getattr(self, "_glass", None)
        if g is None or g.broken:
            return
        try:
            g.add_surface(self.tabs_row, self.dp(19), self.c_item, 0.6)
            g.add_surface(self.mini_box, self.dp(22), self.c_player_bg, 0.62, self._mini_fill_drawable())
            g.set_layout(self.stage, [self.scroll, self.lyr_sv], self.lib_sv, self.lib_page_root, self.lib_detail_header_host)
            g.add_inset(self.lib_fab_host)
            sp = jclass("android.view.View")(self.act)
            sp.setVisibility(8)
            self.root.addView(sp, self.LP(-1, 0))
            self._flat_spacer = sp
            g.add_spacer(sp)
        except Exception as e:
            _glass_note("surfaces", e)

    def _flat_layout(self, on):
        root, sp = self.root, getattr(self, "_flat_spacer", None)
        pb = int(getattr(self, "_root_pad_b", 0))
        root.setPadding(int(root.getPaddingLeft()), int(root.getPaddingTop()), int(root.getPaddingRight()), 0 if on else pb)
        root.setClipChildren(not on)
        root.setClipToPadding(not on)
        if sp is not None:
            if on:
                lp = sp.getLayoutParams()
                lp.height = pb
                sp.setLayoutParams(lp)
            sp.setVisibility(0 if on else 8)
        root.requestLayout()

    def _mini_fill_drawable(self):
        try:
            return self.mini_fill.getDrawable()
        except Exception:
            return None

    def _tabs_lp(self):
        top = bool(self.p.get_setting("move_tabs_to_top", False))
        lp = self.LP(-1, self.dp(38))
        lp.setMargins(self.dp(10), self.dp(6 if top else 8), self.dp(10), self.dp(8 if top else 0))
        return lp

    def _build_tabs(self):
        GD = _cls("android.graphics.drawable.GradientDrawable")
        FL = jclass("android.widget.FrameLayout")
        FLP = jclass("android.widget.FrameLayout$LayoutParams")
        row = FL(self.act)
        row.setPadding(self.dp(3), self.dp(3), self.dp(3), self.dp(3))
        box = GD()
        box.setColor(self.c_item)
        box.setCornerRadius(float(self.dp(19)))
        row.setBackground(box)
        pill = jclass("android.view.View")(self.act)
        pg = GD()
        pg.setColor(self.c_sel)
        pg.setCornerRadius(float(self.dp(16)))
        pill.setBackground(pg)
        pill.setVisibility(4)
        row.addView(pill, FLP(0, -1))
        inner = jclass("android.widget.LinearLayout")(self.act)
        inner.setOrientation(0)
        inner.setGravity(16)
        row.addView(inner, FLP(-1, -1))
        for i, (name, label) in enumerate(self.TABS):
            tv = self._text(strings(label), 13, self.c_sub, bold=True, gravity=17, single=True)
            tv.setOnClickListener(self.Click(self._tab_click(name)))
            lp = self.LP(0, -1, 1.0)
            if i:
                lp.setMargins(self.dp(2), 0, 0, 0)
            inner.addView(tv, lp)
            self.tab_btns[name] = tv
        views = [self.tab_btns[n] for n, _ in self.TABS]
        self.tab_pr = _PillRow(self, pill, views, views)
        self.tabs_row = row
        return row

    def _tab_click(self, name):
        return lambda v: self._set_tab(name)

    _tab_anim = None
    _tab_post = None

    def _tab_index(self, name):
        return [n for n, _ in self.TABS].index(name)

    def _style_tabs(self, snap=True):
        if snap:
            self.tab_pr.set(self._tab_index(self.tab))

    def _page_of_tab(self, name):
        return self.scroll if name == "queue" else self.tab_pages.get(name)

    def _tab_anim_end(self, snap=True):
        had = self._tab_anim is not None
        self._tab_anim = None
        with tolerated():
            for name in self.tab_btns:
                page = self._page_of_tab(name)
                if page is None:
                    continue
                page.setTranslationX(0.0)
                with tolerated():
                    page.setLayerType(0, None)
                page.setVisibility(0 if name == self.tab else 8)
            if had:
                self.stage.setClipChildren(False)
        if snap:
            self.tab_pr.cancel()
        self._style_tabs(snap)
        post, self._tab_post = self._tab_post, None
        if post is not None and post[0] == self.tab:
            self.handler.postDelayed(self.Run(post[1]), 16)

    def _tab_anim_start(self, old, new):
        order = [n for n, _ in self.TABS]
        try:
            w = int(self.stage.getWidth())
            pin, pout = self._page_of_tab(new), self._page_of_tab(old)
            if w <= 0 or pin is None or pout is None or old not in order \
          or self.tab_pr.geom(order.index(new))[1] <= 0:
                self._tab_anim_end()
                return
            d = 1.0 if order.index(new) > order.index(old) else -1.0
            for page in self.tab_pages.values():
                if page is not pin and page is not pout:
                    page.setVisibility(8)
            if self.scroll is not pin and self.scroll is not pout:
                self.scroll.setVisibility(8)
            pin.setVisibility(0)
            pout.setVisibility(0)
            for pg_ in (pin, pout):
                with tolerated():
                    pg_.setLayerType(2, None)
            pin.setTranslationX(d * w)
            pout.setTranslationX(0.0)
            self.stage.setClipChildren(True)
            anim = {}
            self._tab_anim = anim
            def on_frame(e):
                if self._tab_anim is anim:
                    pin.setTranslationX(d * w * (1.0 - e))
                    pout.setTranslationX(-d * w * e)
            def on_end():
                if self._tab_anim is anim:
                    self._tab_anim_end(snap=False)
                    self.tab_pr.set(self._tab_index(self.tab))
            self.tab_pr.slide(order.index(new), on_frame, on_end)
        except Exception:
            self._tab_anim_end()

    def _lib_unchanged(self):
        try:
            return bool(self.lib_loaded) and self.__dict__.get("_lib_sig_done") == self._lib_sig()
        except Exception:
            return False

    def _queue_library_refresh(self):
        with tolerated():
            if self.tab != "library" or self.lib_state != ("home", None):
                return
            if self.lib_search_active and self.lib_search_query.strip():
                return
            self.p._lib_sync_names()
            if getattr(self, "_lib_refresh_pending", False) or self._lib_unchanged():
                return
            self._lib_refresh_pending = True
            old_y = int(self.lib_sv.getScrollY()) if self.lib_sv is not None else 0
            def refresh():
                self._lib_refresh_pending = False
                if self.tab != "library" or self.lib_state != ("home", None):
                    return
                if self.lib_search_active and self.lib_search_query.strip():
                    return
                if self._lib_unchanged():
                    return
                with tolerated():
                    self._lib_render()
                    self.handler.postDelayed(self.Run(lambda: self.lib_sv.scrollTo(0, old_y)), 50)
            self.handler.postDelayed(self.Run(refresh), 120)

    def _set_tab(self, name):
        if name == self.tab:
            if name == "library":
                self._queue_library_refresh()
            return
        if self.drag is not None:
            return
        if self.sel_mode:
            self._exit_sel()
        old = self.tab
        self._tab_post = None
        if self._tab_anim is not None:
            self._tab_anim_end(snap=False)
        self.tab = name
        pin = self._page_of_tab(name)
        pout = self._page_of_tab(old)
        for key in self.tab_btns:
            page = self._page_of_tab(key)
            if page is not None:
                page.setVisibility(0 if page in (pin, pout) else 8)
        self.mini_box.setVisibility(0)
        self.mini_box.setTranslationY(0.0)
        self.hdr_more.setVisibility(0 if name in ("queue", "lyrics") else 8)
        self.hdr_search.setVisibility(0 if name == "library" else 8)
        self._update_library_search_button()
        self._update_title()
        def _heavy(name=name):
            if self.tab != name:
                return
            if name == "library":
                self.__dict__.pop("_lib_pre", None)
                try:
                    fresh = bool(self.lib_loaded) and self.__dict__.get("_lib_sig_done") == self._lib_sig()
                except Exception:
                    fresh = False
                if not fresh and bool(self.lib_loaded) and not self.__dict__.get("_lib_shown", False):
                    with tolerated():
                        fresh = self.__dict__.get("_lib_dsig_done") == self._lib_data_sig()
                if fresh:
                    self.main_header.setVisibility(8 if self.lib_state[0] != "home" else 0)
                    self.handler.postDelayed(self.Run(self._lib_load_covers), 30)
                else:
                    self._lib_render()
                self._lib_shown = True
            if name == "lyrics":
                self._lyr_start()
        self._tab_post = (name, _heavy) if name in ("library", "lyrics") else None
        if name == "queue":
            self.handler.postDelayed(self.Run(self._load_visible_covers), 30)
            self.handler.postDelayed(self.Run(self._refresh_dl), 40)
            self.handler.postDelayed(self.Run(self._update_locate_visibility), 60)
        else:
            with tolerated():
                self.mini_locate.setVisibility(8)
        self._tab_anim_start(old, name)

    PAGE_ROWS = 32

    def _build_library_page(self):
        SV = jclass("android.widget.ScrollView")
        LL = jclass("android.widget.LinearLayout")
        self.lib_page_root = LL(self.act)
        self.lib_page_root.setOrientation(1)
        self.lib_detail_header_host = LL(self.act)
        self.lib_detail_header_host.setOrientation(1)
        self.lib_detail_header_host.setVisibility(8)
        self.lib_page_root.addView(self.lib_detail_header_host, self.LP(-1, -2))
        self.lib_sv = SV(self.act)
        self.lib_root = LL(self.act)
        self.lib_root.setOrientation(1)
        self.lib_root.setPadding(0, self.dp(2), 0, self.dp(14))
        self.lib_search_active = False
        self.lib_search_query = ""
        self._lib_search_pending_query = ""
        self._lib_search_generation = 0
        self._lib_search_suppress = False
        self.lib_search_bar = LL(self.act)
        self.lib_search_bar.setOrientation(0)
        self.lib_search_bar.setGravity(16)
        self.lib_search_bar.setPadding(self.dp(10), 0, self.dp(6), 0)
        search_bg = _cls("android.graphics.drawable.GradientDrawable")()
        search_bg.setColor(self.c_item)
        search_bg.setCornerRadius(float(self.dp(12)))
        self.lib_search_bar.setBackground(search_bg)
        self.lib_search_bar.setVisibility(8)
        search_icon = self._glyph_icon(("msg_search", "ic_ab_search", "msg2_search"), self.c_sub, pad=5, size=20)
        self.lib_search_bar.addView(search_icon, self.LP(self.dp(34), self.dp(44)))
        self.lib_search_input = _cls("android.widget.EditText")(self.act)
        self.lib_search_input.setSingleLine(True)
        self.lib_search_input.setTextSize(16)
        self.lib_search_input.setTextColor(self.c_text)
        self.lib_search_input.setHintTextColor(self.c_sub)
        self.lib_search_input.setHint(strings("search_library"))
        self.lib_search_input.setPadding(self.dp(4), 0, self.dp(4), 0)
        self.lib_search_input.setBackgroundColor(0)
        self.lib_search_input.setImeOptions(3)
        self.lib_search_bar.addView(self.lib_search_input, self.LP(0, self.dp(48), 1.0))
        self.lib_search_clear = self._glyph_icon(("msg_close", "ic_close_white", "msg_cancel"), self.c_sub, pad=8, size=18)
        self.lib_search_clear.setContentDescription(strings("clear_library_search"))
        self.lib_search_clear.setOnClickListener(
       self.Click(lambda v: self.lib_search_input.setText("")))
        self.lib_search_bar.addView(self.lib_search_clear, self.LP(self.dp(38), self.dp(44)))
        search_lp = self.LP(-1, self.dp(48))
        search_lp.setMargins(self.dp(12), self.dp(8), self.dp(12), self.dp(4))
        self.lib_root.addView(self.lib_search_bar, search_lp)
        self.lib_box = LL(self.act)
        self.lib_box.setOrientation(1)
        self.lib_root.addView(self.lib_box, self.LP(-1, -2))
        self.lib_sv.addView(self.lib_root)
        self.lib_page_root.addView(self.lib_sv, self.LP(-1, 0, 1.0))
        FLf = jclass("android.widget.FrameLayout")
        FLPf = jclass("android.widget.FrameLayout$LayoutParams")
        self.lib_page_frame = FLf(self.act)
        self.lib_page_frame.addView(self.lib_page_root, FLPf(-1, -1))
        self.lib_fab_host = LL(self.act)
        self.lib_fab_host.setOrientation(1)
        self.lib_fab_host.setGravity(5)
        self.lib_fab_host.setVisibility(8)
        fab_host_lp = FLPf(-2, -2, 85)
        fab_host_lp.setMargins(0, 0, self.dp(16), self.dp(16))
        self.lib_page_frame.addView(self.lib_fab_host, fab_host_lp)
        editor = self
        TextWatcher = _cls("android.text.TextWatcher")
        class LibrarySearchWatcher(dynamic_proxy(TextWatcher)):
            def __init__(self):
                super().__init__()
            def beforeTextChanged(self, s, start, count, after):
                pass
            def onTextChanged(self, s, start, before, count):
                with tolerated():
                    if editor._lib_search_suppress:
                        return
                    query = str(s or "")
                    if query == editor._lib_search_pending_query:
                        return
                    editor._lib_search_pending_query = query
                    editor._lib_search_generation += 1
                    generation = editor._lib_search_generation
                    def apply_search():
                        with tolerated():
                            if generation != editor._lib_search_generation:
                                return
                            if editor._lib_search_suppress:
                                return
                            if query == editor.lib_search_query:
                                return
                            editor.lib_search_query = query
                            if editor.lib_loaded:
                                if editor.lib_state != ("home", None):
                                    editor.lib_state = ("home", None)
                                    editor.__dict__.pop("_pl_ghosts", None)
                                    editor._lib_reset_selection(None)
                                editor._lib_render()
                    editor.handler.postDelayed(editor.Run(apply_search), 350)
            def afterTextChanged(self, s):
                pass
        self._lib_search_watcher = LibrarySearchWatcher()
        self.lib_search_input.addTextChangedListener(self._lib_search_watcher)
        g = _cls("android.graphics.drawable.GradientDrawable")()
        g.setColor(self.c_bg)
        g.setCornerRadius(float(self.dp(self.R_BIG)))
        self.lib_sv.setBackground(g)
        self._lib_fill = g
        with tolerated():
            self.lib_sv.setClipToOutline(True)
        with tolerated():
            self.lib_sv.setOnScrollChangeListener(_scrollchg_proxy()(self._lib_on_scroll))
        self.lib_state = ("home", None)
        self.__dict__.pop("_pl_ghosts", None)
        self.lib_confirm = None
        self.lib_loading = set()
        self.lib_waiters = {}
        self.lib_streams = {}
        self.lib_resolved = set()
        self.lib_covers = []
        self.lib_reorder_rows = {"playlists": [], "chats": [], "friends": []}
        self.lib_track_loader = None
        self.lib_track_rows = {}
        self.lib_track_reorder_rows = []
        self.lib_sel_mode = False
        self.lib_selected = set()
        self.lib_sel_context = None
        self.lib_detail_title = None
        self.lib_detail_meta = None
        self.lib_detail_base_title = ""
        self.lib_detail_base_meta = ""
        self.lib_queue_cache_ready = False
        self.lib_loaded = False
        return self.lib_page_frame
