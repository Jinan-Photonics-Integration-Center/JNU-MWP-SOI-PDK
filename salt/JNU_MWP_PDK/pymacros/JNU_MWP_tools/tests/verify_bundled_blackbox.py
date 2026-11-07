# -*- coding: utf-8 -*-
# 创建者: Junyi Zhang
# 时间: 2026-11

"""验证仓库自带黑盒数据可独立加载，且没有泄露内部物理版图。"""

from pathlib import Path
import sys

import pya


PYMACROS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PYMACROS))
import JNU_MWP_blackbox as blackbox
from JNU_MWP_tools.release.blackbox_validation import verify_port_straights


def main():
    directory = PYMACROS / "JNU_MWP_blackbox_gds"
    files = sorted(directory.glob("*.gds"))
    assert files, "仓库未携带黑盒 GDS"
    assert Path(blackbox._active_gds_dir()).resolve() == directory.resolve()
    names = set()
    source_files = {}
    for path in files:
        layout = pya.Layout()
        layout.read(str(path))
        for top in layout.each_top_cell():
            cell = layout.cell(top) if isinstance(top, int) else top
            assert cell.name not in names, "器件名称重复：%s" % cell.name
            names.add(cell.name)
            source_files[cell.name] = path
            verify_port_straights(cell, layout)
            pins = list(cell.shapes(layout.layer(1, 10)).each())
            assert any(shape.is_path() for shape in pins), "缺少端口：%s" % cell.name
            assert any(shape.is_text() for shape in pins), "缺少端口名称：%s" % cell.name
            devrec = list(cell.shapes(layout.layer(68, 0)).each())
            assert len(devrec) == 1 and devrec[0].is_box(), cell.name
        for cell in layout.each_cell():
            for index in layout.layer_indices():
                info = layout.get_info(index)
                shapes = list(cell.shapes(index).each())
                if shapes:
                    assert (info.layer, info.datatype) in {(1, 0), (1, 10), (68, 0), (10, 0), (998, 0)}
                if cell.name not in names:
                    assert not shapes or (info.layer, info.datatype) == (10, 0)
    assert len(names) == 31, "黑盒器件数应为 31 个：%d" % len(names)
    assert {
        "1550_crossing4", "1310_500nm_TE_terminator", "1550_500nm_TE_terminator",
        "1310_Ybranch", "1550_Ybranch",
    } <= names
    assert not any(name.startswith("Pcell_") for name in names)
    assert "1550_2um_TE_terminator" in names
    assert {"1310_4x4_MMI", "1550_1x2_MMI", "1550_1x4_MMI",
            "1550_2x2_MMI_2um-InputPort_for_TE0", "1550_4x4_MMI"} <= names
    assert all("*" not in name and "×" not in name for name in names if "MMI" in name)
    assert not {"1310_TE_Terminator", "1550_TE_Terminator", "1550_2um_terminator"} & names
    assert not {"ebeam_crossing4", "ebeam_terminator_te1310", "ebeam_terminator_te1550",
                "ebeam_y_1310", "ebeam_y_1550"} & names
    library = pya.Library.library_by_name("JNULib_BlackBox")
    assert library is not None
    assert not list(library.layout().pcell_names())
    for name in names:
        registered = library.layout().cell(name)
        assert registered is not None, name
        verify_port_straights(registered, library.layout())
        target = pya.Layout()
        instance_cell = target.create_cell(name, "JNULib_BlackBox")
        assert instance_cell is not None and not instance_cell.bbox().empty(), name
        verify_port_straights(instance_cell, target)
        disk = pya.Layout()
        disk.read(str(source_files[name]))
        for layer in ((1, 0), (1, 10), (68, 0), (998, 0), (10, 0)):
            disk_region = pya.Region(disk.top_cell().begin_shapes_rec(disk.layer(*layer)))
            placed_region = pya.Region(instance_cell.begin_shapes_rec(target.layer(*layer)))
            assert (disk_region ^ placed_region).is_empty(), (name, layer)
    print("PASS: %d blackboxes load and instantiate; Si contains only 0.2 um port straights touching the BlackBox body." % len(names))


if __name__ == "__main__":
    main()
