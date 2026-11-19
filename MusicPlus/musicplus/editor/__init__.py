from .core import _QueueEditorCore
from .library_nav import _QueueEditorLibraryNav
from .library_views import _QueueEditorLibraryViews
from .library_ext import _QueueEditorLibraryExt
from .lyrics_scroll import _QueueEditorLyricsScroll
from .header_select import _QueueEditorHeaderSelect
from .playback_menus import _QueueEditorPlaybackMenus
from .tinting import _QueueEditorTinting


class _QueueEditor(
    _QueueEditorTinting,
    _QueueEditorPlaybackMenus,
    _QueueEditorHeaderSelect,
    _QueueEditorLyricsScroll,
    _QueueEditorLibraryExt,
    _QueueEditorLibraryViews,
    _QueueEditorLibraryNav,
    _QueueEditorCore,
):
    pass
