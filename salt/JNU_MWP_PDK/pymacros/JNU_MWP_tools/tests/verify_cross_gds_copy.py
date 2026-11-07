# -*- coding: utf-8 -*-
# 创建者: Junyi Zhang
# 时间: 2026-10

"""实际经过 GUI 深复制粘贴，验证上下文式旧波导和库 PCell 不变空。"""

from collections import Counter
from pathlib import Path
import sys
import tempfile

import pya

PYMACROS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PYMACROS))

from JNU_MWP_tools.core import internal_waveguide_registry as registry
from JNU_MWP_tools.core.pcell_geometry import layout_geometry_equal, cell_geometry_equal
from JNU_MWP_tools.release.repair_cross_gds_layout import repair_file


def _value(obj, name):
    value = getattr(obj, name)
    return value() if callable(value) else value


def _flush():
    dialog = pya.QDialog()
    timer = pya.QTimer(dialog)
    timer.setSingleShot(True)
    timer.timeout(dialog.accept)
    timer.start(30)
    dialog.exec_()


def _fixture(path):
    from JNU_MWP_pcells.taper import Taper
    from JNU_MWP_pcells.straight_waveguide import StraightWaveguide

    layout = pya.Layout()
    layout.dbu = 0.001
    registry.ensure_internal_waveguide_pcells(layout)
    waveguide = layout.create_cell("Waveguide", {
        "path": pya.DPath([pya.DPoint(0, 0), pya.DPoint(80, 0), pya.DPoint(80, 80)], 0.5),
        "width": 0.5, "radius": 20.0, "bend_type": "Circular",
    })
    waveguide.name = "RENAMED_LEGACY_ROUTE"
    for key in list(waveguide.properties()):
        waveguide.delete_property(key)
    layout.register_pcell("OLD_LOCAL_TAPER", Taper())
    taper = layout.create_cell("OLD_LOCAL_TAPER", {"length": 20.0, "width1": 0.5, "width2": 2.0})
    taper.set_property("user_note", "keep this cell property")
    layout.register_pcell("OLD_LOCAL_STRAIGHT", StraightWaveguide())
    straight = layout.create_cell("OLD_LOCAL_STRAIGHT", {"length": 50.0, "width": 0.5})
    class Unavailable(pya.PCellDeclarationHelper):
        def __init__(self):
            super().__init__()
            self.param("size", self.TypeInt, "Size", default=2000)

        def produce_impl(self):
            self.cell.shapes(self.layout.layer(1, 0)).insert(pya.Box(0, 0, self.size, self.size))

    layout.register_pcell("UNAVAILABLE_LOCAL_CELL", Unavailable())
    unavailable = layout.create_cell("UNAVAILABLE_LOCAL_CELL", {})
    branch = layout.create_cell("LEGACY_COPY_BRANCH")
    for index, cell in enumerate((waveguide, taper, straight)):
        instance = branch.insert(pya.CellInstArray(cell.cell_index(), pya.Trans(index * 100000, 0)))
        instance.set_property("design_tag", index)
    top = layout.create_cell("LEGACY_COPY_TOP")
    top.insert(pya.CellInstArray(branch.cell_index(), pya.Trans()))
    top.insert(pya.CellInstArray(unavailable.cell_index(), pya.Trans(300000, 0)))
    layout.write(str(path))


def _parameter_key(cell):
    return (cell.basic_name(), tuple(sorted((key, str(value)) for key, value in cell.pcell_parameters_by_name().items()
                                           if key != "name_suffix")))


