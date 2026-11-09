# -*- coding: utf-8 -*-
# 时间: 2026-11

"""记住 JNU Taper 最后一次确认的参数。"""

import json
import math
import os
from pathlib import Path
import tempfile

import pya

LIBRARY_NAME = "JNULib"
PCELL_NAME = "Pcell_Taper"
_TOOL_LIBRARY = "edit-inst-lib-name"
_TOOL_CELL = "edit-inst-cell-name"
_TOOL_PARAMETERS = "edit-inst-pcell-parameters"
DIMENSION_LIMITS = {
    "width1": 0.001, "width2": 0.001, "length": 0.1,
    "port1_extension_length": 0.0, "port2_extension_length": 0.0,
}
LAYER_CHOICES = {
    "wg_layer": ("1/0", "1/99"), "pin_layer": ("1/10",), "devrec_layer": ("68/0",),
}
_hooks = None
_factory = None
_refresh_timer = None
_pending = None
_revision = 0


def _path():
    return Path(pya.Application.instance().application_data_path()) / "jnu_taper_defaults.json"


def normalize(values):
    """筛除无效值，尺寸下限与 Taper 几何校验保持一致。"""
    result = {}
    for key, minimum in DIMENSION_LIMITS.items():
        try:
            value = float(values[key])
            if math.isfinite(value):
                result[key] = max(value, minimum)
        except (KeyError, TypeError, ValueError, OverflowError):
            pass
    for key, choices in LAYER_CHOICES.items():
        value = values.get(key)
        if value in choices:
            result[key] = value
    return result


def load():
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return normalize(data) if isinstance(data, dict) else {}
    except (AttributeError, OSError, ValueError):
        return {}


def remember(values):
    """仅由已确认的界面操作调用，不在生成或重读 PCell 时写配置。"""
    global _revision
    values = normalize(values)
    if set(values) != DIMENSION_LIMITS.keys() | LAYER_CHOICES.keys() or values == load():
        return
    path = _path()
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".jnu_taper_", suffix=".tmp",
            mode="w", encoding="utf-8", delete=False,
        ) as stream:
            temporary = stream.name
            json.dump(values, stream, indent=2, allow_nan=False)
        os.replace(temporary, path)
        temporary = None
    except OSError as error:
        print("JNU Taper: 无法保存参数：%s" % error)
        return
    finally:
        if temporary is not None:
            try:
                os.remove(temporary)
            except OSError:
                pass

    # KLayout 缓存参数声明；以同一名称刷新 Taper，保留声明 ID 和已有变体。
    library = pya.Library.library_by_name(LIBRARY_NAME)
    if library is not None:
        from JNU_MWP_pcells.taper import Taper
        from .ui_language import localize_pcell_declaration

        library.layout().register_pcell(PCELL_NAME, localize_pcell_declaration(Taper(use_last_parameters=True)))
    _revision += 1
    if _refresh_timer is not None:
        # 等原生放置或属性事务结束后，再刷新实例工具。
        _refresh_timer.start(0)


def _uses_taper(view):
    return (view.get_config(_TOOL_LIBRARY) == LIBRARY_NAME
            and view.get_config(_TOOL_CELL) == PCELL_NAME)


def _reset_tool_parameters(view):
    # 原生配置的 "!" 表示 PCell，且没有覆盖参数。
    view.set_config(_TOOL_PARAMETERS, "!")
    view.commit_config()


def _refresh_instance_tool():
    # Instance 工具可在声明之外单独缓存参数，需同步清除当前 Taper 的覆盖值。
    window = pya.Application.instance().main_window()
    for index in range(window.views()):
        view = window.view(index)
        if _uses_taper(view):
            _reset_tool_parameters(view)


def stage_property_edit(values):
    """原生属性窗口确认时保存；取消时丢弃暂存值。"""
    global _pending
    dialog = pya.QApplication.activeWindow
    if dialog is None or dialog.objectName != "properties_dialog" or not hasattr(dialog, "accepted"):
        return
    if _pending is None or _pending[0] != dialog:
        def accept():
            if _pending is not None and _pending[0] == dialog:
                remember(_pending[1])

        def finish(*_):
            global _pending
            if _pending is not None and _pending[0] == dialog:
                _pending = None

        dialog.accepted(accept)
        dialog.finished(finish)
        dialog.destroyed(finish)
    _pending = (dialog, normalize(values))


def install():
    """监听原生实例放置的提交事件和 Instance 工具的器件切换。"""
    global _hooks, _factory, _refresh_timer
    if _hooks is not None or not hasattr(pya, "EditorHooks") or not hasattr(pya, "PluginFactory"):
        return
    application = getattr(pya, "Application", None)
    app = application.instance() if application is not None else None
    if app is None or app.main_window() is None:
        return
    _refresh_timer = pya.QTimer()
    _refresh_timer.setSingleShot(True)
    _refresh_timer.timeout(_refresh_instance_tool)

    class TaperPlacementHooks(pya.EditorHooks):
        def begin_new_instances(self):
            self.values = None

        def create_instance(self, instance, _view_trans):
            cell = instance.cell
            if not cell.is_library_cell() or not cell.is_pcell_variant():
                return
            library = cell.library()
            if library is not None and library.name() == LIBRARY_NAME and cell.pcell_declaration().name() == PCELL_NAME:
                self.values = cell.pcell_parameters_by_name()

        def commit_instances(self):
            if getattr(self, "values", None):
                remember(self.values)

    _hooks = TaperPlacementHooks()
    _hooks.register("JNU_Taper_Last_Parameters")

    class TaperToolWatcher(pya.Plugin):
        """切回 Taper 时清除早于最近一次确认的缓存。"""

        def __init__(self, view):
            super().__init__()
            self.view = view
            self.selection = {}
            self.parameters = ""
            self.taper_cache = None
            self.timer = pya.QTimer()
            self.timer.setSingleShot(True)
            self.timer.timeout(self.refresh)

        def configure(self, name, value):
            if name == _TOOL_PARAMETERS:
                self.parameters = value.lstrip("!")
            elif name in (_TOOL_CELL, _TOOL_LIBRARY) and self.selection.get(name) != value:
                before = self.is_taper()
                self.selection[name] = value
                if before and not self.is_taper():
                    self.taper_cache = (self.parameters, _revision)
                elif not before and self.is_taper() and self.taper_cache is not None:
                    self.timer.start(0)
            return False

        def is_taper(self):
            return self.selection.get(_TOOL_LIBRARY) == LIBRARY_NAME and self.selection.get(_TOOL_CELL) == PCELL_NAME

        def refresh(self):
            if self.taper_cache is None or self._destroyed() or self.view._destroyed() or not _uses_taper(self.view):
                return
            cached, revision = self.taper_cache
            self.taper_cache = None
            # 只清除切走时记录的原值；保留本次选择明确传入的新参数。
            if cached and revision != _revision and self.view.get_config(_TOOL_PARAMETERS).lstrip("!") == cached:
                _reset_tool_parameters(self.view)

    class TaperToolWatcherFactory(pya.PluginFactory):
        def create_plugin(self, _manager, _root, view):
            return TaperToolWatcher(view)

    _factory = TaperToolWatcherFactory()
    _factory.register(-1, "JNU_Taper_Instance_Parameters", "")


def uninstall():
    """PDK 热重载前释放旧的界面监听器。"""
    global _hooks, _factory, _refresh_timer, _pending
    if _refresh_timer is not None:
        _refresh_timer.stop()
        _refresh_timer = None
    for handler in (_factory, _hooks):
        if handler is not None and not handler._destroyed():
            handler._destroy()
    _factory = _hooks = _pending = None
