# -*- coding: utf-8 -*-
# 创建者: Junyi Zhang
# 时间: 2026-11

"""在完整结构本地坐标中生成可重复更新的覆盖矩形，不保存版图文件。"""

import math
import pya

from JNU_MWP_tools.core.common import _active_context, _main_window

BLOCK_LAYER = pya.LayerInfo(202, 0)
BLOCK_PROPERTY = 124
BLOCK_TAG = "JNU_MWP_cell_block_v1"
# 工艺实体决定覆盖范围；端口、识别区、文字层、旧 Block 不参与递归边界。
PHYSICAL_LAYERS = {(1, 0), (1, 5), (2, 0), (4, 0), (6, 0), (11, 0),
                   (12, 0), (13, 0), (40, 0), (201, 0), (210, 0), (998, 0)}


def plan_cell_blocks(layout, cells, margin_um=0.0):
    """只读规划；共享子结构使用缓存，旧 Block 和 Text 不会扩大边界。"""
    margin_um = float(margin_um)
    if not math.isfinite(margin_um) or margin_um < 0:
        raise ValueError("Block 外扩距离必须为有限非负数。")
    margin = math.ceil(margin_um / layout.dbu)
    layers = [li for li in layout.layer_indexes()
              if (layout.get_info(li).layer, layout.get_info(li).datatype) in PHYSICAL_LAYERS]
    cache = {}

    def physical_bbox(cell):
        key = cell.cell_index()
        if key in cache:
            return cache[key]
        box = pya.Box()
        for li in layers:
            for shape in cell.shapes(li).each():
                if not shape.is_text():
                    box += shape.bbox()
        for instance in cell.each_inst():
            child = physical_bbox(instance.cell)
            if child.empty():
                continue
            for transform in instance.cell_inst.each_cplx_trans():
                box += child.transformed(transform)
        cache[key] = box
        return box

    plan, skipped, seen = [], [], set()
    for cell in cells:
        if cell.cell_index() in seen:
            continue
        seen.add(cell.cell_index())
        if cell.is_library_cell() or cell.is_pcell_variant():
            skipped.append((cell.name, "库单元或参数化单元"))
            continue
        box = physical_bbox(cell)
        if box.empty():
            skipped.append((cell.name, "没有工艺实体"))
            continue
        plan.append({"cell": cell, "bbox": box.enlarged(margin), "physical_bbox": box.dup()})
    return {"blocks": plan, "skipped": skipped, "margin_um": margin_um}


def apply_cell_blocks(layout, plan):
    """仅替换本工具带标记的矩形，保留用户自行绘制的 202/0 图形。"""
    li = layout.layer(BLOCK_LAYER)
    result = []
    for row in plan["blocks"]:
        cell = row["cell"]
        for shape in list(cell.shapes(li).each()):
            if shape.property(BLOCK_PROPERTY) == BLOCK_TAG:
                shape.delete()
        shape = cell.shapes(li).insert(row["bbox"])
        shape.set_property(BLOCK_PROPERTY, BLOCK_TAG)
        result.append({"cell": cell.name, "bbox": row["bbox"].to_s()})
    return result


def generate_cell_blocks():
    """菜单入口：当前结构、所选实例或当前 cell 的直接子结构。"""
    try:
        view, layout, current = _active_context()
        dialog = pya.QDialog(_main_window())
        dialog.setWindowTitle("生成单元覆盖 Block / Generate Cell Blocks")
        form = pya.QVBoxLayout(dialog)
        form.addWidget(pya.QLabel("图层 202/0；覆盖工艺实体，不修改器件和走线。", dialog))
        scope = pya.QComboBox(dialog)
        scope.addItems(["当前 cell / Current cell", "所选实例对应 cell / Selected cells",
                        "全部直接子 cell / Direct child cells"])
        form.addWidget(scope)
        form.addWidget(pya.QLabel("向外留边（µm）：", dialog))
        margin = pya.QDoubleSpinBox(dialog)
        margin.setRange(0, 1000000)
        margin.setDecimals(3)
        margin.setValue(0)
        form.addWidget(margin)
        buttons = pya.QDialogButtonBox(pya.Qt.Horizontal, dialog)
        buttons.setStandardButtons(pya.QDialogButtonBox.Ok | pya.QDialogButtonBox.Cancel)
        buttons.accepted(dialog.accept)
        buttons.rejected(dialog.reject)
        form.addWidget(buttons)
        if dialog.exec_() == 0:
            return
        choice = scope.currentIndex
        if choice == 0:
            cells = [current]
        elif choice == 1:
            cells = [obj.inst().cell for obj in view.object_selection if obj.is_cell_inst()]
            if not cells:
                raise ValueError("请先选中至少一个完整结构实例。")
        else:
            cells = [instance.cell for instance in current.each_inst()]
        plan = plan_cell_blocks(layout, cells, margin.value)
        if not plan["blocks"]:
            raise ValueError("所选范围没有可写且含工艺实体的普通 cell。")
        layout.layer(BLOCK_LAYER)
        view.add_missing_layers()
        view.transaction("生成 Cell 覆盖 Block")
        try:
            result = apply_cell_blocks(layout, plan)
        finally:
            view.commit()
        message = "已生成或更新 %d 个覆盖 Block（202/0）。" % len(result)
        if plan["skipped"]:
            message += "\n跳过 %d 个库、PCell 或空单元。" % len(plan["skipped"])
        pya.MessageBox.info("Cell Blocks", message, pya.MessageBox.Ok)
    except Exception as error:
        pya.MessageBox.warning("Cell Blocks", str(error), pya.MessageBox.Ok)