def verify_clipboard_file(path, copied_output=None):
    """原生复制整个层级到全新 Layout，逐 cell 核对图形、层级和参数。"""
    window = pya.Application.instance().main_window()
    registry.install_internal_waveguide_registration(window)
    source_cv = window.load_layout(str(path), 1)
    _flush()
    source = source_cv.layout()
    assert not any(cell.is_cold_proxy() for cell in source.each_cell())
    top = source.top_cell()
    holder = source.create_cell("__CLIPBOARD_SOURCE_HOLDER")
    instance = holder.insert(pya.CellInstArray(top.cell_index(), pya.Trans()))
    source_cv.cell = holder
    view = window.current_view()
    selected = pya.ObjectInstPath()
    selected.top = holder.cell_index()
    selected.cv_index = _value(view, "active_cellview_index")
    selected.append_path(pya.InstElement(instance))
    view.object_selection = [selected]
    errors = []

    def accept_deep_copy():
        dialog = pya.QApplication.activeModalWidget()
        if dialog is None:
            return
        if str(dialog.windowTitle) != "Copy Options":
            errors.append(str(dialog.windowTitle))
            dialog.close()
            return

        def children(obj):
            return [obj] + [descendant for child in obj.children() for descendant in children(child)]

        next(child for child in children(dialog) if hasattr(child, "text")
             and str(child.text).startswith("Deep copy")).setChecked(True)
        dialog.accept()

    timer = pya.QTimer(window)
    timer.timeout(accept_deep_copy)
    timer.start(10)
    try:
        window.cm_copy()
        target_cv = window.create_layout(1)
        target = target_cv.layout()
        target.dbu = source.dbu
        # 不等待轮询 timer，空版图必须在创建返回时就已经可以接受粘贴。
        assert target.pcell_declaration("Waveguide") is not None
        target_top = target.create_cell("CLIPBOARD_TARGET")
        target_cv.cell = target_top
        window.cm_paste()
    finally:
        timer.stop()
        timer.deleteLater()
    assert not errors, errors
    assert len(list(target_top.each_inst())) == 1
    assert not any(cell.is_empty() or cell.is_cold_proxy() for cell in target.each_cell())
    names = {holder.name: target_top.name}
    variants = {_parameter_key(cell): cell for cell in target.each_cell() if cell.is_pcell_variant()}
    for cell in source.each_cell():
        if cell.is_pcell_variant():
            matched = variants.get(_parameter_key(cell))
            assert matched is not None, cell.name
            names[cell.name] = matched.name
    assert layout_geometry_equal(source, target, names)
    if copied_output:
        options = pya.SaveLayoutOptions()
        options.set_format_from_filename(str(copied_output))
        options.gds2_write_cell_properties = True
        target.write(str(copied_output), options)
        saved = pya.Layout()
        registry.ensure_internal_waveguide_pcells(saved)
        saved.read(str(copied_output))
        assert layout_geometry_equal(target, saved)
        assert not any(cell.is_cold_proxy() for cell in saved.each_cell())
    return {"source_cells": source.cells() - 1, "copied_cells": target.cells() - 1,
            "empty_cells": 0, "cold_proxies": 0, "all_geometry_and_hierarchy_equal": True,
            "pcells": dict(Counter(cell.basic_name() for cell in target.each_cell() if cell.is_pcell_variant()))}


def _select_tree_cell(window, view, name):
    """选择真正的 Cells 树节点，select_cell 只改变编辑 cell，不会选中树节点。"""
    dock = window.findChild("hp_dock_widget")
    if dock is not None:
        dock.show()
        dock.raise_()
    def visit(widget):
        if (widget.__class__.__name__.startswith("QTreeView") and str(widget.objectName) == "tree"
                and widget.isVisibleTo(window)):
            model = _value(widget, "model")

            def find(parent):
                for row in range(model.rowCount(parent)):
                    index = model.index(row, 0, parent)
                    if str(model.data(index, 0)).strip() == name:
                        return index
                    nested = find(index)
                    if nested is not None:
                        return nested
                return None

            chosen = find(pya.QModelIndex())
            if chosen is not None:
                widget.setCurrentIndex(chosen)
                widget.setFocus()
                return True
        return any(visit(child) for child in widget.children())

    assert visit(window), name
    paths = view.selected_cells_paths(_value(view, "active_cellview_index"))
    assert paths and view.active_cellview().layout().cell(paths[0][-1]).name == name


