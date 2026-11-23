# -*- coding: utf-8 -*-
# 时间: 2026-11

"""在 KLayout 批处理或 Python 宏中执行 JNU SOI JSON 版图方案。"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "salt/JNU_MWP_PDK/pymacros"))
from JNU_MWP_tools.core.layout_api import API_VERSION, Layout, catalog


def build(plan, destination):
    if not isinstance(plan, dict) or set(plan) - {"api_version", "top", "dbu", "operations"}:
        raise ValueError("Invalid plan fields.")
    if type(plan.get("api_version")) is not int or plan["api_version"] != API_VERSION:
        raise ValueError(f"Expected api_version: {API_VERSION}")
    operations = plan.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ValueError("operations must be a non-empty array.")
    design = Layout(top=plan.get("top", "TOP"), dbu=plan.get("dbu", 0.001))
    methods = {"place": design.place, "waveguide": design.waveguide, "connect": design.connect}
    for index, op in enumerate(operations, 1):
        try:
            if not isinstance(op, dict) or op.get("op") not in methods:
                raise ValueError("Unknown operation; use place, waveguide or connect.")
            methods[op["op"]](**{key: value for key, value in op.items() if key != "op"})
        except (TypeError, ValueError, RuntimeError) as error:
            raise ValueError(f"Operation {index}: {error}") from error
    output = design.save_gds(destination)
    return {"api_version": API_VERSION, "gds": str(output.resolve()),
            "top": design.cell.name,
            "instances": {op["id"]: [asdict(p) for p in design.ports(op["id"])]
                          for op in operations if op["op"] == "place"}}


def run(action, spec=None, output=None, result=None):
    # 结果通过独立 JSON 文件返回，避免 KLayout 库加载日志混入机器可读数据。
    if not result:
        raise ValueError("Specify a new result JSON file.")
    report = Path(result)
    if report.suffix.lower() != ".json" or report.exists() or not report.parent.is_dir():
        raise ValueError("result must be a new .json file in an existing directory.")
    if action == "catalog":
        data = catalog()
    elif action == "build" and spec and output:
        plan = json.loads(Path(spec).read_text(encoding="utf-8-sig"))
        data = build(plan, output)
    else:
        raise ValueError("Use catalog or build; build requires spec and output.")
    with report.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    print(f"JNU_LAYOUT_API_OK: {report.resolve()}", flush=True)


if __name__ == "__main__":
    if "action" in globals():
        run(action, globals().get("spec"), globals().get("output"), globals().get("result"))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("action", choices=("catalog", "build"))
        parser.add_argument("--spec")
        parser.add_argument("--output")
        parser.add_argument("--result", required=True)
        args = parser.parse_args()
        run(args.action, args.spec, args.output, args.result)
