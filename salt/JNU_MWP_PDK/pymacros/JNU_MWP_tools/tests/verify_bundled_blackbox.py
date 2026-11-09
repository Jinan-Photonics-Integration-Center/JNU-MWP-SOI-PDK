# -*- coding: utf-8 -*-
# 创建者: Junyi Zhang
# 时间: 2026-11

"""验证仓库自带黑盒数据可独立加载，且没有泄露内部物理版图。"""

from collections import Counter
from pathlib import Path
import sys

import pya


PYMACROS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PYMACROS))
import JNU_MWP_blackbox as blackbox
from JNU_MWP_tools.release.blackbox_validation import verify_port_straights


# 白盒里确有标注的器件；没有源标注的器件不推断偏振和比例。
PORT_ANNOTATIONS = {
    "1310_90/10_splitter": {"100%": "opt1", "10%": "opt2", "90%": "opt3"},
    "1310_PBS": {"In": "opt1", "TE": "opt3", "TM": "opt4"},
    "1310_PR": {"In": "opt1", "out": "opt2"},
    "1310_TE_polarizer": {"In": "opt1", "Out": "opt2"},
    "1310_TM_polarizer": {"In": "opt1", "Out": "opt2"},
    "1550_90/10_splitter": {"In": "opt1", "10%": "opt2", "90%": "opt3"},
    "1550_95/5_splitter": {"In": "opt1", "5%": "opt2", "95%": "opt3"},
    "1550_PBS": {"TE": "opt1", "TM": "opt2", "In": "opt3"},
    "1550_TE_polarizer": {"TE+TM": "opt1", "TE": "opt2"},
}


def _port_annotation_texts(cell):
    layout = cell.layout()
    return [s.text for s in cell.shapes(layout.layer(10, 0)).each()
            if s.is_text() and s.text.string != cell.name + " (black box)"]


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
        labels = _port_annotation_texts(disk.top_cell())
        expected = PORT_ANNOTATIONS.get(name, {})
        assert Counter(t.string for t in labels) == Counter(expected.keys()), name
        pins = {s.text.string: s.text for s in disk.top_cell().shapes(disk.layer(1, 10)).each()
                if s.is_text()}
        for label in labels:
            pin = pins[expected[label.string]]
            assert label.y == pin.y and abs((pin.x - label.x) * disk.dbu - 0.25) <= disk.dbu, name
            assert label.halign == pya.Text.HAlignRight, name
        key = lambda t: (t.string, str(t.trans), t.size, t.halign, t.valign)
        assert Counter(map(key, labels)) == Counter(map(key, _port_annotation_texts(registered))), name
        assert Counter(map(key, labels)) == Counter(map(key, _port_annotation_texts(instance_cell))), name
        for layer in ((1, 0), (1, 10), (68, 0), (998, 0), (10, 0)):
            disk_region = pya.Region(disk.top_cell().begin_shapes_rec(disk.layer(*layer)))
            placed_region = pya.Region(instance_cell.begin_shapes_rec(target.layer(*layer)))
            assert (disk_region ^ placed_region).is_empty(), (name, layer)
    print("PASS: %d blackboxes load and instantiate; Si contains only 0.2 um port straights touching the BlackBox body." % len(names))


if __name__ == "__main__":
    main()
