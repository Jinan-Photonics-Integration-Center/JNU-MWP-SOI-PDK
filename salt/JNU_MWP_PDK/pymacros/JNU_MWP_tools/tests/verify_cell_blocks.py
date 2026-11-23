# -*- coding: utf-8 -*-
# 创建者: Junyi Zhang
# 时间: 2026-11
"""覆盖递归变换、重复更新、保留手绘图形及持久化后的 Block 边界。"""
from pathlib import Path
import sys,tempfile
import pya

PYMACROS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PYMACROS))
from JNU_MWP_tools.actions.cell_blocks import plan_cell_blocks, apply_cell_blocks, BLOCK_TAG

def main():
    layout = pya.Layout()
    layout.dbu = .001
    leaf = layout.create_cell("physical_leaf")
    leaf.shapes(layout.layer(1, 0)).insert(pya.Box(0, 0, 10000, 20000))
    leaf.shapes(layout.layer(68, 0)).insert(pya.Box(-100000, -100000, 100000, 100000))
    leaf.shapes(layout.layer(10, 0)).insert(pya.Text("label", pya.Trans(999999, 0)))
    child = layout.create_cell("structure")
    child.insert(pya.CellInstArray(leaf.cell_index(), pya.Trans(1, False, 50000, 10000)))
    child.shapes(layout.layer(12, 0)).insert(pya.Box(-20000, -10000, -10000, 10000))
    li = layout.layer(202, 0)
    manual = pya.Box(-900000, -900000, -800000, -800000)
    child.shapes(li).insert(manual)
    plan = plan_cell_blocks(layout, [child, child], 2)
    assert len(plan["blocks"]) == 1
    expected = pya.Box(-22000, -12000, 52000, 22000)
    assert plan["blocks"][0]["bbox"] == expected, plan["blocks"][0]["bbox"]
    apply_cell_blocks(layout, plan)
    # 重复执行不会把旧 Block 或识别区计入，也不会累加留边。
    apply_cell_blocks(layout, plan_cell_blocks(layout, [child], 2))
    assert child.shapes(li).size() == 2
    assert any(s.box == manual and s.property(124) is None for s in child.shapes(li).each())
    empty = layout.create_cell("empty")
    assert not plan_cell_blocks(layout, [empty])["blocks"]
    try:
        plan_cell_blocks(layout, [child], -1)
        raise AssertionError("负留边未被拒绝")
    except ValueError:
        pass
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "cell_blocks_v1.gds"
        layout.write(str(path))
        reopened = pya.Layout()
        reopened.read(str(path))
        cell = reopened.cell("structure")
        blocks = [s.box for s in cell.shapes(reopened.layer(202, 0)).each() if s.property(124) == BLOCK_TAG]
        assert blocks == [expected], blocks
    print("PASS: transformed process bounds, annotation exclusion, idempotent margin, manual-block preservation, GDS reread", flush=True)

main()
