from typing import Any, List, Optional, Dict
from java.util import ArrayList
from java.lang import Boolean
try:
    from java import jint, jclass, dynamic_proxy, jarray, jfloat
except Exception:
    jint = jclass = dynamic_proxy = jarray = jfloat = None
try:
    from java import jbyte
except Exception:
    jbyte = None
from base_plugin import BasePlugin, MethodHook, MenuItemData, MenuItemType
from hook_utils import find_class, get_private_field, set_private_field
from client_utils import (
 get_last_fragment,
 get_media_controller,
 )
from android_utils import run_on_ui_thread
from ui.settings import Header, Switch, Selector, Divider, EditText
try:
    from ui.settings import Text
except Exception:
    Text = None
try:
    from ui.settings import Input
except Exception:
    Input = None
from ui.bulletin import BulletinHelper
