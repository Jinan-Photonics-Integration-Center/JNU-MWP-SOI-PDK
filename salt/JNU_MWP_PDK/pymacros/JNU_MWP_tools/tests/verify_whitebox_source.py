# -*- coding: utf-8 -*-
# 时间: 2026-11

"""隔离验证源目录优先级、启动加载及修改 GDS 后的热重载。"""

import json
import os
from pathlib import Path
import sys
import tempfile

import pya


PYMACROS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PYMACROS))
from JNU_MWP_tools.core import fixed_gds


def write_device(path, length):
    layout = pya.Layout()
    layout.dbu = 0.001
    cell = layout.create_cell("Source_Config_Probe")
    cell.shapes(layout.layer(1, 0)).insert(pya.Box(0, 0, length, 500))
    layout.write(str(path))


def main():
    previous = os.environ.get("KLAYOUT_HOME")
    try:
        with tempfile.TemporaryDirectory(prefix="jnu-whitebox-source-") as directory:
            home = Path(directory)
            os.environ["KLAYOUT_HOME"] = str(home)
            macros = home / "pymacros"
            bundled = macros / "JNU_MWP_gds"
            private = home / "jnu_private/JNU_MWP_gds"
            source = home / "editable source"
            for folder in (bundled, private, source):
                folder.mkdir(parents=True)
            assert fixed_gds.fixed_gds_directory(macros) == str(bundled)
            write_device(private / "probe.gds", 1000)
            assert fixed_gds.fixed_gds_directory(macros) == str(private)
            write_device(bundled / "probe.gds", 2000)
            assert fixed_gds.fixed_gds_directory(macros) == str(bundled)
            config = home / fixed_gds.SOURCE_CONFIG
            device_file = source / "probe.GDS"
            write_device(device_file, 10000)
            config.write_text(json.dumps({"gds_directory": str(source)}), encoding="utf-8")
            assert fixed_gds.fixed_gds_directory(macros) == str(source)
            import JNULib
            import JNULib_BlackBox
            from JNU_MWP_tools.actions.reload_pdk import reload_jnu_pdk

            assert Path(JNULib.GDS_DIR) == source
            target = pya.Layout()
            placed = target.create_cell("Source_Config_Probe", "JNULib")
            assert placed.bbox().width() == 10000
            placed_index = placed.cell_index()
            write_device(device_file, 25000)
            reload_jnu_pdk(reload_menu=False)
            import JNULib as refreshed
            assert Path(refreshed.GDS_DIR) == source
            lib = pya.Library.library_by_name("JNULib")
            assert lib.layout().cell("Source_Config_Probe").bbox().width() == 25000
            assert target.cell(placed_index).bbox().width() == 25000
            target2 = pya.Layout()
            assert target2.create_cell("Source_Config_Probe", "JNULib").bbox().width() == 25000
            for value in ('{"gds_directory":"missing"}', '[]', '{', '{}'):
                config.write_text(value, encoding="utf-8")
                assert fixed_gds.fixed_gds_directory(macros) == str(bundled)
            print("PASS: source configuration, startup, edited GDS reload and invalid-config fallback.")
    finally:
        if previous is None:
            os.environ.pop("KLAYOUT_HOME", None)
        else:
            os.environ["KLAYOUT_HOME"] = previous


if __name__ == "__main__":
    main()
