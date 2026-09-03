# RefLab 后续开发计划（全项目审查报告）

> 生成日期：2026-09-03 · 基于当前 master 工作区
> 审查方法：两路并行代码审查（引擎/模型层逐行核验含 AST 死代码扫描；UI/测试/工程化层含 git 跟踪状态核实）+ 人工复核关键结论
> 范围：`geometry/`、`models/`、`ui/`、`catia/`、`tests/`、仓库工程化配置

---

## 1. 现状综述

**优势**（应当保持的设计资产）：
- 黄金基线回归测试（`tests/test_golden_height_field.py`，7 组参数矩阵、`max|Δz| < 1e-8`）明显高于同类项目水准，是所有重构的安全网；
- 引擎特性测试覆盖缝隙、拟合、起止点等核心语义；
- 性能架构经过实测优化（16×16 约 3s），且优化过程有数值一致性守护。

**短板**（本计划要解决的）：
- 工程化外围缺失：不可 pip install、无 CI、开发依赖未声明、README 的测试命令开箱即失败；
- 两个「上帝类/上帝模块」：`geometry/engine.py`（约 3000 行，20% 死代码）与 `ui/main_window.py`（约 980 行、40+ 方法、9 种职责）；
- 魔法数字散落、近重复代码成簇、UI 文案与错误提示中英混排；
- 静默失败点多处存在（STEP 导出、COM 调用、网格退化），出问题时用户与开发者都拿不到诊断信息。

---

## 2. 里程碑总览

| 里程碑 | 主题 | 前置 | 预估规模 |
|---|---|---|---|
| **M0** | 开源前必修（安全/法律/基本可用） | 无 | 小，纯清理 |
| **M1** | 工程化基建（打包/CI/日志/依赖） | M0 | 中 |
| **M2** | 架构重构（engine 与 UI 拆分） | M1（需 CI 兜底） | 大，分步提交 |
| **M3** | 测试补强与功能收口 | M1 | 中 |
| **M4** | 低优先级清理 | 随时可做 | 碎片化 |

> 铁律：**任何 M2 重构每拆一个文件，必须跑一次 `tests/test_golden_height_field.py` 确认数值不变**。

---

## 3. M0 —— 开源前必修（P0）

### 3.1 安全与隐私

- [x] **确认客户文件未进 git 历史**：`git log --all -- Simulation/ 1.stp "*.CATPart" "*.lug"` 输出为空，历史干净（2026-09-03 已核实）。发布时继续从打包/tarball 中排除这些目录。
- [x] **解除已跟踪的内部工具产物**：`.playwright-mcp/page-*.yml` 已 `git rm --cached`（2026-09-03 完成）。
- [x] **内部文档隔离**：`UI升级开发文档_v0.3.docx`、`ui_parameter_audit.html` 已写入 `.gitignore`。发布前验收：`git status --porcelain` 输出为空。
- [x] **截图敏感信息检查**：`docs/screenshot_*.png` 三张已入库，当前显示的连接名是 `Part2.CATPart`（安全）。但 UI 会显示真实连接的 Part 名（`catia/bridge.py` 的状态条），未来重拍截图时必须确认不含真实项目号（如 VW 零件号）。

### 3.2 法律与规范

- [x] **商标声明**：README 末尾已加免责声明（与 Dassault Systèmes / SYNOPSYS 无隶属关系）。
- [x] **LICENSE 署名确认**：`MIT (c) 2026 Zifei`，作者已确认用个人名（2026-09-03）。
- [x] **SPDX 标识**：27 个 git 跟踪的 .py 文件已批量补 `# SPDX-License-Identifier: MIT`（main.py 的 shebang 保持在第一行）。

### 3.3 基本可用性

- [x] **声明并安装开发依赖**：新增 `requirements-dev.txt`（pytest≥7.0），venv 已安装 pytest 9.1.1。
- [x] **测试可移植性**：`tests/test_step.py` 加 `pytest.importorskip("OCP")`；`tests/test_ui.py` tkinter 加 importorskip、主题/字体断言加 `@win_only` 平台标记。
- [x] **版本号统一 + 根包壳清理**：删除根目录 `__init__.py`（目录名含连字符永远无法作为包导入，且 pytest 9 收集时会把它的相对导入炸掉——**这是修复 pytest 全量收集失败的根因**；`__version__` 零消费者，M1 的 pyproject 重建单一来源）；删除 `ui/main_window.py` docstring 里的 `v0.11`。
- [x] **README 克隆地址**：`https://github.com/FeifeiWang920/RefLab.git`（2026-09-03 确认）。

