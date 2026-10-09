> 所属项目：[AGENTS.md](../AGENTS.md)

## 常用命令

### 安装依赖

```bash
uv sync --dev

# 可选：安装 ArtD 前端依赖
cd frontend && pnpm install --frozen-lockfile
```

### 启动系统

```bash
# 终端交互式 Pipeline（分析输入消息）
uv run sentinel

# 可选参数：指定日志目录
uv run sentinel --log-dir /path/to/logs

# 显式模块入口
uv run python -m sentinel.main
```

### 启动 Web 看板

Web 看板登录需要先设置 `DASHBOARD_ADMIN_PASSWORD`；未设置时后端会禁用登录，避免使用源码内置共享密码。用户名默认来自 `config/config.yaml` 的 `dashboard.admin_user`（默认 `admin`）。

```bash
# 使用 factory 模式启动 FastAPI 看板
uv run uvicorn sentinel.dashboard:create_dashboard_app --factory --reload --port 8080

# 另开终端启动 ArtD 前端开发服务，/api 默认代理到 127.0.0.1:8080
cd frontend && pnpm dev
```

常用前端入口：

- `/#/sentinel/dashboard`：常规 Web 总览。
- `/#/sentinel/data-screen`：Sentinel 风险态势大屏，复用 `GET /api/dashboard/overview` 的真实统计数据；桌面按 1920x1080 画布缩放，1320px 以下改为纵向滚动布局。
- `/#/sentinel/analysis/workbench`：风险分析工作台，真实分析完成后展示持久化结果、图谱构建指标，并通过 `GET /api/graph/events/{event_id}` 加载事件图谱。
- `/#/sentinel/graph/person`：人员图谱查询，输入人员 ID 后调用 `GET /api/graph/person`，以交互式 SVG 图谱展示 Neo4j 一跳关系。
- `/#/sentinel/blacklist`：黑名单管理，仅 `R_SUPER` / `R_ADMIN` 可见；人员和关键词支持批量编辑并保护未保存变更，典型事件逐条维护。

黑名单管理接口位于 `/api/blacklist/*`，复用 Dashboard 登录认证并额外检查 `R_SUPER` / `R_ADMIN` 管理角色。人员和关键词通过 changeset 批量保存，空白人员 ID 或关键词会被拒绝；典型事件逐条保存，只有 `summary` 用于 embedding 计算，`description` 仅作为管理备注；启停和删除典型事件均携带 `expected_updated_at` 做乐观冲突检查。

`设置` 页面提供当前已生效依赖服务和模型配置的可用性检测按钮，未保存的表单改动不会参与检测。服务检测只对 Neo4j 和 Milvus 做只读探测；模型检测会向当前配置的 LLM、Embedder 和 Reranker 发起极小真实请求，可能消耗少量模型服务额度。

构建前端产物后，FastAPI 看板会自动挂载 `frontend/dist`：

```bash
cd frontend && pnpm build
uv run uvicorn sentinel.dashboard:create_dashboard_app --factory --port 8080
```

### ArtD Web 看板真实分析 PoC

```bash
uv run uvicorn sentinel.dashboard:create_dashboard_app --factory --reload --port 8080
cd frontend && pnpm dev
```

分析结果写入 Milvus 输入事件 collection；运行中的任务状态只保存在后端进程内存中。当前 Web 分析不支持取消。

### Docker 相关

```bash
# 构建并启动完整 Web 部署（Sentinel Web + API + Neo4j + Milvus + etcd + MinIO）
docker compose -f docker/docker-compose.yaml up -d --build

# 访问 Web 看板
# http://localhost:8080

# 仅启动默认依赖服务（Neo4j + Milvus + etcd + MinIO）
docker compose -f docker/compose/dependencies.yaml up -d

# 仅启动特定依赖服务
docker compose -f docker/compose/dependencies.yaml up -d neo4j
docker compose -f docker/compose/dependencies.yaml up -d milvus

# 启动依赖服务并附加本地 RAGFlow profile（RAGFlow Web/API 只绑定 127.0.0.1）
docker compose -f docker/compose/dependencies.yaml --profile ragflow up -d

# 可选：启动依赖服务并附加 Attu Milvus 管理界面
docker compose -f docker/compose/dependencies.yaml --profile attu up -d

# 停止容器但保留持久化数据
docker compose -f docker/docker-compose.yaml down

# 如需清理本地可丢弃数据，先确认不会误删 Neo4j/Milvus/RAGFlow 持久化数据，再使用 -v
# docker compose -f docker/docker-compose.yaml down -v

# 查看服务状态
docker compose -f docker/docker-compose.yaml ps

# 查看日志
docker compose -f docker/docker-compose.yaml logs -f sentinel-api
docker compose -f docker/docker-compose.yaml logs -f sentinel-web
docker compose -f docker/docker-compose.yaml logs -f neo4j
```

