> 所属项目：[AGENTS.md](../AGENTS.md)

## 环境变量说明

配置由 `sentinel.config.SentinelSettings` 统一读取和校验。推荐分层：

- `config/config.yaml`：非密、结构化配置，示例见 [`config/config.example.yaml`](../config/config.example.yaml)。
- `.env`：密钥和本地服务凭据占位。
- 环境变量：最高优先级，适合 CI、容器和临时覆盖。

加载优先级为：代码默认值 < 固定结构化配置文件 `config/config.yaml` < `.env` < 进程环境变量 < 显式构造参数。项目约定上，`.env` 只放密钥和本地服务凭据；非敏感结构化配置应写入 `config/config.yaml`。

`SentinelSettings` 固定读取项目根目录下的 `config/config.yaml`。读取该结构化配置文件时会以 `config/config.example.yaml` 为模板自动创建缺失文件，并补齐已有文件中缺失的非敏感配置项；已有用户配置值不会被覆盖。
旧版 `milvus.stash_collection` 会被直接迁移为 `milvus.input_events_collection` 并从配置文件中删除；需要继续使用原 collection 名时，把该名称保留在新的 `input_events_collection` 字段中。

Web 看板中的 `设置` 页面会沿用同一套配置边界：

- 非密结构化配置保存到 `config/config.yaml`
- 密钥类配置保存到 `.env`
- 保存成功后，只会影响之后新建的分析任务；已经运行中的任务继续使用创建时捕获的配置快照
- Milvus 连接、token 或输入事件 collection 的切换会在存在运行中任务时被拒绝，避免运行任务写入旧目标而看板读取新目标
- 保存时会移除 `.env` 中由设置页负责的非密覆盖项，让 `config/config.yaml` 成为重启后的来源；如果同类字段来自进程环境变量，请先移除该覆盖再通过设置页保存

Sentinel 领域配置固定从 `config/profile` 读取，不通过 `config/config.yaml` 或环境变量
改写路径。这里的 `profile` 指 Sentinel 领域配置目录，和 Docker Compose 的
`--profile` / `profiles` 概念无关。

