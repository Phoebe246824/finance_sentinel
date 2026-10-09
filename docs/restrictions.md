> 所属项目：[AGENTS.md](../AGENTS.md)

## 禁止事项

以下操作**绝对禁止**：

### 文件与目录

> ⚠️ **默认禁止修改 `src/graphiti_core/` 目录中的文件**。只有当任务明确涉及构图方案、Graphiti 行为适配、图谱写入或检索底层机制时才允许修改，并且必须说明影响范围、扩大验证范围。

> ⚠️ **禁止删除 `docs/` 目录中的报告文档**，它们记录了开发过程中的关键决策

> ⚠️ **禁止修改 `.env` 文件并提交**，该文件已在 `.gitignore` 中

> ⚠️ **禁止提交 `logs/`、`__pycache__/`、`.mypy_cache/`、`.ruff_cache/` 目录中的文件**

> ⚠️ **禁止提交 `frontend/node_modules/`、`frontend/dist/`、`frontend/.env*`（`frontend/.env.example` 除外）和前端包管理缓存**

### 环境与配置

> ⚠️ **禁止硬编码 API 密钥或密码**，所有敏感信息必须通过环境变量读取

> ⚠️ **禁止直接操作生产环境的 Neo4j / Milvus**，仅操作本地 Docker Compose 服务

> ⚠️ **禁止在没有 `GRAPHITI_DRY_RUN=true` 保护的情况下，对生产 Neo4j 执行写入测试**

### 代码与架构

> ⚠️ **禁止绕过 `uv run ruff check` lint 检查强行提交**

> ⚠️ **禁止在 Flow 的 Stage 方法中直接调用外部 API**，必须通过 `src/sentinel/utils/litellm_*` 或对应的 service 模块

> ⚠️ **禁止在 `src/sentinel/main.py` 中新增业务逻辑**，业务逻辑应放在对应的 service 模块中

> ⚠️ **禁止在未获维护者明确批准时新增 RAGFlow 上传、解析、数据集管理或其它外部服务写入行为**；当前 RAGFlow 集成只允许 retrieval API 读取

### 数据库

> ⚠️ **禁止删除 Neo4j 中的已有数据或索引**，除非通过 Graphiti 提供的 API

> ⚠️ **禁止手动修改 `compose/volumes/` 下的持久化数据文件**

### 智能体高风险停下询问

以下情况编码智能体必须先询问维护者：

> ⚠️ 删除、重置或迁移 Neo4j、Milvus、日志、实验结果等数据

> ⚠️ 新增或改变外部服务写入行为

> ⚠️ 改变 `SentinelSettings` 配置语义、密钥回退链或环境变量含义

> ⚠️ 改变数据库 schema、Milvus collection schema 或持久化数据策略

> ⚠️ 改变 pipeline 路由、风险阈值、黑名单过滤语义或构图准入规则，但需求不清

> ⚠️ 准备 push 到远端或覆盖他人未提交改动

### Git 与多人维护

> ⚠️ **禁止编码智能体未经维护者明确授权直接 push 到 `origin/*` 功能分支**。默认只在本地提交并说明 ahead/behind 状态；除非维护者明确要求，不要 reset/revert 覆盖他人提交。
