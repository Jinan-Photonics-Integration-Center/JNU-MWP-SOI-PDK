# -*- coding: utf-8 -*-
# 时间: 2026-11

"""JNU SOI PDK 的脚本接口。公开坐标、尺寸及端口宽度均以 µm 表示。"""

from dataclasses import dataclass
import importlib
import math
import os
from pathlib import Path
import tempfile

import pya

from JNU_MWP_tools.actions import path_to_waveguide as waveguide
from JNU_MWP_tools.core.common import PIN_LAYER
from JNU_MWP_tools.core.internal_waveguide_registry import ensure_internal_waveguide_pcells
from JNU_MWP_tools.core.pdk_identity import PDK_VERSION, TECHNOLOGY_NAME

API_VERSION = 1
_LIBRARIES = ("JNULib", "JNULib_BlackBox")


def _library(name, *, optional=False):
    if name not in _LIBRARIES:
        raise ValueError(f"Unknown JNU SOI library: {name}")
    lib = pya.Library.library_by_name(name)
    if lib is None:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as error:
            if error.name != name:
                raise
        lib = pya.Library.library_by_name(name)
    if lib is None:
        if optional:
            return None
        raise ValueError(f"Library is not installed: {name}")
    return lib.layout()


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"Expected a finite number, got {value!r}")
    return float(value)


def _xy(point):
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        raise ValueError("Coordinates must be [x, y] in µm.")
    return tuple(_number(value) for value in point)


@dataclass(frozen=True)
class Port:
    name: str
    xy_um: tuple
    width_um: float
    direction_deg: int