下表列出 `SentinelSettings` 支持的环境变量名。CI、容器和临时调试可以用进程环境变量覆盖；本地 `.env.example` 只示例密钥和服务凭据。

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` / `NEO4J_DATABASE` | Neo4j 连接 | bolt://localhost:7687, user `neo4j` |
| `GRAPHITI_DRY_RUN` | 设为 true 跳过 Neo4j 写入，LLM 提取仍会执行 | false |
| `GRAPHITI_EPISODE_SOURCE` | Graphiti Episode source 类型 | message |
| `LLM_PROVIDER` | 非 Graphiti 文本生成与 Embedding 的 LiteLLM provider 前缀；OpenAI-compatible 私有/第三方 endpoint 通常使用 `openai`，裸模型名会自动转为 `openai/<model>` | openai |
| `LLM_MODEL` | 聊天模型名称 | gpt-4o |
| `LLM_API_KEY` | LLM API 密钥 | - (必填) |
| `LLM_BASE_URL` | LLM API 地址 | https://api.openai.com/v1 |
| `EMBEDDER_MODEL` | 嵌入模型名称 | BAAI/bge-m3 |
| `EMBEDDER_API_KEY` | 嵌入 API 密钥 | 未设置时 fallback 到 LLM_API_KEY |
| `EMBEDDER_API_BASE` | 嵌入 API 地址 | 未设置时 fallback 到 LLM_BASE_URL |
| `EMBEDDING_DIM` | 嵌入向量维度，需与 Milvus 事件 collection 维度一致 | 1024 |
| `RERANKER_MODEL` | 重排序模型 | BAAI/bge-reranker-v2-m3 |
| `RERANKER_API_KEY` | 重排序 API 密钥 | 未设置时 fallback 到 LLM_API_KEY |
| `RERANKER_BASE_URL` | 重排序 API 地址 | 未设置时 fallback 到 LLM_BASE_URL |
| `SEARCH_NUM_RESULTS` | 默认搜索返回数 | 10 |
| `RISK_SEARCH_NUM_RESULTS` | 风险评估搜索返回数 | 20 |
| `SEARCH_MIN_SCORE` | 搜索相关性阈值（0.0 关闭） | 0.0 |
| `RISK_THRESHOLD` | 风险评分阈值 | 0.7 |
| `MILVUS_URI` / `MILVUS_TOKEN` | Milvus 连接（黑名单存储 + 输入事件库使用） | http://localhost:19530, 空 |
| `MILVUS_INPUT_EVENTS_COLLECTION` | Milvus 输入事件 collection 名称 | input_events |
| `KV_TTL_DAYS` | 输入事件记录过期天数 | 90 |
| `STASH_SEMANTIC_TOP_K` | Milvus 事件库语义召回数量 | 10 |
| `STASH_RERANK_MIN_SCORE` | Milvus 事件库回捞 rerank 最低分 | 0.7 |
| `STASH_RERANK_ENABLED` | 是否启用 Milvus 事件库回捞 rerank | true |
| `BATCH_MAX_PER_PERSON` | 批量构图时每人最多取事件数 | 20 |
| `BLACKLIST_EVENT_SIMILARITY_THRESHOLD` | 事件相似度阈值 | 0.5 |
| `BLACKLIST_PERSON_MIN_HITS` | 人员命中次数阈值 | 1 |
| `DASHBOARD_ADMIN_USER` | Web 看板登录用户名 | admin |
| `DASHBOARD_ADMIN_PASSWORD` | Web 看板登录密码；未设置时禁用登录，避免源码内置共享密码 | - |
| `DASHBOARD_ACCESS_TOKEN` / `DASHBOARD_REFRESH_TOKEN` | Web 看板 token；未设置时进程启动时随机生成 | 随机 |
| `RAGFLOW_API_KEY` | RAGFlow API Key；其它 RAGFlow 运行参数在 `config/config.yaml` 的 `ragflow` 段配置 | - |
| `RAGFLOW_ENABLED` | 是否启用 RAGFlow 检索；本地开发优先写入 `config/config.yaml` | false |
| `RAGFLOW_BASE_URL` | RAGFlow API 地址；本地开发优先写入 `config/config.yaml` | http://127.0.0.1:9380 |
| `RAGFLOW_DATASET_ID` / `RAGFLOW_DATASET_IDS` | RAGFlow Dataset ID；`RAGFLOW_DATASET_IDS` 逗号分隔并优先 | - |
| `RAGFLOW_TOP_K` | 返回检索片段数量，同时作为 retrieval `page_size` | 5 |
| `RAGFLOW_SIMILARITY_THRESHOLD` | RAGFlow 相似度阈值 | 0.2 |
| `RAGFLOW_VECTOR_SIMILARITY_WEIGHT` | RAGFlow 向量相似度权重 | 0.7 |
| `RAGFLOW_TIMEOUT_SECONDS` | RAGFlow retrieval 请求超时秒数 | 15.0 |
| `RAGFLOW_MAX_CONTEXT_CHARS` | 注入 prompt 的 RAGFlow 证据字符上限 | 4000 |
| `RAGFLOW_FAIL_OPEN` | retrieval 失败时是否继续原流程；false 用于调试/测试暴露失败 | true |

必填密钥缺失或为空时，`get_settings()` 首次构造会失败；开发和测试环境也需要提供真实测试密钥或在单测中显式构造 `SentinelSettings(_env_file=None, ...)`。

## Docker Compose Web 部署变量

`docker/docker-compose.yaml` 用于完整 Web 部署。Compose 会读取 `.env` 作为
`sentinel-api` 的密钥来源，但不会把 `.env` 打进镜像。`config/` 会挂载到
`/app/config`，容器内固定读取 `/app/config/config.yaml` 作为结构化配置。

为避免容器内误连 `localhost`，`sentinel-api` service 会覆盖以下容器网络地址：

| 变量 | Compose 覆盖值 | 说明 |
|------|----------------|------|
| `NEO4J_URI` | `bolt://neo4j:7687` | 连接 Compose 内 Neo4j service |
| `MILVUS_URI` | `http://milvus:19530` | 连接 Compose 内 Milvus service |
| `RAGFLOW_BASE_URL` | `${RAGFLOW_BASE_URL:-http://ragflow:9380}` | 启用 RAGFlow profile 时默认连接 Compose 内 RAGFlow service，可通过 `.env` 或进程环境覆盖到外部 RAGFlow |

