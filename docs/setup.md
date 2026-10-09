> 所属项目：[AGENTS.md](../AGENTS.md)

## 开发环境搭建

### 前置依赖

- **Python**: 3.13+
- **uv**: 0.11+（依赖管理与脚本运行器，安装方式见 https://docs.astral.sh/uv/）
- **Node.js**: 20.19.0+（仅开发 Art Design Pro 前端或本地构建前端时需要）
- **pnpm**: 10.17.1+（仅开发 `frontend/` 或本地构建前端时需要）
- **Docker** + Docker Compose v2.20+（用于完整 Web 部署、依赖服务或可选 RAGFlow；可用 `docker compose version` 检查）
- **Git**

### 通用准备

先克隆仓库并准备结构化配置和密钥文件：

```bash
git clone <repo-url> && cd finance_sentinel

test -f config/config.yaml || cp config/config.example.yaml config/config.yaml
test -f .env || cp .env.example .env
```

编辑 `.env`，至少填入：

- `LLM_API_KEY`
- `DASHBOARD_ADMIN_PASSWORD`（Web 看板登录需要；未设置时登录会被禁用）

`EMBEDDER_API_KEY`、`RERANKER_API_KEY` 仅在嵌入或重排序服务不复用 `LLM_API_KEY` 时单独配置。启用 RAGFlow 时，只把 `RAGFLOW_API_KEY` 放进 `.env`；`enabled`、`base_url`、`dataset_id(s)`、检索阈值等非敏感运行参数写入 `config/config.yaml` 的 `ragflow` 段。

`SentinelSettings` 读取结构化配置时会自动补齐 `config/config.yaml` 中缺失的默认词条。Docker 部署默认使用 DaoCloud、清华 PyPI 和 npmmirror 等中国境内镜像/包源；如需切回官方源或内网源，可通过 `SENTINEL_*_BASE_IMAGE`、`*_IMAGE`、`UV_DEFAULT_INDEX` 和 `NPM_REGISTRY` 等变量覆盖，完整列表见 [env-vars.md](env-vars.md)。

### 方式一：完整 Docker Web 部署（推荐）

`docker/docker-compose.yaml` 面向最简部署入口，会同时启动 Sentinel Web、Sentinel API、Neo4j、Milvus、etcd 和 MinIO：

```bash
docker compose -f docker/docker-compose.yaml up -d --build
docker compose -f docker/docker-compose.yaml ps
```

访问入口：

- Sentinel Web: `http://localhost:8080`
- Neo4j Browser: `http://localhost:7474`（默认 `neo4j/pa55w0rd`）
- Milvus WebUI: `http://localhost:9091/webui/`

Compose 会读取 `.env` 作为 `sentinel-api` 的运行时密钥来源，但不会把 `.env` 打进镜像；`config/` 会挂载到 API 容器并通过 `/app/config/config.yaml` 读取结构化配置。容器内 `NEO4J_URI`、`MILVUS_URI` 会自动指向 Compose service name，避免误连容器内的 `localhost`。

常用排查命令：

```bash
docker compose -f docker/docker-compose.yaml logs -f sentinel-api
docker compose -f docker/docker-compose.yaml logs -f sentinel-web
docker compose -f docker/docker-compose.yaml logs -f neo4j
```

停止完整部署但保留 Neo4j、Milvus 等持久化数据：

```bash
docker compose -f docker/docker-compose.yaml down
```

不要在共享或需要保留数据的环境使用 `docker compose -f docker/docker-compose.yaml down -v`，该命令会删除本地数据卷。

### 方式二：仅启动依赖服务

如果希望 Python 后端或终端 Pipeline 在宿主机运行，只用 Docker 提供 Neo4j、Milvus、etcd 和 MinIO：

```bash
docker compose -f docker/compose/dependencies.yaml up -d
docker compose -f docker/compose/dependencies.yaml ps
```

也可以只启动单个依赖服务：

```bash
docker compose -f docker/compose/dependencies.yaml up -d neo4j
docker compose -f docker/compose/dependencies.yaml up -d milvus
```

依赖-only 模式下，本地进程默认连接：

- Neo4j: `bolt://localhost:7687`
- Milvus: `http://localhost:19530`

### 方式三：本地 FastAPI 后端 + 前端开发服务

该方式适合开发 Web API 或 Art Design Pro 前端。先安装依赖：

```bash
uv venv
uv sync --dev
uv run pre-commit install

cd frontend
pnpm install --frozen-lockfile
cp .env.example .env.development
cd ..
```

启动依赖服务后，在两个终端分别运行：

```bash
uv run uvicorn sentinel.dashboard:create_dashboard_app --factory --reload --port 8080
```

```bash
cd frontend
pnpm dev
```

`frontend/.env.example` 默认把 Vite 的 `/api` 代理到 `http://127.0.0.1:8080`。本地开发入口通常是 Vite 输出的地址；FastAPI 仍在 `http://127.0.0.1:8080` 提供 API。

### 方式四：构建前端后由 FastAPI 挂载

该方式适合验证生产前端产物，但仍在宿主机运行 Python 后端：

```bash
docker compose -f docker/compose/dependencies.yaml up -d
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..

uv run uvicorn sentinel.dashboard:create_dashboard_app --factory --port 8080
```

访问 `http://localhost:8080`。如果 `frontend/dist` 不存在，FastAPI 会返回占位 HTML 提示，而不是完整 SPA。

### 方式五：终端 Pipeline

终端模式适合直接输入消息并观察 CrewAI Flow：

```bash
uv venv
uv sync --dev
docker compose -f docker/compose/dependencies.yaml up -d
uv run sentinel
```

也可以使用显式模块入口：

```bash
uv run python -m sentinel.main
```

### 可选：RAGFlow profile

RAGFlow 是只读外部知识检索源，不替代 Graphiti 搜索，也不生成最终分析结果。需要本地 RAGFlow 时，在 `.env` 填入 `RAGFLOW_API_KEY`，在 `config/config.yaml` 的 `ragflow` 段启用并配置 dataset：

```bash
docker compose -f docker/compose/dependencies.yaml --profile ragflow up -d
```

访问入口：

- RAGFlow Web: `http://127.0.0.1:8088`
- RAGFlow API: `http://127.0.0.1:9380`

启用后可检查 retrieval 配置和检索连通性：

```bash
uv run scripts/check_ragflow_retrieval.py "强降雨 临时安置点 交通管制 物资调度"
```

完整说明见 [ragflow.md](ragflow.md)。

### 可选：Attu Milvus 管理界面

Attu 只用于本地查看 Milvus collection，不是 Sentinel 运行必需服务：

```bash
docker compose -f docker/compose/dependencies.yaml --profile attu up -d
```

访问 `http://localhost:8000`。

### 验证与自检

依赖服务和模型配置可用以下脚本检查。模型 live 检查会消耗极少额度，执行前会要求确认；只想检查静态配置时使用 `--static-only`：

```bash
uv run scripts/check_service_health.py
uv run scripts/check_model_config.py --static-only
```

常用测试和质量门禁见 [commands.md](commands.md)。文档或代码改动提交前通常运行：

```bash
uv run pre-commit run --all-files
```
