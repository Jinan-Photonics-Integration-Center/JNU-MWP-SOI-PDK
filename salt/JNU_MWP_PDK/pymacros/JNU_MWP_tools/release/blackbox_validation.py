# -*- coding: utf-8 -*-
# 时间: 2026-11

"""重读生成的黑盒，阻止内部图形或额外图层进入公开器件库。"""

import pya


def verify_port_straights(cell, layout):
    """独立核对四向直段、原连接端面和黑盒主体，拒绝多余的内部 Si。"""
    bodies = list(cell.shapes(layout.layer(998, 0)).each())
    assert len(bodies) == 1 and bodies[0].is_box(), cell.name
    body = bodies[0].box
    assert not body.empty(), cell.name
    si = list(cell.shapes(layout.layer(1, 0)).each())
    paths = [s.path for s in cell.shapes(layout.layer(1, 10)).each() if s.is_path()]
    assert len(si) == len(paths) > 0 and all(s.is_box() for s in si), cell.name
    remaining = [s.box for s in si]
    for path in paths:
        a, b = list(path.each_point())
        x, y = (a.x + b.x) // 2, (a.y + b.y) // 2
        dx, dy = b.x - a.x, b.y - a.y
        half = path.width // 2
        other_half = path.width - half
        if dx > 0:
            match = next((s for s in remaining if s.right == x and s.bottom == y - half
                          and s.top == y + other_half and s.left == body.right), None)
        elif dx < 0:
            match = next((s for s in remaining if s.left == x and s.bottom == y - half
                          and s.top == y + other_half and s.right == body.left), None)
        elif dy > 0:
            match = next((s for s in remaining if s.top == y and s.left == x - half
                          and s.right == x + other_half and s.bottom == body.top), None)
        else:
            match = next((s for s in remaining if s.bottom == y and s.left == x - half
                          and s.right == x + other_half and s.top == body.bottom), None)
        assert match is not None, (cell.name, str(path))
        length = match.width() if dx else match.height()
        assert abs(length * layout.dbu - 0.2) < 1e-9, cell.name
        assert (pya.Region(match) & pya.Region(body)).is_empty(), cell.name
        remaining.remove(match)
    assert not remaining, cell.name


def verify_blackbox_gds(path, expected_name):
    """核对写出的单器件 GDS、端口、显示图层和标签子单元。"""
    layout = pya.Layout()
    layout.read(str(path))
    tops = layout.top_cells()
    assert len(tops) == 1 and tops[0].name == expected_name, path
    top = tops[0]
    verify_port_straights(top, layout)
    pin_shapes = list(top.shapes(layout.layer(1, 10)).each())
    assert any(shape.is_text() for shape in pin_shapes), expected_name
    assert all(shape.is_path() or shape.is_text() or shape.is_box() for shape in pin_shapes), expected_name
    devrec = list(top.shapes(layout.layer(68, 0)).each())
    assert len(devrec) == 1 and devrec[0].is_box(), expected_name
    allowed_layers = {(1, 0), (1, 10), (68, 0), (10, 0), (998, 0)}
    for cell in layout.each_cell():
        for index in layout.layer_indices():
            if cell.shapes(index).is_empty():
                continue
            info = layout.get_info(index)
            layer = (info.layer, info.datatype)
            assert layer in allowed_layers, (expected_name, layer)
            if cell.cell_index() != top.cell_index():
                assert layer == (10, 0), (expected_name, layer)