def _subtree(cell):
    result, pending = {}, [cell]
    while pending:
        current = pending.pop()
        if current.cell_index() in result:
            continue
        result[current.cell_index()] = current
        pending.extend(instance.cell for instance in current.each_inst())
    return list(result.values())


def verify_original_cell_tree_copy(path, cell_name, copied_output=None, source_cellview=None):
    """直接打开原文件，Cells 树复制指定子 cell，再 File/New Layout 粘贴。"""
    path = Path(path)
    stamp = path.stat()
    window = pya.Application.instance().main_window()
    if source_cellview is None:
        registry.install_internal_waveguide_registration(window)
        cv = window.load_layout(str(path), 1)
    else:
        # 正常冷启动验收传入已经从命令行打开的源视图，不手动安装注册器或重开文件。
        cv = source_cellview
    _flush()
    source = cv.layout().cell(cell_name)
    assert source is not None
    cells = _subtree(source)
    assert not any(cell.is_empty() or cell.is_cold_proxy() for cell in cells)
    view = window.current_view()
    source_view_index = _value(window, "current_view_index")
    # 先执行 File/New Layout，再切回源文件选中子 cell，覆盖用户的实际顺序。
    target_cv = window.create_layout(1)
    target_view_index = _value(window, "current_view_index")
    target = target_cv.layout()
    target.dbu = source.layout().dbu
    target_cv.cell = target.create_cell("TOP")
    assert target.pcell_declaration("Waveguide") is not None
    window.current_view_index = source_view_index
    _select_tree_cell(window, view, cell_name)
    errors = []

    def choose_deep_copy():
        dialog = pya.QApplication.activeModalWidget()
        if dialog is None:
            return
        if str(dialog.windowTitle) != "Copy Cell Options":
            errors.append(str(dialog.windowTitle))
            dialog.close()
            return

        def children(obj):
            return [obj] + [item for child in obj.children() for item in children(child)]

        next(item for item in children(dialog) if hasattr(item, "text")
             and str(item.text).startswith("Deep copy")).setChecked(True)
        dialog.accept()

    timer = pya.QTimer(window)
    timer.timeout(choose_deep_copy)
    timer.start(10)
    try:
        window.cm_cell_copy()
        window.current_view_index = target_view_index
        window.cm_cell_paste()
    finally:
        timer.stop()
        timer.deleteLater()
    assert not errors, errors
    copied = target.cell(cell_name)
    assert copied is not None
    target_cells = _subtree(copied)
    assert len(target_cells) == len(cells)
    assert not any(cell.is_empty() or cell.is_cold_proxy() for cell in target_cells)
    variants = {_parameter_key(cell): cell for cell in target_cells if cell.is_pcell_variant()}
    names = {}
    for cell in cells:
        if cell.is_pcell_variant():
            assert _parameter_key(cell) in variants, cell.name
            names[cell.name] = variants[_parameter_key(cell)].name
    assert all(cell_geometry_equal(cell, target.cell(names.get(cell.name, cell.name)), names) for cell in cells)
    if copied_output:
        options = pya.SaveLayoutOptions()
        options.set_format_from_filename(str(copied_output))
        options.gds2_write_cell_properties = True
        target.write(str(copied_output), options)
        saved = pya.Layout()
        registry.ensure_internal_waveguide_pcells(saved)
        saved.read(str(copied_output))
        assert layout_geometry_equal(target, saved)
        assert not any(c.is_empty() or c.is_cold_proxy() for c in _subtree(saved.cell(cell_name)))
    after = path.stat()
    assert (stamp.st_size, stamp.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    return {"cell": cell_name, "source_subtree_cells": len(cells), "copied_subtree_cells": len(target_cells),
            "empty_cells": 0, "cold_proxies": 0, "all_geometry_and_hierarchy_equal": True,
            "source_file_unchanged": True, "file_new_before_copy": True,
            "pcells": dict(Counter(cell.basic_name() for cell in target_cells if cell.is_pcell_variant()))}


def _dirty_memory_and_undo(source):
    """保留真正未保存的编辑，证明修复不重读磁盘且没有清空用户的撤销历史。"""
    window = pya.Application.instance().main_window()
    cv = window.load_layout(str(source), 1)
    layout = cv.layout()
    cv.cell = layout.top_cell()
    view = window.current_view()
    cold_before = len([c for c in layout.each_cell() if c.is_cold_proxy()])
    marker_layer = layout.layer(287, 0)
    box = pya.Box(777000, 123000, 778000, 124000)
    view.transaction("User unsaved marker")
    cv.cell.shapes(marker_layer).insert(box)
    view.commit()
    assert _value(cv, "is_dirty")
    registry._recover_loaded_view(view)
    assert cv.cell.shapes(marker_layer).size() == 1
    assert len([c for c in layout.each_cell() if c.is_pcell_variant()]) == 3
    manager = _value(window, "manager")
    assert manager.has_undo()
    manager.undo()
    _flush()
    assert cv.cell.shapes(marker_layer).size() == 1
    assert len([c for c in layout.each_cell() if c.is_cold_proxy()]) == cold_before
    manager.undo()
    assert cv.cell.shapes(marker_layer).size() == 0
    manager.redo()
    assert cv.cell.shapes(marker_layer).size() == 1
    manager.redo()
    assert len([c for c in layout.each_cell() if c.is_pcell_variant()]) == 3
    print("PASS: unsaved marker preserved and repair/user edit undo-redo history retained", flush=True)


def main():
    with tempfile.TemporaryDirectory(prefix="jnu_cross_gds_") as directory:
        directory = Path(directory)
        source, repaired = directory / "legacy.gds", directory / "portable.gds"
        _fixture(source)
        raw = pya.Layout()
        raw.read(str(source))
        assert registry._has_unrecognized_waveguides(raw)
        assert not raw.cell("RENAMED_LEGACY_ROUTE").properties()
        # 缓存已被更改时不允许以当前实现覆盖，等价性检查必须能拒绝差异。
        first, second = pya.Layout(), pya.Layout()
        a, b = first.create_cell("TEST"), second.create_cell("TEST")
        a.shapes(first.layer(1, 0)).insert(pya.Box(0, 0, 100, 100))
        b.shapes(second.layer(1, 0)).insert(pya.Box(0, 0, 100, 101))
        assert not cell_geometry_equal(a, b)
        window = pya.Application.instance().main_window()
        registry.install_internal_waveguide_registration(window)
        if pya.Library.library_by_name("JNULib") is None:
            import JNULib
        cv = window.load_layout(str(source), 1)
        _flush()
        assert cv.layout().cell("RENAMED_LEGACY_ROUTE") is None
        waves = [cell for cell in cv.layout().each_cell() if cell.is_pcell_variant()]
        assert sorted(cell.basic_name() for cell in waves) == ["Pcell_Straight_Waveguide", "Pcell_Taper", "Waveguide"]
        original_copy = verify_original_cell_tree_copy(source, "LEGACY_COPY_BRANCH", directory / "original_cell_copy.gds")
        assert original_copy["source_subtree_cells"] == 4
        report = repair_file(source, repaired)
        assert report["restored_count"] == 3 and report["static_count"] == 1, report
        copied = verify_clipboard_file(repaired, directory / "copied.gds")
        assert copied["pcells"] == {"Waveguide": 1, "Pcell_Taper": 1, "Pcell_Straight_Waveguide": 1}, copied
        _dirty_memory_and_undo(source)
    print("PASS: original-file Cells-tree subcell copy, legacy recovery, exact geometry gate and reopened PCells", flush=True)


if __name__ == "__main__":
    main()
