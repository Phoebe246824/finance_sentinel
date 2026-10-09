# 贡献指南

感谢关注 Sentinel！本文档说明如何搭建环境、提交变更和参与审查。

## 环境准备

- Python 3.13，依赖与命令通过 [uv](https://docs.astral.sh/uv/) 管理：`uv sync`
- 前端：Node.js ≥ 20.19，pnpm 10（`cd frontend && pnpm install`）
- 本地服务（Neo4j / Milvus / LLM API）仅在运行集成测试或真实分析时需要；
  单元测试全部离线运行。

环境搭建细节见 [docs/setup.md](docs/setup.md)，常用命令见 [docs/commands.md](docs/commands.md)。

## 开发工作流

1. 从 `main` 派生功能分支。
2. 完成变更后确认：
   - `uv run pre-commit run --all-files` 通过（ruff 检查与格式化）；
   - `uv run pytest tests/ -m "not integration"` 全绿；
   - 前端变更需 `pnpm lint` 与 `pnpm build` 通过。
3. 提交 Pull Request。CI 会自动执行上述检查。

集成测试（标记 `integration`）需要真实 Milvus / Neo4j / LLM 服务，
维护者会在评审时决定是否要求补充集成验证。

## 提交信息

使用英文 Angular Conventional Commits，格式与要求见
[docs/conventions.md](docs/conventions.md) 的"提交信息格式"一节。

## 文档同步

以下变更请同步更新对应文档，否则 reviewer 会要求补充：

- 新增/修改命令 → [docs/commands.md](docs/commands.md)
- 新增/修改环境变量 → [docs/env-vars.md](docs/env-vars.md) 与 `.env.example`
- 改变模块边界或数据流 → [docs/architecture.md](docs/architecture.md)

## 审查与合并

- `main` 分支受保护：禁止直接推送，CI 必须全绿。
- 任何维护者都可以审查并合并他人的 PR；审查者自己负责确认测试覆盖充分。
- 涉及以下内容时请格外仔细：认证与密钥处理、黑名单过滤语义、
  风险阈值、构图准入规则、`docker/` 部署配置、
  `config/profile/` 下的提示词目录。

## 行为约定

参与讨论请保持专业与友善；技术分歧以仓库内文档和测试结果为准。
