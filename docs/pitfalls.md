> 所属项目：[AGENTS.md](../AGENTS.md)

## 注意事项 / 已知陷阱

### 环境与平台

- **Python 版本**：项目使用 Python 3.13，请确认所有依赖兼容性
- **Docker 资源**：完整 Web compose 默认会启动 Sentinel Web/API 与 Milvus 依赖容器（etcd + MinIO + Milvus）和 Neo4j；只需要依赖服务时使用 `docker compose -f docker/compose/dependencies.yaml up -d`。Attu 通过 `docker compose -f docker/compose/dependencies.yaml --profile attu up -d` 可选启动。请确保 Docker 分配了至少 8GB 内存
- **不要在 worktree 之间复用 `.venv`**：`.venv/bin/uvicorn`、`.venv/bin/pytest`、`.venv/bin/pre-commit` 等 console script 的 shebang 会写入绝对路径。若它们仍指向已删除或旧的 `.worktrees/*/.venv/bin/python`，`uv run uvicorn ...` 可能加载旧环境/旧代码，表现为当前源码里存在的 API 在运行时 404。遇到这类错位时，在当前 worktree 执行 `uv sync --dev --reinstall`，并用 `head -1 .venv/bin/uvicorn .venv/bin/pytest .venv/bin/pre-commit` 确认路径指向当前 worktree。

### 依赖与架构

- **`src/graphiti_core/` 是本地嵌入副本**：不是通过 pip 安装的 `graphiti-core` 包，而是直接嵌入在项目中的代码。这意味着 Graphiti 升级需要手动同步
- **模型 API 配置有统一回退链**：LLM、Embedder、Reranker 可分别配置 API Key / Base URL；Embedder 和 Reranker 未设置密钥或地址时回退到 LLM 配置。必填密钥缺失会在 `SentinelSettings` 构造阶段失败。
- **重排序不是本地模型**：非 Graphiti 的重排序调用通过 LiteLLM Rerank；Graphiti workflow 仍通过 Graphiti 的 cross_encoder 客户端调用外部 rerank 服务

### 日志系统

- **双输出系统**：`print_*` 函数使用 Rich Console 输出到终端（彩色），`logging.getLogger()` 输出到 RotatingFileHandler 文件日志
- **文件日志自动轮转**：单个日志文件最大 5MB，保留 3 个备份
- **第三方日志静默**：`neo4j`、`httpx`、`urllib3`、`httpcore`、`crewai`、`asyncio` 的日志级别被设为 WARNING

### Flow 执行注意事项

- **`SentinelPipelineFlow.kickoff()` 是同步方法**，但内部包含异步操作（通过 `asyncio.run()` 或直接 await）
- **Graphiti 客户端在每个 Stage 中独立创建和关闭**，不跨 Stage 共享，确保连接不泄漏
- **风险评估路由**：`risk_score > RISK_THRESHOLD` 进入二次评估（含图谱检索），`risk_level == LOW` 直接结束流程
- **`GRAPHITI_DRY_RUN=true`** 时跳过 Neo4j 写入，但 LLM 实体/关系提取仍会执行，用于调试提取效果

### 搜索与检索

- **混合搜索默认使用 `COMBINED_HYBRID_SEARCH_CROSS_ENCODER`**（语义向量 + BM25 + BFS 图遍历 → Cross-Encoder 重排序）
- **主体 Episode 过滤**：搜索时会自动从 `event.raw_content` 提取 `id_number`（如 P01），并只保留包含该主体的 Episode 及其关联结果
- **搜索超时**：`hybrid_search()` 设置了 20 秒超时，超时不会抛异常而是返回空结果

### Milvus 黑名单与事件库

