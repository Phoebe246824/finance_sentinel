# Sentinel 舆情分析系统

多源事件实时接入 → 黑名单过滤 → AI 分类评级 → 单条构图 → 风险上下文检索 → 首次风险评估 → （仅超阈值）批量补图 + 二次风险评估 → （仍超阈值）意图分析与趋势预测。

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     用户输入 (终端 / Web 看板)                    │
└────┬────────────────────────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────────────────────────────┐
│  Stage 1  事件标准化 (CrewAI Agent)                              │
│  Normalizer Agent → 原始消息 → NormalizedEvent                   │
└────────────────────────────┬───────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  Stage 1.5  黑名单过滤 (新增)                                     │
│  ├─ 人员 ID 比对  → person_blacklist (Milvus)                     │
│  ├─ 敏感词比对    → keyword_blacklist (Milvus)                    │
│  └─ 事件相似度比对 → event_blacklist (Milvus)                     │
│                                                                 │
│  标准化后所有输入事件先写入 Milvus 事件库                           │
│  OR 逻辑：任一命中 → PASS      全未命中 → 停止 pipeline             │
│            │                       │                             │
│            ▼                       ▼                             │
│        进入 Stage 2          保留事件库记录供后续回捞              │
│                         支持人员 ID + 语义召回                   │
│                                                                 │
│  PASS 后在 sentinel.main 中自动积累命中记录                         │
└────────────────────────────┬───────────────────────────────────┘
                             │ (PASS 路径)
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  Stage 2  事件分类 (CrewAI Agent)                                │
│  TypeClassifier Agent → 事件类型 + 关键实体提取                   │
└────────────────────────────┬───────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  Stage 3  当前事件单条构图 (Graphiti + Neo4j)                    │
│  Episode 写入 → LLM 实体/关系提取 → 去重合并 → 向量               │
└────────────────────────────┬───────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  Stage 4  首次风险上下文检索 (Graphiti)                          │
│  语义向量 + BM25 + 图遍历                                        │
└────────────────────────────┬───────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────┐
│  Stage 5  首次风险评估 (CrewAI Agent)                            │
│  RiskEvaluator Agent（使用 Stage 4 上下文）                      │
└────────────────────────────┬───────────────────────────────────┘
                             │
                 ┌───────────┴───────────┐
                 │                       │
                 ▼                       ▼
       score <= threshold         score > threshold
                 │                       │
                 │                       ▼
                 │         ┌──────────────────────────────────────┐
                 │         │ Stage 6 批量补图 (Milvus 回捞候选)      │
                 │         │ 共享人员直通；非同人候选需通过 rerank     │
                 │         │ 已构图 Episode 跳过，避免重复写 Neo4j    │
                 │         └────────────────┬─────────────────────┘
                 │                          │
                 │          ┌───────────────┴───────────────┐
                 │          │                               │
                 │          ▼                               ▼
                 │   无新增补图 batched=0              有新增补图 batched>0
                 │          │                               │
                 │          │                               ▼
                 │          │                         ┌──────────────────────────────────────┐
                 │          │                         │ Stage 7 二次风险上下文检索 + 二次评估     │
                 │          │                         │ (有回捞候选时重新检索并评估)              │
                 │          │                         └────────────────────┬─────────────────┘
                 │          │                                              │
                 │          │                                   ┌──────────┴───────────┐
                 │          │                                   │                      │
                 │          │                                   ▼                      ▼
                 │          │                           second_score <= threshold  second_score > threshold
                 │          │                                   │                      │
                 ▼          ▼                                   ▼                      ▼
      ┌────────────┐  ┌────────────────────────────┐   ┌────────────┐   ┌──────────────────────────────┐
      │  complete  │  │ Stage 8 Dashboard          │   │  complete  │   │ Stage 8 Dashboard            │
      │  流程结束   │  │ 意图分析 + 趋势预测 (自适应) │ │   |   流程结束  │    │    意图分析 + 趋势预测 (自适应) │
      └────────────┘  └──────────────┬─────────────┘   └───────────┘    └────────────┬─────────────────┘
                                     │                                               │                     
                                     ▼                                               ▼                    
                                ┌────────────┐                               ┌────────────┐              
                                │  complete  │                               │  complete  │      
                                │  流程结束   │                               │  流程结束    │       
                                └────────────┘                               └────────────┘                             
                                                                       
