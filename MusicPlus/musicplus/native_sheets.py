from .compat import jarray, jclass, jfloat, jint
from elyx import strings
from .helpers import _argb
from .android import _mix, _proxies, _wide_px
from .editor import _QueueEditor
from .safe import tolerated


class _ProgressSheet(_QueueEditor):
    def show_progress(self, title, on_cancel, on_continue=None, force=False):
        if not force:
            with tolerated():
                editor = getattr(self.p, "_editor", None)
                if getattr(editor, "tab", None) == "library":
                    self.dialog = None
                    self.label = None
                    return
        act = self.act
        LinearLayout = jclass("android.widget.LinearLayout")
        Dialog = jclass("android.app.Dialog")
        GradientDrawable = jclass("android.graphics.drawable.GradientDrawable")
        ColorDrawable = jclass("android.graphics.drawable.ColorDrawable")
        ProgressBar = jclass("android.widget.ProgressBar")
        LP = self.LP
        dlg = Dialog(act)
        dlg.requestWindowFeature(1)
        self.dialog = dlg
        root = LinearLayout(act)
        root.setOrientation(1)
        bg = GradientDrawable()
        bg.setColor(self.c_bg)
        r = float(self.dp(16))
        bg.setCornerRadii(jarray(jfloat)([r, r, r, r, 0.0, 0.0, 0.0, 0.0]))
        root.setBackground(bg)
        root.setPadding(self.dp(20), self.dp(16), self.dp(12), self.dp(12))
        root.addView(self._text(title, 20, self.c_text, bold=True), LP(-1, -2))
        line = LinearLayout(act)
        line.setOrientation(0)
        line.setGravity(16)
        line.setPadding(0, self.dp(14), 0, self.dp(6))
        line.addView(ProgressBar(act), LP(self.dp(28), self.dp(28)))
        self.label = self._text(strings("starting"), 15, self.c_sub)
        self.label.setPadding(self.dp(14), 0, 0, 0)
        line.addView(self.label, LP(0, -2, 1.0))
        root.addView(line, LP(-1, -2))
        row = LinearLayout(act)
        row.setGravity(8388613)
        cancel = self._text(strings("cancel"), 16, self.c_sub, bold=True, gravity=17)
        cancel.setPadding(self.dp(16), self.dp(10), self.dp(8), self.dp(10))
        def _cancel(v):
            try:
                on_cancel()
            finally:
                dlg.dismiss()
        cancel.setOnClickListener(self.Click(_cancel))
        row.addView(cancel, LP(-2, -2))
        if on_continue is not None:
            cont = self._text(strings("continue"), 16, self.c_accent, bold=True, gravity=17)
            cont.setPadding(self.dp(12), self.dp(10), self.dp(8), self.dp(10))
            def _continue(v):
                try:
                    on_continue()
                finally:
                    dlg.dismiss()
            cont.setOnClickListener(self.Click(_continue))
            row.addView(cont, LP(-2, -2))
        root.addView(row, LP(-1, -2))
        dlg.setContentView(root)
        dlg.setCancelable(False)
        win = dlg.getWindow()
        if win is not None:
            win.setBackgroundDrawable(ColorDrawable(0))
            win.setLayout(-1, -2)
            win.setGravity(80)
        dlg.show()
        with tolerated():
            win = dlg.getWindow()
            win.setLayout(-1, -2)
            win.setGravity(80)
    def set_text(self, text):
        with tolerated():
            self.label.setText(str(text))
    def close(self):
        with tolerated():
            self.dialog.dismiss()


