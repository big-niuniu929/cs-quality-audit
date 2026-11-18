# 客服质检系统 · 会话质检与商机分级

> 把「抽几条聊天记录看看客服说得怎么样」变成一套可复核的流程：导入会话 → 规则引擎定商机等级 → 6 维评分 → AI 质检维度 → 人工复核 → 两个看板。

桌面应用（PyQt6），Windows / macOS 都能打包成免安装程序；数据在本机 SQLite，不外发。
案例页：**https://big-niuNiu929.github.io/work/cs-quality.html**

---

## 这个仓库是什么

一个**本地跑的客服会话质检工具**。业务方每天导出一批会话记录，质检不再是抽样翻聊天，而是全量过一遍、按同一套标准打分、把可疑的直接标出来。

| 环节 | 做什么 | 在哪 |
|---|---|---|
| **导入解析** | 读会话 `.log` + 会话记录 `.xlsx`，按店铺批次入库，解析多日/多客服会话 | `src/qc_engine/parser/`、`storage/database.py` |
| **角色与型号识别** | 区分客服 / 机器人 / 客户；从商品名末尾识别型号（含套组型号） | `roles.py`、`matcher.py`、`model_matcher.py` |
| **商机分级 A/B/C** | 关键词规则引擎：售前/售后判定、短会话无效判定、留资/比价/降价信号 → 商机等级 | `rules/engine.py`、`config/rules.yaml` |
| **6 维评分** | 响应速度 / 售前必问 / 话术匹配 / 问题解决 / 引导留资 / 优惠触达，四档制满分 100 | `quality/scoring.py`、`config/scoring.yaml` |
| **AI 质检 + 副驾** | AI 质检补齐语义维度；「爆单一铲」按当前筛选或全量提问（数字类问题走只读 SQL 精确统计，内容类问题分批读） | `ai/client.py`、`ai/copilot.py`、`ai/stats.py` |
| **人工复核 / 两个看板** | 逐行改分并留痕；运营看板 + 客服看板（按客服汇总大表，6 维得分率） | `app.py`、`services/runner.py` |

`app.py` 是 UI 层（PyQt6，图表、看板、复核交互全部手绘自绘），`src/qc_engine/` 是引擎层——**UI 与规则/评分/存储分开**，所以评分标准改 YAML 就行，不用动代码。

## 版本线

| tag | 时间 | 形态 | 差别 |
|---|---|---|---|
| `v4.0-legacy` | 2026-10 | 单文件 PyQt 应用（`app.py` 80 KB） | 能跑通「导入 → 看板 → 复核 → 评分规则」的闭环，评分和角色识别都写死在代码里 |
| `v5.2.0` | 2026-11 | 拆包 + 引擎化 + AI | 引擎拆进 `src/qc_engine/`（parser/rules/quality/ai/storage/services）；评分换成 **100 分四档制**；双看板（运营/客服）共用一套筛选；客服汇总大表；AI 质检与「爆单一铲」副驾；macOS 打包 |

中间的小版本：v5.0 双看板 + 评分规则库统一（每维扣 33%/63%/100% → 得 67%/37%/0%）；v5.1 看板筛选共用、导入批次可编辑、「导入中断不再留空壳批次」的修复；v5.2 评分改回 100 分四档制并把档位标准做成可查看的规则库。这些都在 `docs/` 与 README_给同事.md 里有原文。

```bash
git log --oneline --decorate
git show v4.0-legacy --stat
git checkout v4.0-legacy        # 看单文件时代的实现
```

## 怎么跑

```bash
python -m pip install -r requirements.txt     # 只有 PyQt6 + openpyxl + pyyaml
python app.py                                  # 源码直跑
```

打包成免安装程序（给不装 Python 的同事）：

```bash
pyinstaller 全量自动化客服质检系统.spec        # Windows
bash build_macos.command                       # macOS（会自动装依赖再打包）
```

首次使用：`config/ai_config.json` 里填自己的接口地址/模型/密钥（不填也能跑规则质检，只是 AI 维度显示「待AI质检」）；数据落在 `data/qc.db`，升级时保留 `config/` 与 `data/` 两个目录即可。

## 脱敏说明（重要）

- **`data/` 整个目录没有进仓库**：包含真实会话库（SQLite）与会话备份，属于业务数据，只在本地
- **真实客服姓名全部换成编号**（`agent-01` …），`config/roles.yaml` 里的账号前缀与显示名已脱敏
- **AI 密钥清空、内网网关换成占位**（`config/ai_config.json` → `api_key: ""`、`base_url` 指向 `gateway.example.com`）
- **打包产物 `dist/`（含 300+ MB 运行时）与交付 zip 未入库**
- 截图只保留少量界面图，展示的都是示例/合成数据

保留下来的是**规则、评分标准、解析与入库逻辑、UI 结构**——这些是这个项目的本体。

## 目录

```
app.py                     PyQt6 UI（看板 / 明细 / 复核 / 设置）
src/qc_engine/             引擎：parser、rules、quality、ai、storage、services
config/                    rules.yaml / scoring.yaml / roles.yaml / products.yaml / ai_config.json
docs/                      需求理解、ABC 商机判定规则、使用说明书、截图
templates/capsules.json    副驾快捷提问胶囊
全量自动化客服质检系统.spec  PyInstaller 打包配置
build_windows.bat / build_macos.command / start.bat / requirements.txt
```

## 许可与联系

MIT（见 `LICENSE`）。作品集：https://big-niuNiu929.github.io/ · GitHub：[@big-niuNiu929](https://github.com/big-niuNiu929)