```

**数据流说明**:
1. 用户通过终端或 Web 看板输入消息
2. Stage 1: 标准化 → NormalizedEvent
3. 标准化后的所有输入事件先写入 Milvus 事件库，初始 `is_graph_built=false`
4. Stage 1.5: 黑名单过滤（三合一 OR 匹配）→ PASS 进入 pipeline / 全未命中则停止 pipeline，但事件仍保留在 Milvus 事件库
5. Stage 2: 事件分类 + 关键实体提取
6. Stage 3: 当前事件单条构图，并立即将当前事件标记为已构图
7. Stage 4: 在当前图上检索首次风险上下文
8. Stage 5: 首次风险评估（使用 Stage 4 上下文）
9. 若 Stage 5 `score <= threshold`：直接结束流程（不进入 Dashboard）
10. 若 Stage 5 `score > threshold`：从 Milvus 回捞历史未构图事件候选，并先做相关性准入过滤
11. Stage 6: 共享人员 ID 的历史事件直接进入批量补图；非同人候选需通过 rerank 阈值过滤；Neo4j 已存在相同 Episode 时跳过重复构图并标记 Milvus `is_graph_built=True`
12. 若 Stage 6 `batched_count == 0`：说明没有新增候选真正写入 Neo4j（可能无回捞、全部被 rerank 过滤、或全部已存在 Neo4j），跳过二次检索和二次风险评估，直接进入 Stage 8 Dashboard（保留首次风险评估结果）
13. 若 Stage 6 `batched_count > 0`：Stage 7 在新增补图后检索二次风险上下文并执行二次风险评估
14. 若二次评估 `score > threshold`：进入 Stage 8 Dashboard；否则结束流程

**核心组件**:
- **Milvus**: 黑名单存储（人员 / 关键词 / 相似事件）+ 全量输入事件库与同人/语义候选回捞，构图后通过 `is_graph_built` 避免重复回捞
- **黑名单过滤器**: 人员监控 + 关键词监控 + 相似事件监控
- **Rerank 过滤**: 对非共享人员 ID 的 Milvus 候选做精排过滤，避免语义粗召回噪声进入批量构图
- **批量构图**: 中/高风险触发，合并通过准入的历史事件一次性写入图谱，并跳过 Neo4j 已存在 Episode

## 项目结构

```
finance_sentinel/
├── src/
│   ├── sentinel/            # Sentinel 业务包
│   │   ├── main.py          # CrewAI Flow 编排入口
│   │   ├── models.py        # 共享 Pydantic 数据模型
│   │   ├── dashboard.py     # Web 看板服务 (FastAPI)
│   │   ├── blacklist/       # 黑名单系统
│   │   ├── graph/           # Sentinel 知识图谱 Adapter
│   │   ├── ragflow/         # RAGFlow 外部知识检索与 prompt-safe 证据格式化
│   │   ├── trend_prediction/# 事件分类与自适应提示词
│   │   └── utils/           # 日志、LiteLLM 与文本工具
│   └── graphiti_core/       # 本地嵌入的 Graphiti 内核副本
├── scripts/
│   ├── check_ragflow_retrieval.py   # RAGFlow retrieval 配置与检索自检
│   ├── reset_and_seed_demo_state.py # 重置 Neo4j/Milvus demo 状态并写入黑名单测试种子
│   └── run_blacklist_kv_demo.py     # 15 个测试用例自动回放，启动前执行 full demo reset
├── tests/                   # 单元测试
├── compose/                 # Docker Compose 服务定义
├── config/                  # 结构化非密配置示例
├── .env                     # 密钥与本地服务凭据
├── .env.example             # 密钥与本地服务凭据示例
├── pyproject.toml           # Python 项目元数据、依赖和工具配置
├── uv.lock                  # uv 锁文件
└── requirements.txt         # 兼容旧安装流程的依赖导出
```

## 核心模块说明

### sentinel.main — Pipeline 编排

`SentinelPipelineFlow` (CrewAI Flow):

```
标准化 → 黑名单过滤 → Classification → Single Graph Build
                                          → Search First Risk Context
                                          → First Risk Evaluation
                                          → Router
                                            ├── complete
                                            └── batch_graph
                                                  → Search Second Risk Context
                                                  → Second Risk Evaluation
                                                  → Router
                                                    ├── go_dashboard
                                                    └── complete
                                          → Dashboard (仅 go_dashboard) → complete
