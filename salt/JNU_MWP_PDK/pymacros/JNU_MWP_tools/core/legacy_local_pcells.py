# -*- coding: utf-8 -*-
# 创建者: Junyi Zhang
# 时间: 2026-10

"""把几何可精确匹配的旧本地 Taper／直波导关联到稳定 JNU 库。"""

import pya

from JNU_MWP_tools.core.pcell_geometry import cell_geometry_equal
from JNU_MWP_tools.core.ui_language import localize_pcell_declaration


def _family(parameters):
    if {"width1", "width2", "length", "wg_layer", "pin_layer"} <= set(parameters):
        return "Pcell_Taper"
    if {"width", "length", "wg_layer", "pin_layer"} <= set(parameters):
        return "Pcell_Straight_Waveguide"
    return None


def legacy_local_cells(layout):
    """只检查无法解析的本地声明，不替换其他器件库的代理。"""
    return [(cell, _family(cell.pcell_parameters_by_name())) for cell in layout.each_cell()
            if cell.is_proxy() and not cell.is_pcell_variant() and not cell.is_library_cell()
            and _family(cell.pcell_parameters_by_name()) is not None]


def pcell_context_key(cell):
    """按实际输入匹配代理身份，兼容旧参数中的整数／浮点数表示差异。"""
    params = dict(cell.pcell_parameters_by_name())
    family = _family(params)
    if family == "Pcell_Taper":
        for key in ("port1_extension_length", "port2_extension_length"):
            params.setdefault(key, 0.0)
        params.setdefault("devrec_layer", pya.LayerInfo(68, 0))
    derived = {"name_suffix", "points_per_90", "npoints", "Bezier_Rmax", "Bezier_Rmin", "Euler_Reff"}

    def value(item):
        return ("number", float(item)) if isinstance(item, (int, float)) else ("value", str(item))

    return family or cell.basic_name(), tuple(sorted((key, value(item)) for key, item in params.items() if key not in derived))


def prepare_pcell_recovery(layout, internal_factories=None):
    """在 Undo transaction 外预生成并逐个核对候选，不改动原实例及旧 cell。"""
    internal_factories = internal_factories or {}
    library = pya.Library.library_by_name("JNULib")
    original_indices = {cell.cell_index() for cell in layout.each_cell()}
    missing = list(legacy_local_cells(layout)) if library is not None else []
    for cell in list(layout.each_cell()):
        if (cell.is_proxy() and not cell.is_pcell_variant() and not cell.is_library_cell()
                and cell.basic_name() in internal_factories):
            missing.append((cell, cell.basic_name()))
    planned = []
    for old, family in missing:
        if old.is_empty():
            continue
        old_index, name = old.cell_index(), old.name
        if family in internal_factories:
            if layout.pcell_declaration(family) is None:
                layout.register_pcell(family, localize_pcell_declaration(internal_factories[family]()))
            candidate = layout.create_cell(family, dict(old.pcell_parameters_by_name()))
        else:
            candidate = layout.create_cell(family, "JNULib", dict(old.pcell_parameters_by_name()))
        if (candidate is None or candidate.cell_index() in original_indices
                or list(candidate.each_parent_inst())
                or any(item[1] == candidate.cell_index() for item in planned)):
            continue
        for key, item in old.properties().items():
            candidate.set_property(key, item)
        if not cell_geometry_equal(old, candidate):
            layout.delete_cell(candidate.cell_index())
            continue
        target_name = candidate.name if family in internal_factories else name
        planned.append((old_index, candidate.cell_index(), name, target_name))
    return planned


def apply_pcell_recovery(layout, planned):
    """仅重连真实 Instance 和移除旧代理，可由调用者放入单次 Undo transaction。"""
    mapping = {old_index: new_index for old_index, new_index, _old_name, _new_name in planned}
    for parent in list(layout.each_cell()):
        if parent.cell_index() in mapping:
            continue
        for instance in list(parent.each_inst()):
            if instance.cell_index in mapping:
                instance.cell_index = mapping[instance.cell_index]
    layout.delete_cells(list(mapping))
    for _old_index, new_index, _old_name, new_name in planned:
        layout.cell(new_index).name = new_name


def discard_prepared_pcells(layout, planned):
    """异常或撤销事务后只删除本次预生成且没有实例引用的候选。"""
    for _old_index, new_index, _old_name, _new_name in planned:
        if layout.is_valid_cell_index(new_index):
            cell = layout.cell(new_index)
            if not list(cell.each_parent_inst()):
                layout.delete_cell(new_index)


def restore_legacy_local_pcells(layout):
    """用于未绑定 GUI 的临时预览；当前用户 Layout 使用可撤销的事务入口。"""
    planned = prepare_pcell_recovery(layout)
    apply_pcell_recovery(layout, planned)
    return [item[2] for item in planned]