---

## 4. M1 —— 工程化基建（P1）

### 4.1 打包与依赖

- [x] **pyproject.toml**：元数据、`requires-python = ">=3.9"`、`[project.scripts] reflab = "main:main"`、`[tool.pytest.ini_options]`、ruff/mypy 宽松配置。版本 0.9.7 以 pyproject 为单一来源；`main.py` 启动时经 importlib.metadata 输出版本。`pip install -e ".[dev]"` 已验证可用（2026-09-03）。
- [x] **可选依赖分组**：`step = ["cadquery"]`、`catia = ["pywin32; sys_platform == 'win32'"]`、`dev = ["pytest", "ruff"]`，与实际依赖对齐。
- [x] **可复现性**：新增 `constraints.txt`（Windows 11 / Python 3.13.5 验证组合）。
- [x] **根目录 `__init__.py`**：已删除（M0 完成，同时修复 pytest 9 收集失败）。

### 4.2 CI 与质量门

- [x] **GitHub Actions**（`.github/workflows/ci.yml`）：Windows 全量安装（step+catia extras）、Linux 核心 extras（可跳过子集），ruff 门禁 + pytest；win/ubuntu × py3.12/3.13 矩阵。
- [x] **pytest 配置**：pyproject `[tool.pytest.ini_options]`（testpaths + -q）；`tests/conftest.py` 注入仓库根。
- [x] **Ruff（宽松起步）**：`select = [E,F,W]` + per-file-ignores（E402 为 sys.path 引导惯例、engine 的物理符号 I 与待 M2 清理的 F841）；现存告警已清零。mypy 配置占位已写入 pyproject（不作为 CI 门禁）。
- [x] **.gitignore 裁剪**：移除 Django/Flask/Scrapy 等模板残留，分组注释，补 `.claude/`。

### 4.3 日志与错误处理

- [x] **logging 替代 print**：main.py basicConfig + 版本输出；engine/step_export/mesh_export/bridge/ui 各自模块 logger。
- [x] **STEP 导出静默失败**：print → logging.warning，并统计跳过面数、汇总告警（保持 int 返回值不破坏 API）。
- [x] **mesh_export 静默退化**：`warnings.warn` 附 facet 索引。
- [x] **bridge 关键 `except Exception: pass`**：6 处改 `logger.debug`（选择/命名/关闭/粘贴/Update 路径）。
- [x] **统一用户可见错误入口**：`_user_error` / `_user_warning`（日志 + 弹窗），11 处调用点收口；文案翻译属 M2 strings.py。
- [x] **`MF_REFLECTOR_JOBS` 非法值**：`logger.warning`（含 caplog 回归测试）。

### 4.4 行为修正（属 bug，优先修）

- [x] **`detect_catia()` 探测不再拉起 CATIA**：`_get_catia(allow_launch=False)` 默认仅 GetActiveObject；Dispatch 仅显式发送路径（`allow_launch=True`）。测试：`test_detect_catia_never_launches`（断言探测路径零次 Dispatch）。
- [x] **CATIA 发送后台线程化**：worker + `after` 轮询（复用生成线程模式）；发送期间按钮禁用、生成/发送互斥；成功仅写状态栏不再弹模态。bridge 的 `_get_catia` 已在工作线程内 `CoInitialize`。测试：`test_send_catia_runs_in_background`。

---

## 5. M2 —— 架构重构（P1，分步提交）

### 5.1 geometry/engine.py（约 3000 行）—— ✅ 全部完成（2026-09-03，每步黄金基线验证）

