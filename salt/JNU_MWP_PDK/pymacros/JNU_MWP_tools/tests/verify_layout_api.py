# -*- coding: utf-8 -*-
# 时间: 2026-11

"""验证脚本 API 的端口变换、路线检查与 GDS 往返。"""

from pathlib import Path
import sys
import tempfile

import pya

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from JNU_MWP_tools.core.internal_waveguide_registry import ensure_internal_waveguide_pcells
from JNU_MWP_tools.core.layout_api import Layout, catalog


def main():
    devices = catalog()["libraries"]
    assert "Pcell_Taper" in devices["JNULib"]["pcells"]
    assert len(devices["JNULib_BlackBox"]["fixed"]["1550_PBS"]) == 3
    design = Layout(top="API_TEST")
    common = {"library": "JNULib", "parameters": {"width": 0.5, "length": 30}}
    name = "Pcell_Straight_Waveguide"
    design.place("a", name, (0, 0), **common)
    design.place("b", name, (180, 60), rotation=180, **common)
    end = next(port for port in design.ports("b") if port.name == "opt2")
    assert end.xy_um == (150.0, 60.0) and end.direction_deg == 180, end
    assert len(list(design.cell.each_inst())) == 2
    try:
        design.connect(("a", "opt2"), ("b", "opt2"), via=[(35, 0), (35, 60)])
    except ValueError as error:
        assert "radius" in str(error)
    else:
        raise AssertionError("A route with insufficient bend space was accepted.")
    assert len(list(design.cell.each_inst())) == 2
    route = design.connect(("a", "opt2"), ("b", "opt2"), via=[(80, 0), (80, 60)], bend_type="Bezier")
    assert route.cell.is_pcell_variant() and route.property(126)
    si = pya.Region(design.cell.begin_shapes_rec(design.layout.layer(1, 0))).merged()
    assert si.count() == 1, "The connection must join both device end faces."
    design.place("blackbox", "1550_PBS", (0, 150), library="JNULib_BlackBox")
    assert len(design.ports("blackbox")) == 3

    with tempfile.TemporaryDirectory(prefix="jnu-layout-api-") as tmp:
        path = design.save_gds(Path(tmp) / "test.gds")
        try:
            design.save_gds(path)
        except FileExistsError:
            pass
        else:
            raise AssertionError("An existing GDS was overwritten.")
        saved = pya.Layout()
        ensure_internal_waveguide_pcells(saved)
        saved.read(str(path))
        top = saved.top_cell()
        instances = list(top.each_inst())
        assert top.name == "API_TEST" and len(instances) == 4
        assert all(not inst.cell.is_empty() for inst in instances)
        assert any(inst.cell.is_pcell_variant() and inst.property(126) for inst in instances)
        before = pya.Region(design.cell.begin_shapes_rec(design.layout.layer(1, 0)))
        after = pya.Region(top.begin_shapes_rec(saved.layer(1, 0)))
        assert (before ^ after).is_empty(), "GDS reread changed Si geometry."
    print("PASS: SOI layout API catalog, named ports, route, GDS roundtrip", flush=True)


if __name__ == "__main__":
    main()