### Milvus 调试

```bash
# 访问 Milvus 内置 Web UI
# http://localhost:9091/webui/

# 可选：启动并访问 Attu Web UI 管理 Milvus
docker compose -f docker/compose/dependencies.yaml --profile attu up -d
# http://localhost:8000

# 查看 Milvus collection 列表
# 通过 Attu UI 或 pymilvus API 查看
```

### RAGFlow 检索自检

```bash
# 启动本地 RAGFlow profile
docker compose -f docker/compose/dependencies.yaml --profile ragflow up -d

# RAGFLOW_API_KEY 放在 .env；enabled/base_url/dataset_id(s) 等放在 config/config.yaml

# 检查当前 RAGFlow 配置是否能检索
uv run scripts/check_ragflow_retrieval.py "强降雨 临时安置点 交通管制 物资调度"
```

完整配置说明见 [RAGFlow 集成](ragflow.md)。

### 黑名单 Demo

```bash
# 重置 Neo4j、重置 Sentinel 使用的全部 Milvus demo/store collections，并预置黑名单测试数据
uv run scripts/reset_and_seed_demo_state.py

# 自动回放 blacklist/Milvus/filter 功能样例；启动阶段会执行同样的 full demo reset
uv run scripts/run_blacklist_kv_demo.py
```

`reset_and_seed_demo_state.py` 会删除 Neo4j 图谱节点，并重置 Sentinel 使用的全部 Milvus demo/store collections，包括黑名单 collections、输入事件记录 collection `input_events` 和 review-action 记录 collection `review_actions`；仅用于本地可丢弃测试数据。

`run_blacklist_kv_demo.py` 的 `[1/3]` 会复用同一 full demo reset：删除 Neo4j 图谱节点、重置 Sentinel 使用的全部 Milvus demo/store collections（包括黑名单 collections、`input_events` 和 `review_actions`），并预置黑名单数据。该步骤使用 `sentinel.utils.stage_timer` 将初始化计为单一 `reset Neo4j and Milvus demo state` 阶段；TTY 终端下会用 Rich live 刷新当前阶段耗时，阶段完成后固定显示，并输出 reset summary（Neo4j 删除数、Milvus drop/not-found 状态和 seed 数量），不再额外打印最终的 `Duration breakdown` 文本块。

通用黑名单 demo seed 中 `P203`、`P204` 是黑名单人员样本；命中黑名单的样例会进入完整 pipeline 并构图。当前 `input_events` 是全量输入事件库，批量补图只回捞 `is_graph_built=false` 的历史候选；后续样例应通过图谱检索复用已构图的历史事件，并校验 Milvus 批量补图不会重复处理已构图事件。

黑名单种子写入应使用 stores 的批量接口：`append_persons()`、`append_keywords()`、`append_events()`。不要在脚本中逐条循环调用单条 append，否则会把 Milvus query/upsert/flush 的网络成本线性放大。

### 测试

```bash
# 运行全部非集成测试
uv run pytest tests/ -m "not integration" -v

# 运行特定测试文件
uv run pytest tests/test_blacklist_filter.py -v

# main.py 轻量重构后的主流程回归
uv run pytest tests/test_main_blacklist_workflow.py tests/test_milvus_stash_flow.py -v

# 抽离后的 pipeline / graph search helper 回归
uv run pytest tests/test_pipeline_classification.py tests/test_pipeline_risk.py tests/test_pipeline_dashboard.py tests/test_graph_search_helpers.py -v

# Web 看板与真实分析任务回归
uv run pytest tests/test_config.py tests/test_dashboard_app.py tests/test_dashboard_artd_api.py tests/test_graph_person_graph.py tests/test_graph_query_client.py tests/test_web_analysis_tasks.py tests/test_web_serialization.py tests/test_web_settings_service.py -v

# 运行集成测试前先确认本地 Docker/Neo4j/Milvus/LLM 配置可用
RUN_BLACKLIST_DEMO_INTEGRATION=1 uv run pytest tests/test_blacklist_kv_demo_integration.py -v

# 运行并生成覆盖率报告（需安装 pytest-cov）
uv run pytest tests/ --cov=sentinel
```

### 代码质量

```bash
# 安装 Git pre-commit hooks
uv run pre-commit install

# 手动运行全部 hooks
uv run pre-commit run --all-files

# Python 语法编译检查
uv run python -m py_compile $(find src scripts tests -name '*.py')

# 前端 lint 与构建检查
cd frontend && pnpm exec eslint src/api/sentinel src/router/modules src/views/about src/views/settings src/views/sentinel src/utils/constants --max-warnings=0
cd frontend && pnpm build
```

pre-commit 会调用 Ruff 自动处理格式化、导入排序和可自动修复 lint。如果 hook 修改文件，重新 `git add` 后再次提交。