`RAGFLOW_BASE_URL` 指向 Compose service name 不代表默认启用 RAGFlow；是否检索仍由
`config/config.yaml` 中的 `ragflow.enabled` 或对应环境变量控制。默认未启用 RAGFlow
时，不需要启动 `ragflow` profile。完整 Web Compose 中该环境变量优先级高于
`config/config.yaml` 的 `ragflow.base_url`，因此需要连接外部 RAGFlow 时应显式设置
`RAGFLOW_BASE_URL` 覆盖默认容器内地址。

根 Compose 默认使用中国境内可访问性更好的镜像和包源；如部署环境需要官方源或内网源，可以通过以下变量覆盖。它们只影响 Docker 构建或 Compose 镜像选择，不经过 `SentinelSettings`：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SENTINEL_WEB_PORT` | `sentinel-web` 绑定到宿主机的 HTTP 端口 | 8080 |
| `SENTINEL_PYTHON_BASE_IMAGE` | `sentinel-api` Python 基础镜像 | docker.m.daocloud.io/library/python:3.13-slim-bookworm |
| `SENTINEL_NODE_BASE_IMAGE` | `sentinel-web` 前端构建基础镜像 | docker.m.daocloud.io/library/node:20.19-bookworm-slim |
| `SENTINEL_NGINX_BASE_IMAGE` | `sentinel-web` Nginx 运行时基础镜像 | docker.m.daocloud.io/library/nginx:1.27-alpine |
| `UV_DEFAULT_INDEX` | API 镜像构建时 uv/pip 默认 Python 包索引 | https://pypi.tuna.tsinghua.edu.cn/simple |
| `UV_VERSION` | API 镜像构建时安装的 uv 版本 | 0.11.16 |
| `NPM_REGISTRY` | Web 镜像构建时 pnpm/npm registry | https://registry.npmmirror.com |
| `ETCD_IMAGE` | Milvus 依赖 etcd 镜像 | quay.m.daocloud.io/coreos/etcd:v3.5.25 |
| `MILVUS_MINIO_IMAGE` | Milvus 依赖 MinIO 镜像 | docker.m.daocloud.io/minio/minio:RELEASE.2025-04-22T22-12-26Z |
| `MILVUS_IMAGE` | Milvus standalone 镜像 | docker.m.daocloud.io/milvusdb/milvus:v2.6.15 |
| `ATTU_IMAGE` | Attu 镜像 | docker.m.daocloud.io/zilliz/attu:v2.5.6 |
| `NEO4J_IMAGE` | Neo4j 镜像 | docker.m.daocloud.io/library/neo4j:5.26.0 |

RAGFlow 只作为外部知识检索源使用，不生成风险结论、意图分析或趋势预测。`ragflow.fail_open: true` 时，HTTP/JSON/API envelope 失败会记录 warning 并继续原流程；成功但无 chunks 时不向 prompt 注入占位内容。`ragflow.enabled`、`ragflow.base_url`、`ragflow.dataset_id(s)`、检索阈值和 prompt 字符上限属于非敏感结构化配置，应写入 `config/config.yaml`，不要写入 `.env`。

## 本地 RAGFlow Docker profile 凭据

以下变量只用于本地 Docker profile 的依赖服务密码，可放在 `.env` 或进程环境中供 `docker compose` 读取，不经过 `SentinelSettings` 解析：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `RAGFLOW_MYSQL_PASSWORD` | 本地 RAGFlow MySQL 密码 | 示例值 |
| `RAGFLOW_REDIS_PASSWORD` | 本地 RAGFlow Redis 密码 | 示例值 |
| `RAGFLOW_MINIO_PASSWORD` | 本地 RAGFlow MinIO 密码 | 示例值 |
| `RAGFLOW_ELASTIC_PASSWORD` | 本地 RAGFlow Elasticsearch 密码 | 示例值 |

本地 RAGFlow Docker profile 还支持以下 compose 覆盖变量。它们不经过 `SentinelSettings`，也不在 `.env.example` 中作为默认入口展示；需要临时覆盖时可在 shell 或部署环境中传给 `docker compose`：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `RAGFLOW_IMAGE` | RAGFlow 服务镜像 | docker.m.daocloud.io/infiniflow/ragflow:v0.26.1 |
| `RAGFLOW_MYSQL_IMAGE` | RAGFlow MySQL 镜像 | docker.m.daocloud.io/library/mysql:8.0.39 |
| `RAGFLOW_REDIS_IMAGE` | RAGFlow Redis 镜像 | docker.m.daocloud.io/library/redis:7-alpine |
| `RAGFLOW_MINIO_IMAGE` | RAGFlow MinIO 镜像 | docker.m.daocloud.io/minio/minio:RELEASE.2025-04-22T22-12-26Z |
| `RAGFLOW_ELASTICSEARCH_IMAGE` | RAGFlow Elasticsearch 镜像 | elastic.m.daocloud.io/elasticsearch/elasticsearch:8.11.3 |
| `RAGFLOW_ES_INIT_IMAGE` | RAGFlow Elasticsearch 数据目录初始化镜像 | docker.m.daocloud.io/library/alpine:3.20 |
| `RAGFLOW_WEB_PORT` | RAGFlow Web 本地 loopback 端口 | 8088 |
| `RAGFLOW_API_PORT` | RAGFlow API 本地 loopback 端口 | 9380 |
| `RAGFLOW_MYSQL_DATABASE` | RAGFlow MySQL 数据库名 | rag_flow |
| `RAGFLOW_MINIO_USER` | RAGFlow MinIO 本地用户名 | ragflow-local |
| `RAGFLOW_ES_JAVA_OPTS` | RAGFlow Elasticsearch JVM 参数 | -Xms1g -Xmx1g |
| `TZ` | RAGFlow 容器时区 | Asia/Shanghai |

前端联调环境变量维护在 [`frontend/.env.example`](../frontend/.env.example)，通常复制到 `frontend/.env.development` 后供 Vite 读取；它们不经过 `SentinelSettings` 解析：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `VITE_VERSION` | 前端应用版本标识 | 0.1.0 |
| `VITE_PORT` | Vite 本地开发端口 | 3006 |
| `VITE_BASE_URL` | 前端路由 base/public path | `/` |
| `VITE_ACCESS_MODE` | 前端访问模式标记；当前 Sentinel 面板使用 `frontend` | `frontend` |
| `VITE_WITH_CREDENTIALS` | 浏览器请求是否携带 credentials | false |
| `VITE_OPEN_ROUTE_INFO` | 是否展示路由调试信息 | false |
| `VITE_LOCK_ENCRYPT_KEY` | 前端锁屏本地加密 key 示例值 | `s3cur3k3y4adpro` |
| `VITE_API_URL` | 前端请求使用的 API base path | `/` |
| `VITE_API_PROXY_URL` | Vite 开发代理目标地址（用于把 `/api` 转发到 FastAPI） | `http://127.0.0.1:8080` |
| `VITE_DROP_CONSOLE` | 是否在构建中移除 console 输出 | false |

