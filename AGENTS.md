# AGENTS.md — Sentinel Agent Instructions

本文件只面向编码智能体。人类开发者请从 [docs/development.md](docs/development.md) 开始。

## 1. 必读顺序

开始任何代码或文档改动前，按任务范围阅读：

1. [docs/development.md](docs/development.md)
2. [docs/architecture.md](docs/architecture.md)
3. [docs/commands.md](docs/commands.md)
4. [docs/restrictions.md](docs/restrictions.md)
5. 与本次任务直接相关的模块和测试

涉及配置时阅读 [docs/env-vars.md](docs/env-vars.md)。涉及已知坑时阅读 [docs/pitfalls.md](docs/pitfalls.md)。

## 2. 项目边界速查

- `src/sentinel/` 是运行时业务包。
- `src/sentinel/main.py` 负责 CrewAI Flow 编排；新增业务逻辑优先放入领域模块。
- `src/sentinel/pipeline/` 负责 blacklist gate、分类、风险评估、批量构图和 dashboard 等 Stage 级业务逻辑。
- `src/sentinel/blacklist/` 负责黑名单过滤、Milvus stores、输入事件落库和回捞。
- `src/sentinel/graph/` 负责 Graphiti/Neo4j adapter、构图和检索。
- `src/sentinel/trend_prediction/` 负责分类、领域适配、意图分析和趋势预测。
- `src/sentinel/web/` 负责 Web 看板 API、实时分析任务管理、结果序列化和 SPA 挂载。
- `src/sentinel/utils/` 只放跨模块共享工具。
- `src/graphiti_core/` 是 vendored Graphiti；默认不改。构图方案、Graphiti 行为适配、图谱写入或检索底层任务可以修改，但必须说明影响范围并扩大验证。
- `scripts/` 是本地运维、检查、演示脚本。

## 3. 工作树规则

- 开始前运行 `git status -sb` 并确认当前分支。
- 多人或多智能体并行时，必须从 `main` 派生分支并在 `.worktrees/` 下创建隔离工作树。
- 单智能体小改动可在当前上下文处理，但必须保护已有未提交改动。
- 不修改、删除、reset、revert 不属于本任务的改动。
- 如果遇到与本任务冲突的他人未提交改动，停下询问维护者。

## 4. 高风险操作必须先问

以下情况必须先询问维护者，不能自主继续：

- 删除、重置或迁移 Neo4j、Milvus、日志、实验结果等数据。
- 修改 `src/graphiti_core/` 且任务目标未明确涉及 Graphiti 行为。
- 新增或改变外部服务写入行为。
- 改变 `SentinelSettings` 配置语义、密钥回退链或环境变量含义。
- 改变数据库 schema、Milvus collection schema 或持久化数据策略。
- 改变 pipeline 路由、风险阈值、黑名单过滤语义或构图准入规则，但需求不清。
- 准备 push 到远端。
- 需要覆盖或丢弃他人改动。

## 5. 开发规则

- Python 版本基线是 3.13。
- 依赖和命令通过 `uv` 管理。
- 项目内部运行时代码统一使用 `sentinel.*` 导入。
- 不新增根目录兼容壳。
- 配置统一通过 `sentinel.config.SentinelSettings`。
- 测试中构造 `SentinelSettings` 时显式隔离本地配置来源，避免依赖未跟踪的 `config/config.yaml` 或 `.env`。
- 新增命令、环境变量、模块边界或禁止事项时，同步更新对应 `docs/` 文件。

## 6. 验证规则

- 每次代码变更至少运行相关测试。
- 影响共享模型、配置、pipeline、Graphiti adapter、Milvus stores、LiteLLM 工具函数或公共脚本时，扩大到相关测试组或 `uv run pytest tests/ -m "not integration"`。
- 文档-only 变更通常运行 pre-commit 即可。
- 集成测试只在明确具备 Docker、Neo4j、Milvus、LLM/Rerank API 等条件时运行。
- 如果验证无法运行或失败，交付说明必须写明命令、失败原因和判断。

## 7. 提交规则

- 提交消息必须使用英文 Angular Conventional Commits。
- 示例：`docs(agent): update agent instructions`。
- 默认只本地提交，不直接 push 到 `origin/*`，除非维护者明确要求。
- 提交前运行 pre-commit；如果 hook 修改文件，重新暂存并再次提交。

## 8. 常用入口

| 任务 | 文档 |
|---|---|
| 开发准则 | [docs/development.md](docs/development.md) |
| 环境搭建 | [docs/setup.md](docs/setup.md) |
| 常用命令 | [docs/commands.md](docs/commands.md) |
| 代码规范 | [docs/conventions.md](docs/conventions.md) |
| 架构边界 | [docs/architecture.md](docs/architecture.md) |
| 环境变量 | [docs/env-vars.md](docs/env-vars.md) |
| 已知陷阱 | [docs/pitfalls.md](docs/pitfalls.md) |
| 禁止事项 | [docs/restrictions.md](docs/restrictions.md) |
