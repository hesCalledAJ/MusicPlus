from .compat import jarray, jclass, jfloat, jint
from elyx import strings
from .android import _cls, _mix, _wide_px
from .glass import _attach_sheet_drag, _hit
from .equalizer import (
 EQ_FREQS,
 EQ_MAX_DB,
 EQ_MIN_DB,
 EQ_PRESETS,
 EQ_STEP_DB,
 curve_at,
 freq_label,
 preset_gains,
)
from .safe import tolerated
from .sheets import _PlaybackSheet


def _ci(v):
    return jint(((int(v) & 0xFFFFFFFF) ^ 0x80000000) - 0x80000000)


def eq_summary(p):
    eq = getattr(p, "_eq", None)
    if eq is None or not eq.is_on():
        return strings("state_off")
    key = eq.preset()
    if not key:
        return strings("eq_custom")
    for k, sk, _g in EQ_PRESETS:
        if k == key:
            return strings(sk)
    u = eq.user_preset(key)
    if u is not None:
        return u["name"]
    return strings("eq_custom")


def _db(v):
    return f"{v:+g} dB" if abs(v) >= 0.01 else "0 dB"


class _EqualizerSheet(_PlaybackSheet):
    def show(self):
        act, dp, LP, p = self.act, self.dp, self.LP, self.p
        eq = getattr(p, "_eq", None)
        if eq is None:
            p._bulletin(strings("equalizer_is_unavailable"), error=True)
            return
        LL = jclass("android.widget.LinearLayout")
        SV = jclass("android.widget.ScrollView")
        HSV = jclass("android.widget.HorizontalScrollView")
        Dialog = jclass("android.app.Dialog")
        GD = jclass("android.graphics.drawable.GradientDrawable")
        CD = jclass("android.graphics.drawable.ColorDrawable")
        View = jclass("android.view.View")
        red = self.c_red
        dlg = Dialog(act)
        dlg.requestWindowFeature(1)
        root = LL(act)
        root.setOrientation(1)
        bg = GD()
        bg.setColor(self.c_bg)
        r = float(dp(16))
        bg.setCornerRadii(jarray(jfloat)([r, r, r, r, 0.0, 0.0, 0.0, 0.0]))
        root.setBackground(bg)
        root.setPadding(0, 0, 0, dp(12))
        grab = LL(act)
        grab.setGravity(17)
        gp = View(act)
        gg = GD()
        gg.setColor(_mix(self.c_bg, self.c_sub, 0.5))
        gg.setCornerRadius(float(dp(2)))
        gp.setBackground(gg)
        grab.addView(gp, LP(dp(36), dp(4)))
        root.addView(grab, LP(-1, dp(18)))
        refreshers = []

        def sync_fx():
            eq.sync()

        def sync():
            for fn in refreshers:
                with tolerated():
                    fn()
            self._refresh()

        head = LL(act)
        head.setOrientation(0)
        head.setGravity(16)
        head.setPadding(dp(20), 0, dp(20), 0)
        tcol = LL(act)
        tcol.setOrientation(1)
        tcol.addView(self._text(strings("equalizer"), 18, self.c_text, bold=True, single=True), LP(-1, -2))
        sub = self._text("", 13, self.c_sub, single=True)
        sub.setPadding(0, dp(2), 0, 0)
        tcol.addView(sub, LP(-1, -2))
        head.addView(tcol, LP(0, -2, 1.0))
        sw = jclass("android.widget.Switch")(act)
        sw.setChecked(eq.is_on())
        sw.setClickable(False)
        sw.setFocusable(False)
        head.addView(sw, LP(-2, -2))

        def toggle_master(v=None):
            eq.set_on(not eq.is_on())
            sync_fx()
            sync()
        head.setOnClickListener(self.Click(toggle_master))
        self._press_fx(head)
        root.addView(head, LP(-1, -2))

        def sub_text():
            if not eq.is_on():
                return strings("state_off")
            bits = [eq_summary(p)]
            if eq.supported is False:
                bits.append(eq.why or strings("equalizer_needs_a_playing_track"))
            return " · ".join(bits)
        refreshers.append(lambda: (sw.setChecked(eq.is_on()), sub.setText(sub_text())))
        sub.setText(sub_text())

        body = LL(act)
        body.setOrientation(1)
        body.setPadding(0, dp(12), 0, 0)
        sv = SV(act)
        sv.addView(body)
        root.addView(sv, LP(-1, -2))

        def gap_lp(first, top=2):
            lp = LP(-1, -2)
            lp.setMargins(dp(12), dp(10) if first else dp(top), dp(12), 0)
            return lp

        def dim():
            body.setAlpha(1.0 if eq.is_on() else 0.45)
        refreshers.append(dim)
        dim()

        dmx = act.getResources().getDisplayMetrics()
        CW = int((_wide_px(act, 600) or int(dmx.widthPixels)) - dp(24) - dp(16))
        CH = int(dp(220))
        PL, PR, PT, PB = float(dp(40)), float(dp(18)), float(dp(34)), float(dp(26))
        chart_state = {"active": -1}
        curve_card = LL(act)
        curve_card.setOrientation(1)
        curve_card.setBackground(self._group_bg(self.c_item, True, True))
        curve_card.setPadding(dp(8), dp(8), dp(8), dp(8))
        curve_iv = _cls("android.widget.ImageView")(act)
        with tolerated():
            curve_iv.setScaleType(_cls("android.widget.ImageView$ScaleType").FIT_XY)
        curve_card.addView(curve_iv, LP(-1, CH))
        body.addView(curve_card, gap_lp(True))
        import math
        LO_F, HI_F = 20.0, 20000.0
        LSPAN = math.log(HI_F) - math.log(LO_F)

        def cx(hz):
            return PL + (math.log(hz) - math.log(LO_F)) / LSPAN * (CW - PL - PR)

        def cy(db):
            mid = PT + (CH - PT - PB) / 2.0
            return mid - (db / EQ_MAX_DB) * ((CH - PT - PB) / 2.0)

        def db_at(y):
            mid = PT + (CH - PT - PB) / 2.0
            v = (mid - y) / ((CH - PT - PB) / 2.0) * EQ_MAX_DB
            return round(max(EQ_MIN_DB, min(EQ_MAX_DB, v)) / EQ_STEP_DB) * EQ_STEP_DB

        def draw_curve():
            Bitmap = jclass("android.graphics.Bitmap")
            Config = jclass("android.graphics.Bitmap$Config")
            Canvas = jclass("android.graphics.Canvas")
            Paint = jclass("android.graphics.Paint")
            Path = jclass("android.graphics.Path")
            Style = jclass("android.graphics.Paint$Style")
            Align = jclass("android.graphics.Paint$Align")
            RectF = jclass("android.graphics.RectF")
            on = eq.is_on()
            bmp = Bitmap.createBitmap(CW, CH, Config.ARGB_8888)
            cv = Canvas(bmp)
            gains = eq.gains()
            grid = Paint()
            grid.setAntiAlias(True)
            grid.setStrokeWidth(float(dp(1)))
            txt = Paint()
            txt.setAntiAlias(True)
            txt.setTextSize(float(dp(10)))
            txt.setColor(_ci(_mix(self.c_item, self.c_sub, 0.85)))
            txt.setTextAlign(Align.RIGHT)
            for db in (-12, -6, 0, 6, 12):
                grid.setColor(_ci(_mix(self.c_item, self.c_sub, 0.55 if db == 0 else 0.22)))
                cv.drawLine(PL, float(cy(db)), float(CW - PR), float(cy(db)), grid)
                cv.drawText(f"{db:+d}" if db else "0", PL - float(dp(6)), float(cy(db)) + float(dp(3.5)), txt)
            txt.setTextAlign(Align.CENTER)
            for hz in EQ_FREQS:
                grid.setColor(_ci(_mix(self.c_item, self.c_sub, 0.16)))
                cv.drawLine(float(cx(hz)), PT, float(cx(hz)), float(CH - PB), grid)
                cv.drawText(freq_label(hz).replace(" kHz", "k").replace(" Hz", ""), float(cx(hz)), float(CH) - float(dp(8)), txt)
            line = Path()
            fill = Path()
            n = 120
            zero = float(cy(0))
            for i in range(n + 1):
                hz = LO_F * math.exp(LSPAN * i / n)
                x, y = float(cx(hz)), float(cy(curve_at(gains, hz)))
                if i == 0:
                    line.moveTo(x, y)
                    fill.moveTo(x, zero)
                    fill.lineTo(x, y)
                else:
                    line.lineTo(x, y)
                    fill.lineTo(x, y)
            fill.lineTo(float(CW - PR), zero)
            fill.close()
            accent = self.c_accent if on else _mix(self.c_item, self.c_sub, 0.6)
            fp = Paint()
            fp.setAntiAlias(True)
            fp.setStyle(Style.FILL)
            fp.setColor(_ci(_mix(self.c_item, accent, 0.30)))
            cv.drawPath(fill, fp)
            lp_ = Paint()
            lp_.setAntiAlias(True)
            lp_.setStyle(Style.STROKE)
            lp_.setStrokeWidth(float(dp(2.5)))
            lp_.setColor(_ci(accent))
            cv.drawPath(line, lp_)
            act_i = chart_state["active"]
            halo = Paint()
            halo.setAntiAlias(True)
            halo.setColor(_ci(_mix(self.c_item, accent, 0.35)))
            ring = Paint()
            ring.setAntiAlias(True)
            ring.setColor(_ci(accent))
            core = Paint()
            core.setAntiAlias(True)
            core.setColor(_ci(self.c_item))
            for i, (hz, g) in enumerate(zip(EQ_FREQS, gains)):
                x, y = float(cx(hz)), float(cy(g))
                if i == act_i:
                    cv.drawCircle(x, y, float(dp(20)), halo)
                cv.drawCircle(x, y, float(dp(9)), ring)
                cv.drawCircle(x, y, float(dp(5)), core if i != act_i else ring)
            if act_i >= 0:
                label = _db(gains[act_i])
                bt = Paint()
                bt.setAntiAlias(True)
                bt.setTextSize(float(dp(12)))
                bt.setFakeBoldText(True)
                bt.setTextAlign(Align.CENTER)
                bt.setColor(_ci(self.c_bg))
                tw = float(bt.measureText(label))
                x = float(cx(EQ_FREQS[act_i]))
                y = max(float(cy(gains[act_i])) - float(dp(30)), float(dp(4)) + float(dp(12)))
                bx = max(float(dp(4)) + (tw + float(dp(16))) / 2, min(float(CW) - float(dp(4)) - (tw + float(dp(16))) / 2, x))
                rect = RectF(bx - tw / 2 - float(dp(8)), y - float(dp(14)), bx + tw / 2 + float(dp(8)), y + float(dp(6)))
                bp = Paint()
                bp.setAntiAlias(True)
                bp.setColor(_ci(accent))
                cv.drawRoundRect(rect, float(dp(10)), float(dp(10)), bp)
                cv.drawText(label, bx, y, bt)
            curve_iv.setImageBitmap(bmp)
        refreshers.append(lambda: draw_curve())
        with tolerated():
            draw_curve()

        def chart_touch(v, e):
            a = int(e.getActionMasked())
            x, y = float(e.getX()), float(e.getY())
            if a == 0:
                best = min(range(len(EQ_FREQS)), key=lambda i: abs(cx(EQ_FREQS[i]) - x))
                chart_state["active"] = best
                with tolerated():
                    v.getParent().requestDisallowInterceptTouchEvent(True)
            elif a not in (1, 2, 3):
                return False
            i = chart_state["active"]
            if i < 0:
                return False
            if a in (0, 2):
                eq.set_band(i, db_at(y))
                if not eq.is_on():
                    eq.set_on(True)
                sync_fx()
                with tolerated():
                    draw_curve()
                    dim()
            else:
                chart_state["active"] = -1
                sync()
            return True
        curve_iv.setOnTouchListener(self.Touch(chart_touch))

        pres_lbl = self._text(strings("eq_presets"), 13, self.c_sub, bold=True)
        pres_lbl.setPadding(dp(28), 0, dp(28), 0)
        pl = LP(-1, -2)
        pl.setMargins(0, dp(14), 0, dp(6))
        body.addView(pres_lbl, pl)
        hs = HSV(act)
        hs.setHorizontalScrollBarEnabled(False)
        strip = LL(act)
        strip.setOrientation(0)
        strip.setPadding(dp(12), 0, dp(12), 0)
        chip_paints = []

        def pick_preset(key):
            g = preset_gains(key)
            if g is None:
                u = eq.user_preset(key)
                g = u["gains"] if u is not None else None
            if g is None:
                return
            eq.set_gains(g, key)
            if not eq.is_on():
                eq.set_on(True)
            sync_fx()
            sync()

        def add_chip(key, label):
            c = LL(act)
            c.setGravity(17)
            c.setPadding(dp(14), dp(7), dp(14), dp(7))
            tv = self._text(label, 13, self.c_text, bold=True, single=True)
            c.addView(tv, LP(-2, -2))
            def paint(c=c, tv=tv, key=key):
                on = eq.is_on() and eq.preset() == key
                cg = GD()
                cg.setCornerRadius(float(dp(16)))
                cg.setColor(_mix(self.c_bg, self.c_accent, 0.30 if on else 0.10))
                c.setBackground(cg)
                tv.setTextColor(self.c_accent if on else self.c_text)
            c.setOnClickListener(self.Click(lambda v, key=key: pick_preset(key)))
            self._press_fx(c)
            chip_paints.append(paint)
            paint()
            lp = LP(-2, -2)
            lp.setMargins(dp(4), 0, dp(4), 0)
            strip.addView(c, lp)

        def build_strip():
            strip.removeAllViews()
            del chip_paints[:]
            for u in eq.user_presets():
                add_chip("u:" + u["id"], u["name"])
            for key, sk, _g in EQ_PRESETS:
                add_chip(key, strings(sk))
        build_strip()
        refreshers.append(lambda: [fn() for fn in list(chip_paints)])
        hs.addView(strip)
        body.addView(hs, LP(-1, -2))

        fx = (("eq_bass", strings("bass_boost")), ("eq_virt", strings("surround")), ("eq_loud", strings("loudness")))
        Bitmap = jclass("android.graphics.Bitmap")
        Config = jclass("android.graphics.Bitmap$Config")
        Canvas = jclass("android.graphics.Canvas")
        Paint = jclass("android.graphics.Paint")
        Style = jclass("android.graphics.Paint$Style")
        Cap = jclass("android.graphics.Paint$Cap")
        Align = jclass("android.graphics.Paint$Align")
        RectF = jclass("android.graphics.RectF")
        KS = 240

        def knob_bitmap(lv):
            bmp = Bitmap.createBitmap(KS, KS, Config.ARGB_8888)
            cv = Canvas(bmp)
            w = 18.0
            m = w / 2 + 8.0
            box = RectF(m, m, KS - m, KS - m)
            tr = Paint()
            tr.setAntiAlias(True)
            tr.setStyle(Style.STROKE)
            tr.setStrokeWidth(w)
            tr.setStrokeCap(Cap.ROUND)
            tr.setColor(_ci(_mix(self.c_item, self.c_sub, 0.35)))
            cv.drawArc(box, 135.0, 270.0, False, tr)
            if lv > 0:
                pr = Paint()
                pr.setAntiAlias(True)
                pr.setStyle(Style.STROKE)
                pr.setStrokeWidth(w)
                pr.setStrokeCap(Cap.ROUND)
                pr.setColor(_ci(self.c_accent))
                cv.drawArc(box, 135.0, 270.0 * lv / 100.0, False, pr)
            tp = Paint()
            tp.setAntiAlias(True)
            tp.setTextAlign(Align.CENTER)
            tp.setFakeBoldText(True)
            tp.setTextSize(64.0)
            tp.setColor(_ci(self.c_accent if lv > 0 else self.c_sub))
            cv.drawText(str(lv), KS / 2.0, KS / 2.0 + 22.0, tp)
            return bmp

        krow = LL(act)
        krow.setOrientation(0)
        krow.setPadding(dp(8), dp(10), dp(8), dp(8))
        krow.setBackground(self._group_bg(self.c_item, True, True))
        for key, label in fx:
            cell = LL(act)
            cell.setOrientation(1)
            cell.setGravity(1)
            iv = _cls("android.widget.ImageView")(act)
            with tolerated():
                iv.setScaleType(_cls("android.widget.ImageView$ScaleType").FIT_CENTER)
            cell.addView(iv, LP(dp(68), dp(68)))
            cell.addView(self._text(label, 13, self.c_text, gravity=17, single=True), LP(-2, -2))
            def paint(iv=iv, key=key):
                iv.setImageBitmap(knob_bitmap(eq.level(key)))
            st = {"y": 0.0, "v": 0}
            def touch(v, e, key=key, st=st, paint=paint):
                a = int(e.getActionMasked())
                if a == 0:
                    st["y"], st["v"] = float(e.getRawY()), eq.level(key)
                    with tolerated():
                        v.getParent().requestDisallowInterceptTouchEvent(True)
                    return True
                if a == 2:
                    nv = int(round(st["v"] + (st["y"] - float(e.getRawY())) / float(dp(140)) * 100.0))
                    nv = max(0, min(100, nv))
                    if nv != eq.level(key):
                        eq.set_level(key, nv)
                        if not eq.is_on():
                            eq.set_on(True)
                        sync_fx()
                        paint()
                        with tolerated():
                            draw_curve()
                            dim()
                    return True
                if a in (1, 3):
                    sync()
                    return True
                return False
            iv.setOnTouchListener(self.Touch(touch))
            refreshers.append(paint)
            paint()
            kl = LP(0, -2, 1.0)
            krow.addView(cell, kl)
        fx_lbl = self._text(strings("eq_effects"), 13, self.c_sub, bold=True)
        fx_lbl.setPadding(dp(28), 0, dp(28), 0)
        fl = LP(-1, -2)
        fl.setMargins(0, dp(16), 0, dp(6))
        body.addView(fx_lbl, fl)
        body.addView(krow, gap_lp(False, 0))

        def action_row(label, glyphs, color):
            r_ = LL(act)
            r_.setOrientation(0)
            r_.setGravity(16)
            r_.setMinimumHeight(dp(52))
            r_.setPadding(dp(16), dp(8), dp(16), dp(8))
            r_.setBackground(self._group_bg(self.c_item, True, True))
            r_.addView(self._glyph_icon(glyphs, color, pad=0), LP(dp(24), dp(24)))
            t_ = self._text(label, 16, color)
            t_.setPadding(dp(16), 0, 0, 0)
            r_.addView(t_, LP(0, -2, 1.0))
            self._press_fx(r_)
            return r_

        def next_custom_name():
            have = {u["name"].lower() for u in eq.user_presets()}
            n = 1
            while f"{strings('eq_custom')} {n}".lower() in have:
                n += 1
            return f"{strings('eq_custom')} {n}"

        def do_save_preset():
            gains = eq.gains()
            def save(text):
                if not text:
                    return
                key = eq.save_user_preset(text, gains)
                eq.set_gains(gains, key)
                if not eq.is_on():
                    eq.set_on(True)
                sync_fx()
                build_strip()
                with tolerated():
                    hs.scrollTo(0, 0)
                sync()
            self._prompt_text(strings("eq_save_preset"), next_custom_name(), strings("eq_preset_name"), save)

        def do_delete_preset():
            key = eq.preset()
            u = eq.user_preset(key) if key.startswith("u:") else None
            if u is None:
                return
            eq.delete_user_preset(key)
            build_strip()
            p._bulletin(strings("deleted_n", u["name"]))
            sync()

        sav = action_row(strings("eq_save_preset"), ("msg_add", "msg_saved", "msg_fave"), self.c_accent)
        sav.setOnClickListener(self.Click(lambda v: do_save_preset()))
        body.addView(sav, gap_lp(False, 14))
        dele = action_row(strings("eq_delete_preset"), self._DEL, red)
        dele.setOnClickListener(self.Click(lambda v: do_delete_preset()))
        body.addView(dele, gap_lp(False, 14))

        def paint_preset_rows(force=False):
            key = eq.preset()
            sav.setVisibility(0 if (force or not key) else 8)
            dele.setVisibility(0 if (force or key.startswith("u:")) else 8)
        refreshers.append(paint_preset_rows)
        paint_preset_rows()

        def do_reset():
            eq.reset()
            sync()
        rst = LL(act)
        rst.setOrientation(0)
        rst.setGravity(16)
        rst.setMinimumHeight(dp(52))
        rst.setPadding(dp(16), dp(8), dp(16), dp(8))
        rst.setBackground(self._group_bg(self.c_item, True, True))
        rst.addView(self._glyph_icon(("msg_reset", "msg_retry", "msg_refresh"), red, pad=0), LP(dp(24), dp(24)))
        rt = self._text(strings("reset_equalizer"), 16, red)
        rt.setPadding(dp(16), 0, 0, 0)
        rst.addView(rt, LP(0, -2, 1.0))
        rst.setOnClickListener(self.Click(lambda v: do_reset()))
        self._press_fx(rst)
        body.addView(rst, gap_lp(False, 14))
        refreshers.append(lambda: rst.setVisibility(8 if eq.is_default() else 0))
        rst.setVisibility(8 if eq.is_default() else 0)

        win_h = -2
        dm = act.getResources().getDisplayMetrics()
        wpx = _wide_px(act, 600)
        try:
            MS = jclass("android.view.View$MeasureSpec")
            fr = _cls("android.graphics.Rect")()
            act.getWindow().getDecorView().getWindowVisibleDisplayFrame(fr)
            avail = int(fr.height())
            if avail < dp(240):
                avail = int(dm.heightPixels)
            avail = min(avail, int(dm.heightPixels))
            width = wpx or int(dm.widthPixels)
            exact, free = MS.makeMeasureSpec(width, 1 << 30), MS.makeMeasureSpec(0, 0)
            sv.setVisibility(8)
            root.measure(exact, free)
            fixed = int(root.getMeasuredHeight())
            sv.setVisibility(0)
            paint_preset_rows(True)
            rst.setVisibility(0)
            body.measure(exact, free)
            paint_preset_rows()
            rst.setVisibility(8 if eq.is_default() else 0)
            room = max(avail - dp(32) - fixed, dp(120))
            if int(body.getMeasuredHeight()) > room:
                root.removeView(sv)
                root.addView(sv, LP(-1, 0, 1.0))
                win_h = fixed + room
        except Exception:
            win_h = -2
        dlg.setContentView(root)
        dlg.setCanceledOnTouchOutside(True)
        win = dlg.getWindow()
        if win is not None:
            win.setBackgroundDrawable(CD(0))
            win.setLayout(wpx or -1, win_h)
            win.setGravity(80)

        def sd_move(dy):
            root.setTranslationY(max(0.0, float(root.getTranslationY()) + dy))

        def sd_end(vel):
            ty, h = float(root.getTranslationY()), float(root.getHeight())
            if ty > h * 0.35 or (vel > 1200 and ty > 0):
                root.animate().translationY(h).setDuration(160).withEndAction(
             self.Run(lambda: dlg.dismiss())).start()
            else:
                root.animate().translationY(0.0).setDuration(180).start()
        def sd_skip(ev):
            rx, ry = float(ev.getRawX()), float(ev.getRawY())
            return any(_hit(v, rx, ry) for v in (curve_iv, krow))
        self._sd_skip = sd_skip
        _attach_sheet_drag(
       self, dlg, lambda: [sv], lambda: 0, lambda: True,
       lambda: float(root.getTranslationY()) > 0.5, lambda: None, sd_move, sd_end)
        dlg.show()
        with tolerated():
            win = dlg.getWindow()
            win.setLayout(wpx or -1, win_h)
            win.setGravity(80)