`RERANKER_MODEL` / `RERANKER_API_KEY` / `RERANKER_BASE_URL` 不拆分。它们是跨场景覆盖值：未设置时，所有非 Graphiti 内部的重排序调用统一回退到 `BAAI/bge-reranker-v2-m3`、`LLM_BASE_URL` 和 `LLM_API_KEY`；一旦显式设置，所有场景都使用同一组覆盖值。

非 Graphiti 的文本生成、Embedding、Rerank 调用统一通过 `sentinel.utils.litellm_text`、`sentinel.utils.litellm_embedding`、`sentinel.utils.litellm_rerank`；Graphiti 内部仍使用 Graphiti 原生 `LLMClient`、`EmbedderClient`、`CrossEncoderClient`。

`LLM_PROVIDER` 不是服务商展示名，而是 LiteLLM 的路由前缀。比如文本或 Embedding 模型配置为 `Qwen3-Embedding-8B`、`BAAI/bge-m3` 或 `Qwen/Qwen2.5-72B-Instruct` 时，非 Graphiti 调用会按 `LLM_PROVIDER` 自动转换为 `openai/Qwen3-Embedding-8B`、`openai/BAAI/bge-m3` 或 `openai/Qwen/Qwen2.5-72B-Instruct`；已显式写成 `openai/...` 等 LiteLLM provider 前缀的模型名会保持不变。

LiteLLM 的 Rerank API 走 `/v1/rerank` 风格接口，裸 `RERANKER_MODEL` 会由 `sentinel.utils.litellm_rerank` 转换为 `jina_ai/<model>`；已显式写成 `jina_ai/...`、`cohere/...` 等 LiteLLM rerank provider 前缀时保持不变。
