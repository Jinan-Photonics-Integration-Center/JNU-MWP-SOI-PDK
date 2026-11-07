# -*- coding: utf-8 -*-
# 时间: 2026-11

"""在独立 KLayout 进程中验证原生属性窗口的确定、取消与新建默认值。"""

from pathlib import Path
import sys
import tempfile
import traceback

import pya

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from JNU_MWP_tools.core import taper_defaults


def verify(directory, settings_path=None):
    if settings_path is not None:
        taper_defaults._path = lambda: settings_path
    import JNULib

    window = pya.Application.instance().main_window()
    cellview = window.create_layout(1)
    layout = cellview.layout()
    top = layout.create_cell("TOP")
    cellview.cell = top
    view = window.current_view()
    def place(x):
        view.switch_mode("instance")
        point = pya.DPoint(x, 0)
        view.send_mouse_move_event(point, 0)
        view.send_mouse_press_event(point, pya.ButtonState.LeftButton)
        view.send_mouse_release_event(point, pya.ButtonState.LeftButton)
        view.switch_mode("select")

    view.set_config("edit-inst-lib-name", "JNULib")
    view.set_config("edit-inst-cell-name", "Pcell_Taper")
    view.set_config("edit-inst-pcell-parameters", "!length:##50;width1:##0.65;")
    view.commit_config()
    place(0)
    original = next(top.each_inst()).cell.pcell_parameters_by_name()
    assert original["length"] == 50.0 and original["width1"] == 0.65
    assert taper_defaults.load() == original
    old_output = directory / "old_taper.gds"
    layout.write(str(old_output))
    view.set_config("edit-inst-cell-name", "Pcell_Straight_Waveguide")
    view.commit_config()

    def edit_length(length, accept):
        instance = next(top.each_inst())
        path = pya.ObjectInstPath()
        path.top = top.cell_index()
        path.cv_index = view.active_cellview_index
        path.append_path(pya.InstElement(instance))
        view.object_selection = [path]
        errors = []

        def change():
            dialog = next((widget for widget in pya.QApplication.topLevelWidgets()
                           if widget.objectName == "properties_dialog" and widget.visible), None)
            try:
                assert dialog is not None, "未打开属性对话框"
                dialog.findChild("param_tab_widget").setCurrentIndex(1)
                field = dialog.findChild("length")
                assert field is not None, "找不到长度字段"
                field.setFocus()
                field.selectAll()
                pya.QApplication.sendEvent(field, pya.QKeyEvent(
                    pya.QEvent.KeyPress, 0, pya.Qt.NoModifier, str(length),
                ))
                assert field.text == str(length), field.text
                button = dialog.findChild("ok_button" if accept else "cancel_button")
                button.setFocus()
                button.click()
            except Exception:
                errors.append(traceback.format_exc())
                if dialog is not None:
                    dialog.reject()

        timer = pya.QTimer(window)
        timer.setSingleShot(True)
        timer.timeout(change)
        timer.start(120)
        window.menu().action("edit_menu.show_properties").trigger()
        if timer.isActive():
            wait = pya.QEventLoop()
            done = pya.QTimer()
            done.setSingleShot(True)
            done.timeout(wait.quit)
            done.start(250)
            wait.exec_()
        timer.stop()
        assert not errors, errors

    edit_length(73.25, True)
    assert next(top.each_inst()).cell.pcell_parameters_by_name()["length"] == 73.25, next(top.each_inst()).cell.pcell_parameters_by_name()
    assert taper_defaults.load()["length"] == 73.25
    assert layout.create_cell("Pcell_Taper", "JNULib", {}).pcell_parameters_by_name()["length"] == 73.25
    old_layout = pya.Layout()
    old_layout.read(str(old_output))
    assert next(old_layout.top_cell().each_inst()).cell.pcell_parameters_by_name() == original
    edit_length(92.75, False)
    assert next(top.each_inst()).cell.pcell_parameters_by_name()["length"] == 73.25
    assert taper_defaults.load()["length"] == 73.25
    view.set_config("edit-inst-cell-name", "Pcell_Taper")
    view.commit_config()
    pya.QApplication.processEvents()
    place(120)
    placed = [i.cell.pcell_parameters_by_name() for i in top.each_inst()]
    assert placed == [dict(original, length=73.25)] * 2, placed

    explicit = layout.create_cell("Pcell_Taper", "JNULib", {"length": 23.0})
    top.insert(pya.CellInstArray(explicit.cell_index(), pya.Trans(150000, 0)))
    output = directory / "tapers.gds"
    layout.write(str(output))
    reopened = pya.Layout()
    reopened.read(str(output))
    assert sorted(i.cell.pcell_parameters_by_name()["length"] for i in reopened.top_cell().each_inst()) == [23.0, 73.25, 73.25]
    assert taper_defaults.load()["length"] == 73.25
    assert next(p.default for p in JNULib.Taper(use_last_parameters=True).get_parameters()
                if p.name == "length") == 73.25


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="jnu_taper_") as temporary:
        directory = Path(temporary)
        verify(directory, settings_path=directory / "taper.json")
    print("TAPER_LAST_PARAMETERS_PASS")