class _NativeSheet:
    def __init__(self, act, title, subtitle=None, max_frac=0.55):
        self.act = act
        self.LL = jclass("android.widget.LinearLayout")
        self.GD = jclass("android.graphics.drawable.GradientDrawable")
        self.Click = _proxies()[1]
        self.dm = act.getResources().getDisplayMetrics()
        d = float(self.dm.density)
        self.dp = lambda v: int(round(float(v) * d))
        th = _QueueEditor._theme
        self.c_bg = th("key_windowBackgroundGray", th("key_dialogBackground", -1))
        self.c_item = th("key_windowBackgroundWhite", self.c_bg)
        self.c_text = th("key_windowBackgroundWhiteBlackText", _argb(255, 33, 33, 33))
        self.c_sub = th("key_windowBackgroundWhiteGrayText2", _argb(255, 138, 138, 138))
        self.c_line = th("key_divider", _argb(40, 128, 128, 128))
        self.c_red = th("key_text_RedBold", _argb(255, 229, 57, 53))
        self.c_accent = th("key_player_buttonActive",
       th("key_windowBackgroundWhiteBlueText", _argb(255, 42, 139, 234)))
        self.wpx = _wide_px(act, 600)
        self.max_h = int(self.dm.heightPixels * (0.85 if self.wpx else max_frac))
        dp = self.dp
        self.dlg = jclass("android.app.Dialog")(act)
        self.dlg.requestWindowFeature(1)
        root = self.LL(act)
        root.setOrientation(1)
        bg = self.GD()
        bg.setColor(self.c_bg)
        r = float(dp(16))
        bg.setCornerRadii(jarray(jfloat)([r, r, r, r, 0.0, 0.0, 0.0, 0.0]))
        root.setBackground(bg)
        root.setPadding(0, 0, 0, dp(12))
        grab = self.LL(act)
        grab.setGravity(17)
        pill = jclass("android.view.View")(act)
        pg = self.GD()
        pg.setColor(_mix(self.c_bg, self.c_sub, 0.5))
        pg.setCornerRadius(float(dp(2)))
        pill.setBackground(pg)
        grab.addView(pill, self.LP(dp(36), dp(4)))
        root.addView(grab, self.LP(-1, dp(18)))
        t = self.text(title, 20, self.c_text, True)
        t.setPadding(dp(20), dp(2), dp(20), 0)
        root.addView(t, self.LP(-1, -2))
        if subtitle:
            st = self.text(subtitle, 13, self.c_sub)
            st.setPadding(dp(20), dp(4), dp(20), dp(8))
            root.addView(st, self.LP(-1, -2))
        self.sv = jclass("android.widget.ScrollView")(act)
        self.sv.setVerticalScrollBarEnabled(False)
        self.sv.setOverScrollMode(2)
        self.body = self.LL(act)
        self.body.setOrientation(1)
        self.body.setPadding(dp(12), dp(4), dp(12), dp(4))
        self.sv.addView(self.body, self.LP(-1, -2))
        root.addView(self.sv, self.LP(-1, -2))
        self.footer = self.LL(act)
        self.footer.setOrientation(1)
        self.footer.setPadding(dp(16), dp(10), dp(16), 0)
        root.addView(self.footer, self.LP(-1, -2))
        self.root = root
    @staticmethod
    def LP(w, h, weight=None):
        C = jclass("android.widget.LinearLayout$LayoutParams")
        return C(w, h) if weight is None else C(w, h, weight)
    def text(self, value, size, color, bold=False, gravity=3, single=False):
        tv = jclass("android.widget.TextView")(self.act)
        tv.setText(str(value))
        tv.setTextSize(float(size))
        tv.setTextColor(int(color))
        tv.setGravity(int(gravity))
        if bold:
            tv.setTypeface(jclass("android.graphics.Typeface").DEFAULT_BOLD)
        if single:
            tv.setSingleLine(True)
            tv.setEllipsize(jclass("android.text.TextUtils$TruncateAt").END)
        return tv
    def ripple(self, view, radius=0, circle=False):
        with tolerated():
            col = int(_mix(self.c_item, self.c_sub, 0.3)) & 0xFFFFFF
            col = (0x55 << 24) | col
            col = ((col & 0xFFFFFFFF) ^ 0x80000000) - 0x80000000
            over = self.GD()
            over.setColor(col)
            if circle:
                over.setShape(1)
            else:
                over.setCornerRadius(float(self.dp(radius)))
            sl = jclass("android.graphics.drawable.StateListDrawable")()
            sl.addState(jarray(jint)([16842919]), over)
            base = view.getBackground()
            if base is not None:
                sl.addState(jarray(jint)([]), base)
            view.setBackground(sl)
    def section(self, label):
        tv = self.text(label, 15, self.c_accent, True)
        tv.setPadding(self.dp(8), self.dp(10), self.dp(8), self.dp(6))
        self.body.addView(tv, self.LP(-1, -2))
    def card(self):
        card = self.LL(self.act)
        card.setOrientation(1)
        bg = self.GD()
        bg.setColor(self.c_item)
        bg.setCornerRadius(float(self.dp(14)))
        card.setBackground(bg)
        with tolerated():
            card.setClipToOutline(True)
        self.body.addView(card, self.LP(-1, -2))
        return card
    def divider(self, card, inset=16):
        with tolerated():
            g = getattr(self, "_glass", None)
            if g is not None and g.mode and g.mode[0]:
                return
        v = jclass("android.view.View")(self.act)
        v.setBackgroundColor(self.c_line)
        lp = self.LP(-1, max(1, self.dp(1) // 2))
        lp.setMargins(self.dp(inset), 0, 0, 0)
        card.addView(v, lp)
    def circle(self, content, size=40, tint=True):
        tv = self.text(content, 16, self.c_accent, True, 17)
        bg = self.GD()
        bg.setShape(1)
        bg.setColor(_mix(self.c_item, self.c_accent, 0.16 if tint else 0.0))
        tv.setBackground(bg)
        return tv
    def text_button(self, label, cb, color=None, size=14):
        tv = self.text(label, size, color if color is not None else self.c_accent, True, 17)
        tv.setPadding(self.dp(12), self.dp(8), self.dp(12), self.dp(8))
        tv.setOnClickListener(self.Click(lambda v: cb()))
        self.ripple(tv, 10)
        return tv
    def primary_button(self, label, cb, color=None):
        tv = self.text(label, 15, -1, True, 17)
        bg = self.GD()
        bg.setColor(color if color is not None else self.c_accent)
        bg.setCornerRadius(float(self.dp(12)))
        tv.setBackground(bg)
        tv.setOnClickListener(self.Click(lambda v: cb()))
        self.ripple(tv, 12)
        self.footer.addView(tv, self.LP(-1, self.dp(48)))
        return tv
    def secondary_row(self, *buttons):
        row = self.LL(self.act)
        row.setOrientation(0)
        row.setGravity(17)
        for label, cb in buttons:
            row.addView(self.text_button(label, cb), self.LP(-2, -2))
        self.footer.addView(row, self.LP(-1, -2))
    def fit(self):
        with tolerated():
            MS = jclass("android.view.View$MeasureSpec")
            w = (self.wpx or int(self.dm.widthPixels)) - self.dp(24)
            self.body.measure(MS.makeMeasureSpec(w, 1073741824), MS.makeMeasureSpec(0, 0))
            h = min(int(self.body.getMeasuredHeight()), self.max_h)
            lp = self.sv.getLayoutParams()
            lp.height = int(h)
            self.sv.setLayoutParams(lp)
    def show(self):
        self.fit()
        self.dlg.setContentView(self.root)
        self.dlg.setCanceledOnTouchOutside(True)
        win = self.dlg.getWindow()
        if win is not None:
            win.setBackgroundDrawable(jclass("android.graphics.drawable.ColorDrawable")(0))
            win.setLayout(self.wpx or -1, -2)
            win.setGravity(80)
        self.dlg.show()
        with tolerated():
            self._activity_refresh()
        with tolerated():
            win = self.dlg.getWindow()
            win.setLayout(self.wpx or -1, -2)
            win.setGravity(80)