def _ports(cell, transform=None):
    """递归匹配同一坐标的 PinRec 文字和两点端口 Path。"""
    layout = cell.layout()
    layer = layout.find_layer(PIN_LAYER)
    if layer is None:
        return []
    labels, paths = {}, {}
    iterator = cell.begin_shapes_rec(layer)
    while not iterator.at_end():
        shape = iterator.shape()
        trans = iterator.itrans()
        if transform is not None:
            trans = transform * trans
        if shape.is_text():
            text = shape.text
            disp = text.trans.disp
            point = trans * pya.Point(disp.x, disp.y)
            labels.setdefault((point.x, point.y), set()).add(text.string)
        elif shape.is_path() and shape.path.width > 0:
            path = shape.path.transformed(trans)
            points = list(path.each_point())
            if len(points) == 2:
                a, b = points
                dx, dy = b.x - a.x, b.y - a.y
                if (dx == 0) != (dy == 0):
                    # PinRec 奇数 DBU 端点按源局部坐标的整数中心处理。
                    a0, b0 = list(shape.path.each_point())
                    center = trans * pya.Point((a0.x + b0.x)//2, (a0.y + b0.y)//2)
                    direction = (0 if dx > 0 else 180) if dx else (90 if dy > 0 else 270)
                    paths.setdefault((center.x, center.y), set()).add((path.width, direction))
        iterator.next()
    return [Port(name, (x * layout.dbu, y * layout.dbu), width * layout.dbu, direction)
            for (x, y), records in sorted(paths.items())
            for name in sorted(labels.get((x, y), ()))
            for width, direction in sorted(records)]


def _editable(library_layout, name):
    decl = library_layout.pcell_declaration(name)
    return {p.name: p for p in decl.get_parameters() if not p.hidden and not p.readonly} if decl else {}


def _parameter_value(spec, value):
    types = pya.PCellDeclarationHelper
    if spec.type == types.TypeLayer:
        value = waveguide._parse_waveguide_layer(value)
    elif spec.type == types.TypeDouble:
        value = _number(value)
    elif spec.type == types.TypeInt and type(value) is not int:
        raise ValueError(f"{spec.name} requires an integer.")
    elif spec.type == types.TypeBoolean and type(value) is not bool:
        raise ValueError(f"{spec.name} requires a boolean.")
    elif spec.type == types.TypeString and not isinstance(value, str):
        raise ValueError(f"{spec.name} requires a string.")
    choices = spec.choice_values()
    if choices and value not in choices:
        raise ValueError(f"{spec.name} must be one of {choices!r}.")
    return value


def _json_value(value):
    return f"{value.layer}/{value.datatype}" if isinstance(value, pya.LayerInfo) else value


def catalog(libraries=None):
    """返回可序列化的器件目录、固定器件端口及 PCell 可编辑参数。"""
    entries = {}
    for name in (_LIBRARIES if libraries is None else libraries):
        lib = _library(name, optional=libraries is None)
        if lib is None:
            continue
        entries[name] = {
            "fixed": {cell.name: [port.__dict__ for port in _ports(cell)]
                      for cell in sorted(lib.top_cells(), key=lambda c: c.name)
                      if not cell.is_pcell_variant()},
            "pcells": {cell_name: {
                param.name: {"default": _json_value(param.default),
                             "choices": [_json_value(value) for value in param.choice_values()],
                             "description": param.description}
                for param in _editable(lib, cell_name).values()
            } for cell_name in sorted(lib.pcell_names())},
        }
    return {"api_version": API_VERSION, "pdk_version": PDK_VERSION,
            "technology": TECHNOLOGY_NAME, "units": "um", "libraries": entries}


class Layout:
    """新建独立版图，使用调用方指定的实例 ID 引用器件。"""

    def __init__(self, top="TOP", dbu=0.001):
        dbu = _number(dbu)
        if dbu <= 0:
            raise ValueError("dbu must be positive.")
        if not isinstance(top, str) or not top.strip():
            raise ValueError("top must be a non-empty cell name.")
        self.layout = pya.Layout()
        self.layout.dbu = dbu
        self.layout.technology_name = TECHNOLOGY_NAME
        self.cell = self.layout.create_cell(top)
        self._instances = {}

    def _point(self, point):
        x, y = _xy(point)
        return pya.DPoint(x, y).to_itype(self.layout.dbu)

    def place(self, id, name, at=(0, 0), *, library, parameters=None, rotation=0, mirror=False):
        """放置固定器件或公开 PCell；旋转以逆时针角度表示。"""
        if not isinstance(id, str) or not id or id in self._instances:
            raise ValueError(f"Instance ID is empty or already used: {id!r}")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty cell name.")
        if type(rotation) is not int or rotation not in (0, 90, 180, 270) or type(mirror) is not bool:
            raise ValueError("rotation must be 0/90/180/270 and mirror must be boolean.")
        point = self._point(at)
        lib = _library(library)
        if parameters is None:
            parameters = {}
        if not isinstance(parameters, dict):
            raise ValueError("parameters must be an object.")
        if name in lib.pcell_names():
            specs = _editable(lib, name)
            if set(parameters) - specs.keys():
                raise ValueError(f"Unknown or read-only parameters: {sorted(set(parameters) - specs.keys())}")
            values = {key: _parameter_value(specs[key], value) for key, value in parameters.items()}
            child = self.layout.create_cell(name, library, values)
        else:
            fixed = lib.cell(name)
            if fixed is None or fixed.is_pcell_variant() or not fixed.is_top():
                raise ValueError(f"Device not found: {library}/{name}. Whiteboxes require installation.")
            if parameters:
                raise ValueError("Fixed cells do not take parameters.")
            child = self.layout.create_cell(name, library)
        if child is None or child.is_empty() or not child.is_library_cell():
            raise ValueError(f"Device produced no geometry: {library}/{name}")
        trans = pya.Trans(rotation // 90, mirror, point.x, point.y)
        instance = self.cell.insert(pya.CellInstArray(child.cell_index(), trans))
        self._instances[id] = instance
        return instance

    def ports(self, id):
        """返回实例在顶层中的光端口坐标、朝向及宽度。"""
        try:
            inst = self._instances[id]
        except KeyError as error:
            raise ValueError(f"Unknown instance ID: {id!r}") from error
        return _ports(inst.cell, inst.cplx_trans)

    def _port(self, reference):
        if not isinstance(reference, (list, tuple)) or len(reference) != 2:
            raise ValueError("A port reference must be [instance_id, pin_name].")
        id, name = reference
        matches = [port for port in self.ports(id) if port.name == name]
        if len(matches) != 1:
            raise ValueError(f"Port must exist and be unique: {id}/{name}")
        return matches[0]

    def waveguide(self, points, *, width=0.5, radius=20.0, bend_type="Circular",
                  bezier=0.35, euler_rmax=30.0, euler_rmin=10.0, layer="1/0"):
        """从曼哈顿点列生成原生单宽度 Waveguide；不自动缩小半径。"""
        if bend_type not in ("Circular", "Bezier", "Euler"):
            raise ValueError("bend_type must be Circular, Bezier or Euler.")
        layer = waveguide._parse_waveguide_layer(layer)
        if (layer.layer, layer.datatype) in ((1, 10), (1, 99), (68, 0), (10, 0), (998, 0)):
            raise ValueError("Choose a physical layer for the waveguide.")
        width = _number(width)
        if width < self.layout.dbu:
            raise ValueError("Width must be at least one database unit.")
        dbu = self.layout.dbu
        path = pya.Path([self._point(point) for point in points], round(width / dbu))
        values = {"width": path.width * dbu, "radius": _number(radius), "bend_type": bend_type,
                  "bezier": _number(bezier), "Euler_Rmax": _number(euler_rmax), "Euler_Rmin": _number(euler_rmin)}
        params = waveguide._result_from_editable_params(waveguide.TAB_SINGLE, values, dbu)
        analysis = waveguide._analyze_path_capacity(path, params["effective_radius"], 0.0, dbu)
        if not analysis["possible"] or analysis["issues"]:
            raise ValueError("Route segments cannot fit the requested effective bend radius.")
        params["waveguide_layer"] = layer
        path = pya.Path(analysis["points"], path.width)
        dpath, trans = waveguide._normalize_dpath_to_origin(path.to_dtype(dbu), dbu)
        child = waveguide._create_waveguide_cell(self.layout, dpath, params, 1)
        if child is None or child.is_empty():
            raise ValueError("Waveguide produced no geometry.")
        inst = self.cell.insert(pya.CellInstArray(child.cell_index(), trans))
        waveguide._store_waveguide_recovery_property(inst, dpath, {"waveguide_layer": layer.to_s()})
        waveguide._mark_waveguide(inst, "single")
        return inst

    def connect(self, start, end, via=(), **options):
        """按名称连接等宽端口，校验首尾线段方向；via 只填写中间拐点。"""
        first, last = self._port(start), self._port(end)
        if not math.isclose(first.width_um, last.width_um, rel_tol=0, abs_tol=self.layout.dbu / 2):
            raise ValueError("Port widths differ; insert a Taper before connecting.")
        if "width" in options:
            raise ValueError("Connection width is determined by the two ports.")
        points = [first.xy_um, *via, last.xy_um]
        coords = [self._point(point) for point in points]
        def along(a, b, direction):
            delta = b - a
            dx, dy = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[direction]
            return delta.x * dy == delta.y * dx and delta.x * dx + delta.y * dy > 0
        if not along(coords[0], coords[1], first.direction_deg) or not along(coords[-1], coords[-2], last.direction_deg):
            raise ValueError("The route must leave each port along its outward direction.")
        return self.waveguide(points, width=first.width_um, **options)

    def save_gds(self, path):
        """原子创建 GDS；不覆盖已有文件。重读确认顶层存在后再发布。"""
        target = Path(path)
        if target.suffix.lower() != ".gds":
            raise ValueError("Output must have a .gds extension.")
        if target.exists():
            raise FileExistsError(target)
        if self.cell.is_empty():
            raise ValueError("Cannot save an empty layout.")
        with tempfile.TemporaryDirectory(prefix=".jnu-api-", dir=target.parent) as folder:
            staged = Path(folder) / "layout.gds"
            options = pya.SaveLayoutOptions()
            options.gds2_write_cell_properties = True
            options.gds2_max_cellname_length = 255
            self.layout.write(str(staged), options)
            reread = pya.Layout()
            ensure_internal_waveguide_pcells(reread)
            reread.read(str(staged))
            top = reread.cell(self.cell.name)
            if top is None or top.is_empty():
                raise RuntimeError("GDS reread did not preserve the top cell.")
            if os.name == "nt":
                os.rename(staged, target)
            else:
                os.link(staged, target)
        return target