- **事件 collection 必须是静态 schema**：`input_events` 需要使用 `events_schema.py` 定义的字段，并关闭 dynamic fields。旧的动态字段 collection 会在写入前被拒绝。
- **旧动态字段事件库迁移不要直接跑全量 reset**：已有环境若保留了动态字段输入事件 collection，先通过 Attu 或 Milvus API 导出需要保留的事件数据，再只 drop/recreate 事件 collection；`reset_and_seed_demo_state.py` 和 `run_blacklist_kv_demo.py` 启动阶段都会删除 Neo4j 图谱节点，并重置 Sentinel 使用的全部 Milvus demo/store collections，包括黑名单 collections、输入事件记录 collection `input_events` 和 review-action 记录 collection `review_actions`，只适合本地可丢弃数据。
- **旧配置字段会被直接迁移**：旧 `config/config.yaml` 中的 `milvus.stash_collection` 会在自动补齐配置时迁移为 `milvus.input_events_collection`，并删除旧字段；需要继续使用旧 collection 名时，把该值写入新的 `input_events_collection` 字段。
- **黑名单 seed 使用批量接口**：预置 persons、keywords、event samples 时使用 `append_persons()`、`append_keywords()`、`append_events()`。逐条 append 会重复触发 Milvus query/upsert/flush，初始化时间会随种子数量线性放大。
- **先看 demo 初始化阶段计时和 reset summary**：`run_blacklist_kv_demo.py` 的 `[1/3]` 使用 `sentinel.utils.stage_timer` 将初始化计为单一 `reset Neo4j and Milvus demo state` full reset 阶段；完成后会输出 Neo4j 删除数、种子数量和各 Milvus collection 的 dropped/not-found summary。该工具不再额外打印最终 `Duration breakdown` 文本块。
- **demo 黑名单人员是有意 seed**：`P203`、`P204` 用于让样例事件通过人员黑名单进入完整 pipeline；如果该 case 的 Neo4j/Milvus 预期不匹配，优先检查 demo case 期望而不是删除 seed。
- **blacklist stores 的 embedding 已改为 fail-open**：当前事件入库、event sample seed/query 的远程 embedding 若超时，会降级为确定性的本地 fallback 向量并继续写库/检索，而不是直接把整条 demo 卡死或中断。这能提高本地 demo 的可跑性，但在 provider 异常时，相似度质量会下降。
- **store embedder 现已优先走 batch**：`EventSamplesStore.append_events()` 会优先调用 batch embedding，避免 seed event samples 为每条样本单独发起远程请求；如果 batch 路径失败，再统一走 fallback 向量。
- **Milvus `VARCHAR` 上限按字节而不是按字符生效**：像 `pipeline_message` 这类字段即使只截到 512 个中文字符，也可能因 UTF-8 编码后超过 512 字节而被 Milvus 拒绝。结果写回路径必须使用 UTF-8 安全截断，而不是简单的 `text[:512]`。

### LLM 超时边界

- **结构化 JSON LLM 调用有独立上限**：`generate_pipeline_json()` 统一使用 180 秒超时、较小 completion 上限并禁用 thinking；provider 无响应时会在父进程 300 秒 watchdog 前回退。若 profile prompt 较长，排查慢请求时仍要查看该阶段日志。
- **趋势预测长文本生成仍可能成为新的慢点**：标准化链路已经有界，但 dashboard 阶段的长文本生成/趋势预测在 provider 不稳定时仍可能成为后续阻塞源；排查 demo 时不要只盯 `case_01`。

### Runtime profile prompt

- **修改后必须重启**：`get_profile_config()` 按进程缓存 `profile.yaml` 和 23 个 Markdown 模板。运行中编辑文件不会热加载；源码和 Compose 部署都必须提供完整 `config/profile/`。
- **占位符只在渲染时检查**：loader 不预检 `{variable}`。缺失字段、非法 format spec、属性/索引访问或自定义格式化失败会在对应 Stage 变成脱敏的 `PromptRenderError`，终止当前 Pipeline，而不会进入模型 fallback。
- **Graph extraction 不经过 Sentinel 插值**：该 Markdown 原样传给 Graphiti，普通花括号不会触发 `PromptRenderError`。不要按其他 Profile 模板的变量规则排查它。
- **zero-shot 不使用自适应 Profile prompts**：zero-shot 趋势提示词仍由代码维护，并跳过 Dashboard 分类器和 Profile pair 选择。修改 Dashboard 类别 Markdown 不会影响 zero-shot 输出。

### 分类器注意事项

- **Rerank 分类需要可用 API 配置**：`EventClassifier` 默认 `use_rerank=True`；Settings 构造阶段会拒绝缺失必填密钥，运行时 rerank 调用失败时才回退到关键词匹配
- **回退关键词匹配精度有限**：关键词列表集中维护在 `src/sentinel/trend_prediction/classification_taxonomy.py` 中，覆盖通用事件类别和 4 级严重度关键词
- **合并分类**：`_rerank_classify_combined()` 通过一次 API 调用同时完成类别和严重度分类，使用 `CATEGORY:` / `SEVERITY:` 前缀区分

### 消息队列

- 已移除 RabbitMQ；Pipeline 不再依赖外部消息队列。黑名单与输入事件库使用 Milvus，图谱存储仍使用 Neo4j。