1. [x] **删除约 600 行死代码**：AST 可达性分析定位 22 个死函数 / 597 行，删除后全量测试 + 黄金基线通过。
2. [x] **合并重复实现**：`_realized_angles_on_block` 复用 `_height_slopes`；`_ls_reconstruct_with_borders` 并入 `_SlopeHeightSolver.for_borders` 后删除；1-D 查表闭包统一为 `_table_target_fn`（修复了半成品递归 bug + 恢复被误删的 `_row_h_preemphasis`——黄金基线拦截了一次行为变更）；`_polish_farfield_rectangle` 的 `flux` 死参数删除；UI STL/OBJ 合并为 `_export_mesh`。
3. [x] **魔法数字常量化** → `geometry/tuning.py`（14 个命名常量，覆盖混合权重/gain 调度/抛光/预加重/能量映射/可分离逆问题）。
4. [x] **拆分长函数**：`_build_height_field` 327 行 → 编排器 ~65 行 + `_subgrid_coords/_plan_facets/_pass_absolute/_pass_affine/_pass_inverse/_polish_energy_blocks/_pass_stitch`；`generate_facets` → `_ensure_patch_samples/_add_gap_surfaces` + 装配编排。
5. [x] **管线状态整理**：`HeightField/_GridCtx/_EnergyCtx` NamedTuple（6 元组返回值具名化，位置解包兼容）；`solved`/`blocks` 双份拷贝合并；`cal_blocks` 按阶段命名（abs→cal→inv 由函数边界天然区分）。
6. [x] **模块化拆分**：`geometry/` 现为 parallel(39)/mathutils(157)/flux(186)/reconstruction(253)/solve(590)/facets(863)/tuning(40)/engine(564 门面)；`generate_facets` 经门面延迟转发避免循环依赖；测试引用的私有符号全部 re-export。

### 5.2 ui/main_window.py（约 980 行）—— 结构项完成 4/5（2026-09-03）

- [x] **拆分**：`ui/theme.py`（sv-ttk/字体/muted 色，含 DPI 换算回调）、`ui/constants.py`（窗口/阈值/轮询/超时/颜色）、`ui/dialogs/fstart.py`（F.Start 对话框整体搬移）、`ui/app_state.py`（`collect()` 纯函数化 + `parse_deltas`，可直接单测）；表单 4 helper 的重复样板收敛到 `_field_label/_field_unit`；`main_window.py` 1025 → 744 行。worker.py 未单独拆（后台线程模式 M1 已收敛，拆分收益低）。
- [x] **移除生产代码中的测试辅助**：`_wait_for_generation` 移至 `tests/test_ui.py` 模块级 `wait_generation(app)`。
- [x] **BLAS 环境变量兜底只留一份**：删除 `main.py` 的重复块（`geometry/__init__.py` 在 numpy 首次导入前设置）。
- [x] **文案语言统一（strings.py）**：**作者决定维持现状（中英混排保留），不迁移**（2026-09-03）。

---

## 6. M3 —— 测试补强与功能收口（P2）

### 6.1 缺失的测试 —— ✅ 完成（2026-09-03）

- [x] `models/spreads.py`：新增 `tests/test_spreads.py`（8 项：线性/分段插值、空与单值回退、per_facet 表、缩放平移、frac 钳制）；
- [ ] `catia/bridge.py` 假 COM 单测：**保留未做**——`_select_geometry/_convert_step_to_catpart` 需要深度 mock CATIA COM 对象图，投入产出比低；真实路径已有 UI 后台发送测试 + 探测零 Dispatch 测试覆盖；
- [x] UI 纯函数：`test_parse_deltas_and_aperture_bounds`（parse_deltas 已随 M2 迁至 `ui/app_state.py`，边界四种行为覆盖）；
- [x] `nurbs.py` 双实现等价：新增 `tests/test_nurbs_equivalence.py`（find_span/basis_funs/eval_surface 的 py vs numba 逐点一致，含随机控制点网格）；
- [x] golden 两步流：`capture`（默认输出 `.new.npz`，绝不静默覆盖基线）与 `compare`（报告最大偏差，退出码作门禁）。

### 6.2 功能收口 —— ✅ 完成（2026-09-03）

- [x] `light_target`：`_build_height_field` 入口对非 FAR_FIELD `raise NotImplementedError`（TDD，`test_unsupported_light_target_raises`）；
- [x] `reflection_coefficient`：标注「未参与几何求解；能量仿真不在项目范围，TODO」；
- [x] `SpreadsConfig`：docstring 补充单值列表回退行为（行为保留，文档对齐）；
- [x] 未暴露枚举：`LightTargetType/GapType/GapSurfaceMode` docstring 标注 UI 暴露子集与「仅 API」成员；
- [x] `_collect` 死参数：`step_z=0.0` 注明「UI 未暴露缝隙 Z 向台阶」。

### 6.3 健壮性细节 —— ✅ 完成（2026-09-03）

- [x] `_eval_target_grid` 降级可诊断：数组路径失败时 logger.warning（全局仅一次，防刷屏）；
- [x] `_parallel_map`：worker 异常 re-raise 附 `facet (iu,iv)` 上下文（RuntimeError 链保留原始异常）；
- [x] 防御性 `getattr` 清理：`flux.py`（src.axis）、`solve.py`（uniform_intensity）改直接属性访问（其余随 M2 死代码消亡）；
- [x] `_lists_for_facet`：per_facet 越界报错附表形状与访问下标；
- [x] `_shrink_grid`：无收缩分支统一返回 `copy()`。

