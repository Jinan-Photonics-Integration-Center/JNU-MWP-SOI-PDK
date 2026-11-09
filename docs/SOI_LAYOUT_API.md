# JNU SOI PDK 版图 API

供 AI、KLayout Python 宏及批处理脚本调用。接口版本 `api_version` 为 `1`，所有坐标、线宽和半径均用 µm，默认数据库单位为 0.001 µm。

在 SOI PDK 仓库根目录运行以下 PowerShell 命令。请按本机安装位置调整 KLayout 路径，并为每次运行指定新的输出文件名。

```powershell
$klayout = 'D:/KLayout/klayout_app.exe'
& $klayout -b -r tools/jnu_soi_layout.py -rd action=catalog -rd result=catalog.json
& $klayout -b -r tools/jnu_soi_layout.py -rd action=build -rd spec=examples/soi_layout_api.json -rd output=demo.gds -rd result=demo.json
```

`catalog.json` 列出实际可用的库和器件：固定器件有 PinRec 端口名、局部坐标、宽度及朝向；PCell 有可编辑参数、默认值和下拉选项。固定白盒需要先获得授权并安装；固定黑盒位于 `JNULib_BlackBox`，适合占位和规划。正式版图应使用白盒或公开 PCell。批处理脚本也支持带 KLayout `pya` 的独立 Python，例如 `python tools/jnu_soi_layout.py catalog --result catalog.json`。

`build` 按 `operations` 顺序执行，并在结果 JSON 中返回已放置实例在顶层中的端口信息。自动化应同时检查输出文件和日志中的 `JNU_LAYOUT_API_OK`；遇到无效参数或路径，错误会指出对应操作编号。API 不覆盖既有 GDS 和结果文件。完整示例见 [soi_layout_api.json](../examples/soi_layout_api.json)。

| 操作 | 输入 |
| --- | --- |
| `place` | 实例 `id`、`library`、`name`、坐标 `at`；可选 `rotation`（0/90/180/270°逆时针）、`mirror`、`parameters`。 |
| `waveguide` | 曼哈顿坐标 `points`；可选 `width`、`radius`、`bend_type`（Circular / Bezier / Euler）、`bezier`、`euler_rmax`、`euler_rmin`、输出 `layer`（默认 `1/0`）。 |
| `connect` | `start`、`end` 均为 `[实例 ID, 端口名]`；`via` 为中间拐点。弯曲及图层参数同 `waveguide`，宽度由两个端口确定。 |

KLayout 的 Python 宏可以直接导入同一个 API。正常加载 PDK 后可直接导入；若尚未加载，则先将安装目录的 `pymacros` 加入 `sys.path`。

```python
from JNU_MWP_tools.core.layout_api import Layout, catalog

design = Layout(top="DEMO")
design.place("a", "Pcell_Straight_Waveguide", (0, 0), library="JNULib",
             parameters={"length": 30, "width": 0.5})
design.place("b", "Pcell_Straight_Waveguide", (150, 60), library="JNULib",
             parameters={"length": 30, "width": 0.5})
print(design.ports("a"))
design.connect(("a", "opt2"), ("b", "opt1"), via=[(80, 0), (80, 60)],
               radius=20, bend_type="Bezier")
design.save_gds("demo.gds")
```

为确保不同机器得到一致的版图，请显式填写关键 PCell 参数（例如 Taper 宽度、长度和直段延伸）；省略时使用已安装库的默认值。生成的波导使用 PDK 原生 PCell 和 GDS 恢复属性。命名连线使用标准 PinRec（1/10）识别唯一端口，校验首尾方向和线宽，线段不足时拒绝绘制。首版支持单宽度波导和显式拐点，不执行避障、自动加 Taper 或 DRC；完成布局后可在 KLayout 中运行原有 JNU DRC。
