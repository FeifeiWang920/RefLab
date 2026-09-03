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

- [ ] **pyproject.toml**：声明项目元数据、`requires-python = ">=3.9"`、`[project.scripts] mf-reflector = "main:main"`（或迁移入口到包内模块）；`__init__.py` 通过 `importlib.metadata.version()` 读取版本。
- [ ] **可选依赖分组**：`step = ["cadquery"]`、`catia = ["pywin32"]`、`dev = ["pytest", "ruff", "mypy"]`。当前 `requirements.txt:14-15` 注释掉 pywin32 但 `catia/bridge.py:56,63-64` 硬依赖 win32com，声明与实际不符。
- [ ] **可复现性**：requirements 全部 `>=` 无锁定，numba↔numpy 兼容窗口尤其敏感。提供 `constraints.txt`。
- [ ] **根目录 `__init__.py`**：在无打包现状下制造「仓库根是包」的错觉且 import 时连锁拉起 models/geometry；随 pyproject 落地迁入 `src/mf_reflector/__init__.py`（或删除）。

### 4.2 CI 与质量门

- [ ] **GitHub Actions**：Windows 跑全量（含 STEP/CATIA mock），Linux 跑可跳过子集；黄金基线测试必须在每次 push 运行。
- [ ] **最小 pytest 配置**（pytest.ini 或 pyproject `[tool.pytest.ini_options]`）；加 `tests/conftest.py` 注入仓库根到 sys.path，替代散落各处的样板。
- [ ] **Ruff + mypy（宽松起步）**：清理 Django/Flask/Scrapy 残留的 .gitignore 模板段（`*.log` 藏在 "# Django stuff" 下、`*.stp/*.stl/*.obj` 扩展名规则会连带吞掉用户想提交的样例文件），同时补 `.claude/` 忽略。

### 4.3 日志与错误处理

- [ ] **引入 logging 替代 print**：全仓库目前无 `import logging`。
- [ ] **STEP 导出静默失败**（`geometry/step_export.py:83,205`）：BSpline/MakeFace 失败只 print 后继续，用户拿到缺面 STEP 无任何告警——改为 logging.warning 并在返回值中报告跳过面数。
- [ ] **mesh_export 静默退化**（`mesh_export.py:29-31`）：网格点数不匹配时退化为两三角形导出——至少 `warnings.warn` 并附 facet 索引。
- [ ] **catia/bridge 的 5 处 `except Exception: pass`**（168,177,214,430,440 附近）：至少 `logging.debug` 记录异常，COM 失败才可诊断。
- [ ] **统一用户可见错误入口**：中文标题配英文正文（`ui/main_window.py:639-643` 等）。做一个 `_user_error(title, text)` 辅助，统一语言与日志。
- [ ] **`MF_REFLECTOR_JOBS` 非法值静默忽略**（`engine.py:35-38`）：打一条 warning。

### 4.4 行为修正（属 bug，优先修）

- [ ] **`detect_catia()` 探测可能拉起 CATIA 进程**：`ui/main_window.py:97` 构造函数即探测，而 `catia/bridge.py:69-71` 的 `Dispatch("CATIA.Application")` 回退会启动新的 CATIA。探测阶段只用 `GetActiveObject`，`Dispatch` 留给显式「发送」动作。
- [ ] **CATIA 发送在 UI 线程执行**（`ui/main_window.py:939-962`）：大模型时界面冻结。复用 `_gen_thread` 同款后台 worker 模式。

---

## 5. M2 —— 架构重构（P1，分步提交）

### 5.1 geometry/engine.py（约 3000 行）

按下列顺序独立提交，每步跑黄金基线：

1. **删除约 600 行死代码**（占文件 20%，全仓库零引用或仅被死代码引用）：
   位于 engine.py 的 87, 144, 333, 368, 411, 465, 543, 590, 671, 694, 708, 854, 1274, 1368, 1503, 1511, 1569, 1608, 1808, 2202, 2489 行起始的函数（含传递性死亡的 `_match_border_slopes`、`_intensity_scale_field`、`_reach_rectangle_on_surface`）。验收：`pytest tests/ -q` 全绿 + 黄金基线不变。
2. **合并重复实现**：
   - `_realized_angles_on_block` 内部（1535-1550）逐字复制了 `_height_slopes`（171-189）——直接复用；
   - `_ls_reconstruct_with_borders`（2090-2155）与 `_SlopeHeightSolver` 是同一设计矩阵两套实现——给后者加 border 约束参数后删除前者；
   - 6 处几乎相同的 1-D 查表闭包（381, 451, 1759, 1795, 1894, 1971）——提取统一 `TargetTable` 类；
   - `_polish_farfield_rectangle` 的 `flux` 参数从未使用（1424），调用方还专门算了一次通量（1122）——删参数与调用方计算；
   - STL/OBJ 导出两方法 9 行近乎复制（`ui/main_window.py:904-924`）——合并。
