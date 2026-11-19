from ..compat import run_on_ui_thread
from ..crossfade import _XfHook, _xf_widest
from ..equalizer import _EqEngine
from ..safe import tolerated


class _PluginEqualizer:
    def _install_equalizer(self):
        eq = _EqEngine(self)
        self._eq = eq
        m = _xf_widest("playMessage")
        if m is not None:
            r = self.hook_method(m, _XfHook(None, self._eq_after_play))
            if r:
                self._hooks.append(r)
        run_on_ui_thread(eq.sync, 600)

    def _eq_after_play(self, param):
        eq = getattr(self, "_eq", None)
        if eq is None or not eq.alive:
            return
        for delay in (0, 300, 1200):
            run_on_ui_thread(eq.sync, delay)

    def _eq_sync(self):
        eq = getattr(self, "_eq", None)
        if eq is not None:
            eq.sync()

    def _eq_teardown(self):
        eq = getattr(self, "_eq", None)
        self._eq = None
        if eq is not None:
            with tolerated():
                eq.stop()
