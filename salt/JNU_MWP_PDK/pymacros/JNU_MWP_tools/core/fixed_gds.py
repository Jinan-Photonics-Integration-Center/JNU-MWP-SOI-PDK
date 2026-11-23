# -*- coding: utf-8 -*-
# 创建者: Junyi Zhang
# 时间: 2026-11

"""读取本机白盒源目录配置，并兼容安装副本与独立授权目录。"""

import json
import os
from pathlib import Path

SOURCE_CONFIG = "jnu_whitebox_source.json"


def _application_data_path():
    """与 KLayout 的用户目录一致，独立 Python 也允许隔离配置。"""
    import pya

    if os.environ.get("KLAYOUT_HOME"):
        return Path(os.environ["KLAYOUT_HOME"])
    app = pya.Application.instance() if hasattr(pya, "Application") else None
    if app is not None:
        return Path(app.application_data_path())
    return Path.home() / ("KLayout" if os.name == "nt" else ".klayout")


def _contains_gds(directory):
    return directory.is_dir() and any(
        path.is_file() and path.suffix.lower() == ".gds"
        for path in directory.iterdir()
    )


def fixed_gds_directory(pymacros):
    """每次启动或重载重新解析配置；未配置时维持原安装行为。"""
    home = _application_data_path()
    config = home / SOURCE_CONFIG
    if config.is_file():
        try:
            document = json.loads(config.read_text(encoding="utf-8-sig"))
            value = document.get("gds_directory") if isinstance(document, dict) else None
            if not isinstance(value, str) or not value.strip():
                raise ValueError("gds_directory 必须是非空目录路径")
            source = Path(value).expanduser()
            if not source.is_absolute() or not _contains_gds(source):
                raise ValueError("gds_directory 必须是包含 GDS 文件的绝对目录")
            return str(source)
        except (OSError, ValueError) as error:
            print("JNULib: 白盒源配置无效，使用安装副本：%s (%s)" % (config, error))

    bundled = Path(pymacros) / "JNU_MWP_gds"
    if _contains_gds(bundled):
        return str(bundled)
    private = home / "jnu_private" / "JNU_MWP_gds"
    if _contains_gds(private):
        return str(private)
    return str(bundled)