---

## 7. M4 —— 低优先级清理（P3，随时做）

- [ ] 删除各测试文件的 `__main__` 手工块（`test_ui.py:117-120` 还漏跑了一个测试；pytest 已覆盖）；
- [ ] `tests/test_engine_features.py` 的 6 处 `__import__("geometry.engine", ...)` 改顶部普通 import；
- [ ] 测试产物改用 pytest `tmp_path`（`test_step.py:50-57`、`test_geometry.py:69-73` 写 `tests/output/`，现存 21 个文件靠扩展名规则间接忽略）；
- [ ] `generate_facets` 三重 Python 循环构建采样网格（2880-2884）——numpy broadcasting 快一个量级；
- [ ] engine 内部 4 处函数级 `from geometry.nurbs import ...` 上提到模块顶部（非循环依赖）；
- [ ] `_make_gap_surface` 未使用的 `samples_u/v` 参数删除（2711）；
- [ ] `z_step_u/v = reflector.z_step_* + gaps.effective_step_z()` 两处重复计算（943-944, 2868-2869）——上移为 property；
- [ ] 缺 docstring 的关键入口：`generate_facets`、`_parallel_map`、`_carrier_z`、`_apply_affine` 等；
- [ ] PEP8 风格残留：单空行分隔函数（693, 2488）、尾部 14 行空行（3050-3063）；
- [ ] `_parse_deltas` 的 `fallback=10.0` 魔数提为常量并注明与 UI 默认值的对应关系。

---

## 8. 总验收标准

| 阶段 | 验收命令 / 检查 | 通过标准 |
|---|---|---|
| M0 | `git status --porcelain` | 输出为空 |
| M0 | 新机器 `pip install -r requirements.txt -r requirements-dev.txt && pytest -q` | 全绿且无意外 skip |
| M1 | `pip install -e ".[dev]" && pytest -q` | 已验证全绿（2026-09-03）；入口命令为 `reflab` |
| M1 | GitHub Actions | 已配置（win 全量 / linux 子集），首次 push 后确认 |
| M2 | 每个拆分提交 | 已满足：每步 25 测试全绿，黄金基线数值零漂移（2026-09-03） |
| M2 | `wc -l geometry/engine.py ui/main_window.py` | engine 564 ✅（<800）；main_window 744（dialog/state 拆出后；strings 迁移待产品决策） |
| M3 | `pytest -q`（Linux 容器） | 除平台标记外全绿 |

---

## 附录 A · geometry/ 模块化拆分方案（M2 第 6 步）

```
geometry/
├── tuning.py          # 全部魔法数字常量（EDGE_WEIGHT、PATHS_LS_BLEND、GAIN 调度、CLIP 区间…）
├── mathutils.py       # 向量原语：_unit/_unit_nd、_target_direction*、_required_normal(s)、
│                      #   _slopes_from_normal(s)、_carrier_z
├── flux.py            # 光通量模型：_source_emission_axis、_incident_flux_weights、
│                      #   _cdf_from_weights、_energy_fracs、_linear_fracs
├── reconstruction.py  # 坡度→高度：_height_slopes、_SlopeHeightSolver（含 border 扩展）、
│                      #   _integrate_relative
├── solve.py           # 单面片定态迭代：_eval_target_grid、_solve_facet_optical、
│                      #   _solve_facet_with_borders、_realized_angles_on_block、TargetTable
├── inverse.py         # 逆问题与校正：_calibrate_facets、_separable/_spatial_inverse、
│                      #   _polish_farfield_rectangle 等
├── facets.py          # NURBS 装配：_shrink_grid、_make_facet_*、_make_gap_*、
│                      #   _apply_no_gap_borders、generate_facets
├── parallel.py        # _facet_worker_count、_parallel_map
└── engine.py          # 门面：_build_height_field 精简为 5 个 pass 的编排（~80 行），
                       #   re-export generate_facets 及测试引用的私有符号
```

**兼容性约束**：`geometry/__init__.py:14` 从 `.engine` 导入 `generate_facets`；`tests/test_engine_features.py:173-249` 直接引用 engine 的私有符号——门面 re-export 保持两者不动。`models/facet.py:71` 的函数级 import 是真正的循环依赖规避，保留。