3. **魔法数字常量化** → 新建 `geometry/tuning.py`：路径-LS 混合 0.35/0.65（1493）、逆问题轮次与 gain 调度（1069-1071, 1441-1445）、clamp 区间（1791, 1593-1605, 318-329, 2033）、直方图 bin 数、`edge_weight=2.5` 四处双默认（765, 782, 862, 1479）等。
4. **拆分长函数**：`_build_height_field`（325 行）→ 6 个阶段函数（子网格/种子/绝对求解/仿射校准/逆迭代/缝边）；`generate_facets`（234 行）→ patch 采样调整 + 面片装配 + gap 面 + 补洞，并把「直接改写 `reflector.mesh_u/mesh_v`、`reflector.facets`」的隐藏副作用改为显式返回。
5. **管线状态整理**：`acc_calib` 死初始化（1032-1037）、`cal_blocks` 同名三义（1031/1062/1112）、`solved`/`blocks` 双份拷贝（1202-1203）；6 元组返回值改 NamedTuple。
6. **模块化拆分**（见附录 A 的 7 文件方案），`engine.py` 退化为门面并 re-export 测试引用的私有符号（已核实 `tests/test_engine_features.py:173-249` 依赖 6 个私有符号，门面可保持测试不动）。

### 5.2 ui/main_window.py（约 980 行）

- [ ] **拆分上帝类**（9 种职责混在一起）：
  ```
  ui/
  ├── theme.py          # sv-ttk 应用、字体表、muted 色（现 50-146 行）
  ├── constants.py      # 窗口 760×520/最小 560×430、对话框尺寸、阈值 740px、
  │                     #   轮询 50ms、超时 120s、颜色字面量 #5B616B/#1a5f2a
  ├── strings.py        # 全部 UI 文案（见下条）
  ├── widgets.py        # 4 个近重复表单 helper（417-497）合并为 add_field()
  ├── dialogs/fstart.py # F.Start 对话框（600-727）
  ├── app_state.py      # _collect() 纯函数化（740-832）——可直接单测
  └── worker.py         # 后台生成/CATIA 发送线程 + 轮询（834-902）
  ```
- [ ] **文案语言统一**：页签/按钮中文 vs 字段/分组英文混排（193 "Source" vs 188 "设计"；233 字符串内混排）；F.Start 对话框组题英文、复选框中文、按钮英文。决定一种语言（建议中文 UI + 英文枚举值），集中到 `strings.py`。
- [ ] **移除生产代码中的测试辅助**：`_wait_for_generation`（881-902）仅测试使用，移到 tests/conftest 或 mixin。
- [ ] **BLAS 环境变量兜底只留一份**：`main.py:12-16` 与 `geometry/__init__.py:6-12` 重复——抽到单一模块供两处调用。

---

## 6. M3 —— 测试补强与功能收口（P2）

### 6.1 缺失的测试

- [ ] `models/spreads.py` 零直接测试：角度列表解析（`-20,20` 线性 / `0,5,10,15,20` 分段）、`per_facet` 表、`energy_gamma`；
- [ ] `catia/bridge.py` 仅冒烟：`_select_geometry`、`_convert_step_to_catpart`、`import_step_to_active_part` 用假 COM 对象单测；
- [ ] UI 纯函数：`_parse_deltas`（741-748）、`_aperture_bounds`（563-570）；
- [ ] `nurbs.py` 纯 Python 版与 numba 版基函数数值等价性（46-79 vs 116-151，防双实现漂移）；
- [ ] golden 基线更新流程固化：`capture` 增加 `--out new.npz` + `--compare` 两步流，杜绝「重构后直接重跑把漂移固化为新基线」。

### 6.2 功能收口（消除「看起来支持实际无效」）

- [ ] `light_target` 枚举 11 种取值，引擎只实现 FAR_FIELD 且对其余值**静默按远场处理**——入口处 `raise NotImplementedError`，UI 只暴露已实现的；
- [ ] `reflection_coefficient` 只在 summary() 展示、光学求解从未使用——应用它或标注 TODO；
- [ ] `SpreadsConfig.__post_init__` 对单值角度列表也静默替换为 ±global/2，超出 docstring 承诺——对齐文档或保留单值语义；
- [ ] 引擎支持而 UI 未暴露：`STEP_BACK/STEP_BACK_NO_GAP`、`GapSurfaceMode` 另 3 种、`LightTargetType` 其余 10 种——要么暴露要么标注「仅 API」；
- [ ] `_collect` 里的死参数（`step_z=0.0`、`enabled=True`）。

### 6.3 健壮性细节

- [ ] `_eval_target_grid` 的 `except (TypeError, ValueError, IndexError)` 探测会吞掉 target_fn 内部真实 bug——改为显式协议属性（如 `fn.vectorized = True`）；
- [ ] `_parallel_map` worker 异常丢失面片上下文——re-raise 时附 `(iu, iv)`；
- [ ] 防御性 `getattr` 掩盖拼写错误（engine.py:211, 913-914, 996, 1483，dataclass 属性必然存在）——改直接访问；
- [ ] `_lists_for_facet` 对 `per_facet[i_v][i_u]` 无边界校验——加维度上下文报错；
- [ ] `_shrink_grid` 无收缩时原样返回输入对象、有收缩时返回新数组——统一 copy 语义。

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
| M1 | `pip install -e ".[dev]" && pytest -q` | 全绿；`mf-reflector` 命令可启动 |
| M1 | GitHub Actions | Windows 全绿 + Linux 按预期 skip |
| M2 | 每个拆分提交 | `pytest tests/test_golden_height_field.py -q` 不变绿即回滚 |
| M2 | `wc -l geometry/engine.py ui/main_window.py` | engine < 800（门面+编排）、main_window < 300 |
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
