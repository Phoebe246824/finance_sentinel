> 所属项目：[AGENTS.md](../AGENTS.md)

## 架构约定

### 分层规则

```
入口层 (src/sentinel/main.py)
  └── Flow 编排 — SentinelPipelineFlow 串联所有 Stage，并保留少量管线级 helper
        ├── 黑名单过滤 — sentinel/blacklist/filter.py 三合一 OR 匹配
        ├── Milvus 事件库 — sentinel/blacklist/stores/events_store.py 全量输入事件与同人/语义相关事件池
        ├── Stage 1: classification — CrewAI Agent 分类
        ├── Stage 2: single_graph_build — 当前事件单条构图
        ├── Stage 3: search_first_risk_context — 首次风险上下文检索
        ├── Stage 4: first_risk_evaluation — 首次风险评估
        ├── Stage 5: route_post_first_risk — 阈值路由（complete/batch_graph）
        ├── Stage 6: batch_graph_build_from_stash — Milvus 回捞历史事件补图
        ├── Stage 7: search_second_risk_context + second_risk_evaluation_stage
        └── Stage 8: dashboard — 意图分析与趋势预测
```

- **src/sentinel/main.py**: 负责 Flow 编排、流程控制和仍未拆出的管线级 helper；新业务逻辑应优先沉淀到对应领域模块，避免继续扩大入口层
- **src/sentinel/pipeline/**: 从 `main.py` 抽出的 Stage 级业务逻辑包，承载 blacklist gate、classification、risk、batch、dashboard 和 LLM JSON 解析 helper
- **src/sentinel/blacklist/**: 黑名单系统，`stores/` 包含 Milvus 黑名单存储（persons_store/keywords_store/event_samples_store/events_store），`stores/factory.py` 负责创建运行时 store bundle，`events_store.py` 负责输入事件落库与回捞，`management.py` 提供 Web 管理服务边界，负责操作员 CRUD 语义、批量 changeset 校验、乐观冲突检查、硬删除以及典型事件 summary dirty check。Pipeline 匹配继续使用既有 store lookup/append 接口，不通过 Web 管理服务。`milvus_stash.py` 仅保留兼容脚本/诊断入口。事件 collection 必须使用 `events_schema.py` 定义的静态字段，禁用 dynamic fields
- **src/sentinel/graph/**: Sentinel 知识图谱 Adapter，封装 Graphiti 客户端生命周期、Episode 写入、混合检索和 `batch_add_to_graph()` 批量构图
- **src/sentinel/ragflow/**: RAGFlow retrieval API 客户端和 prompt-safe 外部知识格式化。RAGFlow 只作为外部参考证据来源，不替代 Graphiti 搜索，不上传或解析文档，不生成最终分析结果
- **src/sentinel/trend_prediction/**: Dashboard 的八类趋势分类、严重度分类、类别提示词选择和意图/趋势分析编排；非 zero-shot 自适应提示词正文统一由 runtime profile 提供
- **src/sentinel/web/**: Web 看板后端包，`api.py` 提供 ArtD 兼容接口，`analysis_tasks.py` 管理真实分析任务流，`repository.py`/`serialization.py` 负责 Milvus 结果持久化与 payload 转换，`spa.py` 负责挂载 `frontend/dist`。API 返回 ArtD 兼容 `{code,msg,data}` envelope，`/api/` 保持 JSON，`/` 和非 API 路由服务前端页面。事件列表/概览默认使用轻量字段投影；需要原文匹配的关键词搜索会显式请求完整字段。`/api/blacklist/*` 是受 Dashboard 登录和 `R_SUPER` / `R_ADMIN` 角色保护的黑名单管理接口，路由层只做 envelope、认证和错误映射，业务规则下沉到 `sentinel.blacklist.management`
- **src/sentinel/utils/litellm_*.py**: 非 Graphiti 文本生成、Embedding、Rerank 的 LiteLLM 原子工具函数；图谱提取前摘要逻辑属于 `src/sentinel/graph/writer.py`
- **src/sentinel/utils/text.py**: 共享文本工具函数（如 `extract_subject_id_numbers`），避免模块间循环导入
- **frontend/**: Sentinel ArtD 前端应用，承载路由、API client、页面和业务组件。后端接口封装在 `src/api/sentinel/`，业务页面通常放在 `src/views/sentinel/`；`/sentinel/data-screen` 态势大屏位于 `src/views/sentinel/dashboard/data-screen.vue`，从现有 dashboard overview API 派生展示模型；`/sentinel/graph/person` 图谱查询页通过 Web 图谱 API 读取人员一跳关系，并用 `SentinelGraphViewer` 渲染交互式 SVG 图谱；风险分析工作台在真实分析完成后按事件 ID 加载事件图谱，并展示持久化的图谱构建指标；`/sentinel/blacklist` 黑名单管理位于 `src/views/sentinel/blacklist/index.vue`，通过 `src/api/sentinel/blacklist.ts` 调用管理 API，表达人员/关键词 pending changeset 和典型事件单条 CRUD，不直接编码 pipeline、Graphiti 或 Milvus 匹配语义；设置、关于等顶层应用栏目放在同名 views 目录和独立 route module

### 模块边界

- `src/sentinel/` 是 Sentinel 运行时业务包；新业务逻辑应优先沉淀到对应领域模块，避免继续扩大 `src/sentinel/main.py`
- `src/sentinel/pipeline/` 存放 Stage-specific business logic；`sentinel.main` 负责 Flow wiring、CLI、生命周期和少量管线级 helper
- `scripts/` 存放本地运维、检查和演示脚本；脚本应调用稳定的 `sentinel.*` 接口，不承载运行时核心业务逻辑
- `src/graphiti_core/` 是 vendored Graphiti 内核；默认不改。若任务明确涉及构图方案、Graphiti 行为适配、图谱写入或检索底层机制，可以修改，但必须说明影响范围并扩大验证
- `src/sentinel/ragflow/` 只封装 RAGFlow retrieval 读取、检索结果归一化和 prompt-safe 证据拼接；不得承载上传、解析、数据集管理或最终判断逻辑
- `frontend/` 存放 Web 前端业务实现；不让前端直接编码 pipeline、Graphiti、Milvus 语义，只通过 `src/sentinel/web` 暴露的 API 契约访问后端。Sentinel 态势大屏复用 `GET /api/dashboard/overview` 的真实数据，在前端本地完成风险 KPI、图表、排行和趋势片段派生；图谱页面和风险分析工作台只消费后端返回的 `PersonGraph` payload，在前端负责交互式布局、缩放、拖拽和详情展示，不自行拼接 Graphiti 查询；黑名单管理页面仅表达人员/关键词 changeset、未保存变更状态和典型事件单条 CRUD，不自行推断 embedding 或匹配规则；需要新数据时应新增只读 Web API，而不是硬编码假数据
- `src/sentinel/models.py` 定义所有共享数据模型，其他模块通过 `from sentinel.models import ...` 引用
- `src/sentinel/utils/logging.py` 提供双输出系统：`print_*` 函数用于终端（面向用户），`get_logger()` 用于文件日志（面向开发者）
- `src/sentinel/utils/stage_timer.py` 提供可复用阶段计时工具：短流程可直接 `with StageTimer()` 后使用 `timer.stage("...")`；异步函数推荐使用 `@timed_stages()` 包裹，并在函数内部 `with stage("...")` 标记阶段。TTY 终端下通过 Rich live 刷新当前阶段耗时，完成阶段固定显示；不再额外输出最终文本版耗时拆分。
- `config/profile/` 统一承载运行时结构化领域配置、主 pipeline 的可编辑 prompt，以及非 zero-shot Dashboard 自适应 prompt catalog；`src/sentinel/pipeline/` 不保留这些 prompt 的 package-local 副本，`src/sentinel/trend_prediction/` 也不使用领域 prompt adapter
- `src/sentinel/blacklist/stores/` 统一管理 Milvus 黑名单存储（人员/敏感词/事件样本/输入事件库）；`stores/factory.py` 的 `create_store_bundle()` 负责一次性创建所有存储实例
- `src/sentinel/blacklist/management.py` 承载 Web 黑名单管理业务规则。人员和关键词通过显式 changeset 批量保存；典型事件逐条保存，并仅在 summary 变化时重新计算 embedding，description 只作为管理备注
- 黑名单 stores 提供单条和批量写入接口。脚本预置数据应优先使用 `append_persons()`、`append_keywords()`、`append_events()`，避免逐条 query/upsert/flush 放大 Milvus 初始化耗时
- `src/sentinel/utils/` 存放跨模块共享的工具函数，避免循环导入（如 `extract_subject_id_numbers` 从 `main.py` 迁出至此）

### Pipeline Stage Module Ownership

`sentinel.main` owns CrewAI Flow wiring, `process_message()`, CLI, and service lifecycle.
Stage-specific business logic lives under `sentinel.pipeline.*`:

- `blacklist_gate.py` owns blacklist proceed/stop gate helpers and match write-back.
- `classification.py` owns classification dynamic values, event mutation, and the Python output contract.
- `risk.py` owns risk dynamic values, risk parsing, the Python output contract, and related-context rendering.
- `batch.py` owns Milvus event recall and batch graph build decisions.
- `dashboard.py` owns trend-prediction dashboard execution helpers.

Graph search helpers that query or filter Graphiti/Neo4j search results live under `sentinel.graph.search`.

### Runtime Profile 与 Prompt 所有权

`config/profile/` 的职责保持集中且简洁：

```text
config/profile/
├── profile.yaml                 # graph、risk、pipeline classification、dashboard policy 与所有 prompt 路径
├── README.md                    # 编辑规则、变量契约和运维注意事项
└── prompts/
    ├── pipeline/                # normalization、graph extraction、classification、两次 risk
    └── dashboard/               # general 与八个趋势类别各自的 intent/trend pair
```

运行时数据流如下：

```text
profile.yaml + Markdown
  -> get_profile_config() 延迟加载并缓存 typed Prompt catalog
  -> Stage 组装动态值和 Python output contract
  -> render_prompt()
  -> LLM
```

`get_profile_config()` 与 settings 一样按进程缓存，但 profile 根目录固定为仓库的 `config/profile/`；它不接受 settings、环境变量或可变路径。`profile.yaml` 必须显式声明每个 prompt 的相对路径。修改 YAML 或 Markdown 后必须重启进程，运行中的进程不会热加载。原先位于 pipeline package、`trend_prediction/prompts` 或领域 adapters 的对应可编辑 prompt 已移除，因此不要为 catalog 覆盖的 Stage 创建第二份来源。

仓库 catalog 共 23 个模板：5 个 pipeline 模板，以及 general 加八类 Dashboard 的 18 个 intent/trend 模板。源码运行和 Docker Compose 部署必须提供完整 `config/profile/`；当前不支持脱离仓库配置目录的 wheel-only 部署。

Stage 负责提供当前事件等动态值，并以 Python 常量/模型维护机器可读输出契约；profile Markdown 只维护可编辑的自然语言指导和固定 Markdown 输出措辞。除 graph extraction 外，Stage 使用 `render_prompt()` 注入动态值后才调用 LLM。Graph extraction Markdown 则原样传给 Graphiti，由 Graphiti 自己处理其内容；Sentinel 不对它做占位符插值。

`render_prompt()` 将普通 Python format 异常统一转换为脱敏的 `PromptRenderError`，错误只保留逻辑名称、源路径和异常类型。该错误越过 Stage 的模型 fallback 并终止当前 Pipeline；`BaseException` 继续传播，LLM、网络和 JSON/解析失败仍使用原有 Stage fallback。

该 catalog 不涵盖所有代码内的 LLM 指令：Dashboard zero-shot trend prompt 和 `sentinel.graph.writer` 的构图前摘要 prompt 仍由代码持有。Profile 中的 graph extraction prompt 虽属于 catalog，但按上述规则原样传给 Graphiti。

Dashboard 的自动路径先由 `EventClassifier` 同时给出八类趋势类别和严重度，再按类别选择 intent/trend prompt pair。类别未知、为 `general` 或未在 `prompts.dashboard.categories` 声明时，effective category 和 prompt pair 都回退为 `general`。`dashboard.force_category` 非空时跳过自动类别分类并采用强制类别/置信度；该值仍必须经过相同的已声明类别解析，未声明的强制类别也回退为 effective `general`。通用仓库 profile 保持 `force_category: null`，默认使用自动分类。

这里有两个独立分类空间，不得混用：

- `profile.classification.categories` 定义 pipeline Stage 1 的业务事件类型，结果写入 `NormalizedEvent.event_type`，其集合由 profile 维护。
- Dashboard 趋势分类固定使用 `classification_taxonomy.py` 的八类 taxonomy：`intl_politics`、`tech`、`economy`、`society`、`public_health`、`public_safety`、`energy`、`finance`，用于选择类别 prompt pair；`general` 是回退类别，不是第九个自动分类类别。

### API 设计约定

- FastAPI 应用使用 **factory 模式**：`create_app(settings)` / `create_dashboard_app(settings)`
- Pipeline 为 CrewAI Flow 内存编排，Stage 之间通过 `FlowState` 传递上下文
- 路由：`/api/` 前缀为 JSON API，`/` 为 HTML 页面或 ArtD SPA
- Web 看板 API 对前端使用 ArtD envelope：`{"code": 200, "msg": "success", "data": ...}`。表格接口同时兼容 `current/size` 和 `page/page_size`
- `create_dashboard_app()` 会装配 `AnalysisTaskManager`、`EventResultRepository` 和 SPA fallback；若 `frontend/dist` 尚未构建，则返回占位 HTML 提示

### 状态管理约定

- 去重逻辑：在 `sentinel.main` 中通过内存去重（事件 ID 比对）
- 非 Graphiti 模型调用：通过 `sentinel.utils.litellm_text`、`sentinel.utils.litellm_embedding`、`sentinel.utils.litellm_rerank` 中的原子函数调用 LiteLLM
- RAGFlow 可选检索：`sentinel.ragflow` 调用 RAGFlow retrieval API，将外部知识片段作为不可信参考证据注入首次风险评估、二次风险评估和 Stage 8 意图/趋势分析；RAGFlow 不替代 Graphiti 搜索，也不生成最终分析结果
- Milvus 黑名单：`persons_store`、`keywords_store`、`event_samples_store`，通过 `stores/factory.py` 的 `create_store_bundle()` 统一创建
- Milvus 事件库：`input_events` collection 当前保存所有标准化后的输入事件，支持人员 ID 精确召回与语义相似召回。旧配置文件中的 `milvus.stash_collection` 会在自动补齐配置时迁移为 `milvus.input_events_collection`。未构图事件以 `is_graph_built=false` 保留为后续批量补图候选；非 dry-run 的当前事件单条构图成功或历史候选补图/确认已存在后标记为 `is_graph_built=true`。collection schema 使用静态字段：`event_id`、`person_ids`、`raw_content`、`created_at`、`expire_at`、`is_graph_built`、`embedding`
- Milvus 连接生命周期：通过 `stores/` 共享一个 `MilvusClient`，`StoreBundle.aclose()` 统一关闭 Milvus client 与 embedder 内部客户端，`process_message()` 的 `try/finally` 确保资源释放
- Web 真实分析任务：`AnalysisTaskManager` 当前默认最多并发 1 个任务；通过 `/api/tasks/{task_id}/stream` 以 SSE 回放 `queued/running/success/failed` 更新，终态任务历史只保存在进程内存中并按 TTL 清理
- Web 分析结果持久化：`PipelineRunResult` 通过 `sentinel.web.serialization` 转为 ArtD payload，再由 `EventResultRepository` 写回 Milvus 事件行；`PipelineRunResult.graph_result` 会归一化为轻量 `graph_summary`，并以有界 `graph_summary_json` 保存实体数、关系数、回捞候选和批量补图等图谱构建指标；未进入完整分析流的 `stashed` 结果以 `risk_level=unassessed` 展示，不计入 high/medium/low 风险分布；`/api/events*` 和 `/api/dashboard/overview` 读取的是持久化结果，不依赖内存任务历史，超过仓储扫描上限时 payload 会显式携带截断标记。列表和概览路径避免拉取详情页才需要的大文本/JSON 字段，关键词搜索为保留“事件 ID / 摘要 / 原文”匹配能力会请求完整 Web 字段
- Web 图谱查询：`/api/graph/person` 使用只读 Graphiti/Neo4j 客户端，按 `group_id` 和规范化 `id_number` 精确定位单个中心节点后做有界一跳扩展；`/api/graph/events/{event_id}` 先读取持久化事件，再用事件原文和 `group_id` 精确匹配 `Episodic` 节点，返回事件、MENTIONS 实体和一跳 `RELATES_TO` 关系；图谱 payload 会过滤 embedding/vector 字段并保留 JSON-safe 的 labels/properties，供前端统一渲染；dashboard graph counts 使用短 TTL 进程内缓存，避免页面重复刷新触发高频全图计数