```

**Dashboard 阶段**:
- **事件分类器**: LiteLLM Rerank 调用同时分类事件类别（8 种）和影响严重度（4 级），外部调用失败时回退到关键词匹配
- **意图分析专家**: 根据事件类别使用领域自适应提示词（国际政治/科技/经济/社会/公共卫生/能源/金融/公共安全各有专属分析维度）
- **趋势预测专家**: 根据类别 + 严重度动态调整时间范围（轻微→几天到几周，重大→5 年以上）

**运行方式**: 从终端输入消息进行分析

```bash
uv run sentinel
# 或
uv run python -m sentinel.main
# 输入消息内容进行分析，输入 'quit' 或 'exit' 退出
```

### sentinel.models — 数据模型

| 模型 | 用途 | 关键字段 |
|------|------|----------|
| `NormalizedEvent` | 标准化事件 | event_id, source, raw_content, structured_data, trace_id, event_type, risk_level, risk_score |
| `ClassifiedEvent` | 分类结果 | event_type, risk_level, risk_score, key_entities, summary, reasoning |
| `EventSource` | 事件来源枚举 | NEWS, CHAT, TRANSACTION, BEHAVIOR |
| `RiskLevel` | 风险等级枚举 | HIGH, MEDIUM, LOW |
| `EventType` | 事件类型枚举 | EMERGENCY, NEGATIVE, POSITIVE, INFORMATION, BUSINESS |
| `KeyEntity` | 关键实体 | name, type |

### sentinel.dashboard — Web 看板服务

基于 FastAPI 构建的 Web 看板，提供事件可视化、统计分析和 Sentinel
前端 SPA 挂载。ArtD 前端在 Sentinel 菜单下提供 `总览`、`态势大屏`
和 `黑名单管理` 等业务页面；其中 `态势大屏` 复用现有 dashboard
overview payload，不引入假数据或新的持久化写入。`黑名单管理` 通过
受 Dashboard 登录和 `R_SUPER` / `R_ADMIN` 角色保护的 `/api/blacklist/*`
接口维护人员、关键词和典型事件黑名单，不改变 pipeline 运行时匹配语义。

**主要页面**:
- `/#/sentinel/dashboard` — 常规 Web 总览
- `/#/sentinel/data-screen` — Sentinel 风险态势大屏，使用 1920x1080 桌面缩放画布，并在 1320px 以下切换为可读的纵向滚动布局
- `/#/sentinel/blacklist` — 黑名单管理，仅 `R_SUPER` / `R_ADMIN` 可见；人员和关键词支持批量编辑并保护未保存变更，典型事件逐条维护

**主要端点**:
- `GET /` — 看板主页（HTML）
- `GET /api/events` — 事件列表（分页、过滤）
- `GET /api/events/{event_id}` — 事件详情
- `GET /api/dashboard/overview` — ArtD 总览与态势大屏共享的真实统计 payload
- `GET /api/stats` — 统计数据
- `GET /api/stats/risk-distribution` — 风险分布
- `GET /api/stats/source-distribution` — 来源分布
- `GET /api/graph/stats` — 图谱统计
- `GET/POST /api/blacklist/persons*` — 人员黑名单查询与 changeset 批量保存
- `GET/POST /api/blacklist/keywords*` — 关键词黑名单查询与 changeset 批量保存
- `GET/POST/PUT/PATCH/DELETE /api/blacklist/events*` — 典型事件逐条管理；保存时仅 `summary` 参与 embedding 计算

**启动方式**:
```bash
uv run uvicorn sentinel.dashboard:create_dashboard_app --factory --reload --port 8080
```

### sentinel.graph — Graph 底层操作

基于 Graphiti 构建时序知识图谱，将命中黑名单的当前事件先单条入图；若 Neo4j 已存在同文本 Episode，则跳过重复单条构图。若首次风险超阈值，再从 Milvus 回捞历史未构图候选：共享人员 ID 的候选直接补图，非同人候选必须通过 rerank 阈值过滤；已存在 Neo4j 的候选只标记 Milvus 已构图，不重复写图。只有存在新增候选真正进入批量构图时才执行二次检索和二次风险评估；若无回捞、候选均被过滤、或候选均已存在 Neo4j，则跳过二次流程并直接进入 Dashboard。

- `init_graph_client()`: 初始化 Graphiti 客户端（连接 Neo4j、配置 LLM/Embedder/Cross-Encoder）
- `close_graph_client()`: 关闭 Graphiti 客户端及内部 HTTP 资源
- `add_event_to_graph()`: 将事件写入图谱；可选的提取前摘要由 `sentinel.graph.writer` 直接通过 LiteLLM 生成，Graphiti 负责后续实体/关系/向量嵌入
- `hybrid_search()`: 混合检索 — 语义向量 + BM25 + BFS 图遍历 → RRF 融合，支持 `min_score` 相关性阈值过滤低分结果
- `batch_add_to_graph()`: 批量写入 Milvus 回捞的历史事件候选

### sentinel.ragflow — 外部知识检索

RAGFlow 作为可选外部知识检索源，只调用 retrieval API 读取参考 chunks。检索片段会被标记为不可信证据，并注入首次风险评估、二次风险评估和 Stage 8 意图分析/趋势预测的共享事件描述。RAGFlow 不替代 Graphiti 搜索，不上传或解析文档，也不生成最终分析结果。

配置入口见 [docs/ragflow.md](docs/ragflow.md)：`RAGFLOW_API_KEY` 放在 `.env`；`ragflow.enabled`、`ragflow.base_url`、`ragflow.dataset_id(s)`、检索阈值、超时和 prompt 字符上限放在 `config/config.yaml`。

### sentinel.trend_prediction — Dashboard 分类与自适应提示词

**EventClassifier**: 基于 LiteLLM Rerank 的事件分类器，支持 8 种事件类别和 4 级影响严重度评估。

- `classify_with_severity()`: 单次 API 调用同时返回类别 + 严重度，外部调用失败时自动回退到关键词匹配
- 关键词覆盖：8 类别 × 约 20 关键词 + 4 级严重度 × 约 12 关键词

**Dashboard 类别 prompt catalog**: 八个类别来自 `EventClassifier` 的固定趋势 taxonomy；每个类别的意图分析和趋势预测 Markdown 位于 `config/profile/prompts/dashboard/<category>/`，由 `profile.yaml` 显式声明，不使用领域 adapter 类。编辑与变量规则见 [config/profile/README.md](config/profile/README.md)。

**Runtime Profile prompt**: `config/profile/` 共维护 23 个模板：`prompts/pipeline/` 下 5 个主 Pipeline 模板，以及 `prompts/dashboard/` 下 general + 八类 intent/trend pair。`get_profile_config()` 按进程缓存 YAML 和 Markdown，编辑后必须重启 Sentinel。

源码运行和当前 Docker Compose 部署都必须提供完整的 `config/profile/`。Compose 通过 `./config:/app/config` 挂载该目录；项目不支持只安装 wheel 且不提供仓库配置目录的部署方式。

| 类别标识 | 类别 | Prompt 专注维度 |
|---|---|---|
| `intl_politics` | 国际政治 | 地缘冲突、外交关系、制裁禁令 |
| `tech` | 科技 | 技术创新、芯片/AI、竞争格局 |
| `economy` | 经济 | 宏观经济、货币政策、供应链 |
| `society` | 社会/文化 | 性别/种族、教育医疗、社会福利 |
| `public_health` | 公共卫生 | 传染病、疫苗、医疗资源 |
| `energy` | 能源 | 石油/新能源、碳排放、电网 |
| `finance` | 金融 | 银行保险、证券基金、金融风险 |
| `public_safety` | 公共安全 | 危化品、疑似爆炸装置、应急处置 |

**严重度到时间范围映射**:

| 严重度 | 短期 | 中期 | 长期 |
|---|---|---|---|
| 轻微 | 几天到几周 | 几周（无显著持续影响） | 无显著长期影响 |
| 一般 | 1-3 个月 | 3-12 个月 | 1-2 年（有限长期影响） |
| 严重 | 1-3 个月 | 3-12 个月 | 1-5 年（显著长期影响） |
| 重大 | 1-3 个月 | 3-12 个月 | 5 年以上（深远长期影响） |

## 快速开始

### 最简 Web 部署（推荐）

如果只需要把 Sentinel Web 看板、API 和核心依赖一起跑起来，最短流程如下：

```bash
# 1. 准备结构化配置和密钥文件
test -f config/config.yaml || cp config/config.example.yaml config/config.yaml
test -f .env || cp .env.example .env

# 2. 编辑 .env
# 至少填入 LLM_API_KEY、DASHBOARD_ADMIN_PASSWORD
# 如 Embedder/Reranker 不复用 LLM_API_KEY，再单独填 EMBEDDER_API_KEY / RERANKER_API_KEY

# 3. 构建并启动完整 Web 部署
docker compose -f docker/docker-compose.yaml up -d --build

# 4. 确认服务状态并访问 Web
docker compose -f docker/docker-compose.yaml ps
# 浏览器打开 http://localhost:8080
```

`docker/docker-compose.yaml` 会启动 Sentinel Web、Sentinel API、Neo4j、Milvus、
etcd 和 MinIO。`config/` 会挂载进 API 容器，`.env` 只作为运行时密钥来源，不会
打进镜像。默认 Docker 镜像、Python 包源和 npm registry 使用中国境内镜像；如需
替换为官方源或内网源，见 [docs/env-vars.md](docs/env-vars.md)。其它部署方式见
[docs/setup.md](docs/setup.md)。

### 1. 安装依赖

```bash
uv sync --dev
```

### 2. 配置

非密配置放在 `config/config.yaml`，密钥和本地服务凭据放在 `.env`：

```bash
test -f config/config.yaml || cp config/config.example.yaml config/config.yaml
test -f .env || cp .env.example .env
```

本地 Docker Compose 示例默认使用 Neo4j `neo4j/pa55w0rd`。运行前至少需要在 `.env` 中填入 `LLM_API_KEY`；`EMBEDDER_API_KEY`、`RERANKER_API_KEY` 仅在嵌入或重排序服务不复用 `LLM_API_KEY` 时需要单独配置。启用 RAGFlow 时，额外在 `.env` 填入 `RAGFLOW_API_KEY`，并在 `config/config.yaml` 的 `ragflow` 段设置非敏感运行参数。

Docker 部署默认使用 DaoCloud、清华 PyPI 和 npmmirror 等中国境内镜像/包源；如需切回官方源或内网源，可通过 `SENTINEL_*_BASE_IMAGE`、`*_IMAGE`、`UV_DEFAULT_INDEX` 和 `NPM_REGISTRY` 等变量覆盖，完整列表见 `docs/env-vars.md`。

可用脚本检查配置；模型 live 检查会消耗极少额度，执行前会要求确认：

```bash
uv run scripts/check_service_health.py
uv run scripts/check_model_config.py --static-only
```

### 3. 启动 Web 部署或依赖服务

```bash
# 构建并启动完整 Web 部署（Sentinel Web + API + Neo4j + Milvus）
docker compose -f docker/docker-compose.yaml up -d --build

# 如只需要本地依赖服务（Neo4j + Milvus），使用依赖-only compose
docker compose -f docker/compose/dependencies.yaml up -d

# 可选：启动 Attu Milvus 管理界面
docker compose -f docker/compose/dependencies.yaml --profile attu up -d
```

确保以下服务已运行:
- **Milvus**: `localhost:19530` (黑名单存储 + 输入事件库/回捞)
- **Neo4j**: `localhost:7687` (知识图谱存储)

可选服务:
- **Sentinel Web**: `http://localhost:8080` (完整 Web 部署入口)
- **Attu**: `http://localhost:8000` (需先运行 `docker compose -f docker/compose/dependencies.yaml --profile attu up -d`)

### 4. 启动系统

#### 方式一：终端 Pipeline（分析消息）

```bash
uv run sentinel
```

#### 方式二：Web 看板（可视化界面）

```bash
uv run uvicorn sentinel.dashboard:create_dashboard_app --factory --reload --port 8080
```

本地开发模式下，然后访问 http://localhost:8080 查看看板。Docker 完整 Web 部署也使用同一浏览器入口。

系统启动后，在终端输入消息进行分析:

```
======================================================================
  Sentinel Pipeline — CrewAI Flow 驱动
  输入消息进行分析 (输入 'quit' 或 'exit' 退出)
======================================================================

请输入消息内容:
> 某科技公司因产品质量问题被监管部门立案调查
============================================ 消息处理开始 =============================================

[Flow] 用户输入: 某科技公司因产品质量问题被监管部门立案调查
[Flow] 标准化事件: event_id=01JQ..., source=news
[Flow] 黑名单过滤: PASS (命中敏感词) or STOP (仅保留 Milvus 事件库记录)
[Flow] Stage 2: Classification
[Flow] Stage 3: Single Graph Build
[Flow] Stage 4: Search First Risk Context
[Flow] Stage 5: First Risk Evaluation
[Flow] risk_score > threshold: 执行 Milvus 回捞 + 批量补图准入过滤
[Flow] Stage 6: Batch Graph Build from Stash (共享人员直通；非同人候选 rerank 过滤；Neo4j 已存在则跳过重复构图)
[Flow] batched_count == 0: 无新增补图，跳过二次检索/二次评估，直接进入 Stage 8
[Flow] batched_count > 0: Stage 7 Search Second Risk Context + Second Risk Evaluation
[Flow] Stage 8: Dashboard

[dashboard] 分析结果:
======================================================================
# 意图分析报告
...
# 趋势预测报告
...
======================================================================

[Flow] 消息处理完成 ✓

请输入消息内容:
> quit
退出程序
```

## 技术栈

| 组件 | 技术选型 |
|------|----------|
| Agent 框架 | CrewAI (Flow + Agent + Crew) |
| 知识图谱 | Graphiti + Neo4j |
| 黑名单/缓存 | Milvus (pymilvus) |
| 外部知识检索 | RAGFlow retrieval API（可选，只读参考证据） |
| LLM | OpenAI-compatible API（默认 `gpt-4o`，可切换 OpenAI/SiliconFlow/私有 endpoint） |
| Embedding | OpenAI-compatible Embedding（默认 `BAAI/bge-m3`） |
| 数据模型 | Pydantic v2 |
| Web 框架 | FastAPI + Jinja2 |
| 向量检索 | Graphiti Hybrid Search |

## 依赖

```
fastapi          # Web 框架
uvicorn          # ASGI 服务器
crewai           # 多 Agent 框架
src/graphiti_core # 本地嵌入的 Graphiti 内核副本
neo4j            # Neo4j 驱动
pymilvus         # Milvus 客户端（黑名单 + 输入事件库）
pydantic         # 数据模型
python-dotenv    # 环境变量
ulid-py          # 唯一 ID 生成
httpx            # HTTP 客户端
```

## LiteLLM 工具函数说明

### sentinel.utils.litellm_text — 文本生成

**主要功能**:
- `generate_text()`: 通过 LiteLLM 进行文本生成
- 配置统一来自 `SentinelSettings`
- 裸模型名会按 `LLM_PROVIDER` 转为 LiteLLM 可路由的 `provider/model`

### sentinel.utils.litellm_embedding — Embedding

封装 LiteLLM Embedding 调用，提供向量嵌入能力。

**主要功能**:
- `embed_text()`: 获取文本向量
- 支持 BAAI/bge-m3 等模型
- 与文本生成共用 `LLM_PROVIDER` 作为 LiteLLM 默认 provider 前缀

### sentinel.utils.litellm_rerank — 重排序

**主要功能**:
- `rerank_scores()`: 通过 LiteLLM 进行重排序打分，并按输入 documents 顺序返回分数
- 裸模型名默认转为 `jina_ai/<model>`；显式 `jina_ai/...`、`cohere/...` 等 rerank provider 前缀会保持不变

## 许可证

本项目基于 [MIT License](LICENSE) 开源。

项目中包含的第三方组件：

| 组件 | 来源 | 许可证 |
|---|---|---|
| `src/graphiti_core/` | [getzep/graphiti](https://github.com/getzep/graphiti) 的本地嵌入副本 | Apache-2.0（各文件保留原始版权头） |
| `frontend/` | 基于 [Daymychen/art-design-pro](https://github.com/Daymychen/art-design-pro) 二次开发 | MIT（见 `frontend/LICENSE` 与 `frontend/VENDOR.md`） |

## 免责声明

本项目用于研究与学习目的，按"现状"提供，不构成任何投资建议、风控决策依据或执法指引。将本工具用于真实数据时，请自行确保符合适用法律法规与合规要求。

## 金融风控特化分支

本分支（`finance`）是面向**银行零售反欺诈与反洗钱**场景的特化版本，在通用事件分析能力之上，通过 runtime profile 替换领域语义：

- **图谱 schema**：`Customer / Account / Merchant / Device / RiskSignal / RiskEvent` 六类实体，`TransfersFunds / UsesDevice / TriggersSignal / MatchesPattern` 四类资金与风险关系；
- **风险维度**：客户身份、交易行为、交易对手、金额与速率、设备地理、历史上下文、合规信号七维评估；
- **事件分类**：拆分转账、可疑洗钱、涉诈转账、虚拟币风险、贷款欺诈、跑分归集等 12 类风控事件类型；
- **看板提示词**：`dashboard/finance` 类目固定使用零售风控研判模板（资金/账户/合规链条、三路径概率评估）。

激活方式：分支默认已激活（`config/profile/profile.yaml`）。如需切回通用事件分析版本：

```bash
cp config/profile/profile.generic.yaml config/profile/profile.yaml
```

黑名单演示数据（`scripts/blacklist_demo_cases.py` 的拆分转账、洗钱归集等案例）与 RAGFlow 检查脚本的反洗钱查询词在两个分支中通用。

## 贡献

欢迎 Issue 与 Pull Request，流程与要求见 [CONTRIBUTING.md](CONTRIBUTING.md)。
