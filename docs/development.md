> 所属项目：[AGENTS.md](../AGENTS.md)

## 开发准则

本指南面向人类开发者和编码智能体，说明 Sentinel 当前 `src` 布局下的日常开发规则。智能体还必须先阅读根目录 [AGENTS.md](../AGENTS.md)，因为其中包含智能体专用工作流和高风险停下询问规则。

### 1. 开发基线

- Python 版本基线为 Python 3.13。
- 依赖、脚本和命令统一通过 `uv` 执行。
- Art Design Pro 前端位于 `frontend/`，使用 Node.js 20.19.0+ 与 pnpm 10.17.1+。
- 运行时业务包位于 `src/sentinel/`，项目内部运行时代码统一使用 `sentinel.*` 导入。
- 不新增根目录兼容壳，例如新的顶层 `main.py`、`config.py`、`models.py`。
- 不依赖当前工作目录制造导入成功；命令应通过 `uv run ...` 或已声明的项目入口执行。
- 新增依赖必须进入 `pyproject.toml` 的合适 dependency group，并同步 `uv.lock`。

### 2. 目录职责

| 路径 | 职责 | 开发规则 |
|---|---|---|
| `src/sentinel/` | Sentinel 运行时业务代码 | 新业务逻辑放入对应领域模块，避免继续扩大 `src/sentinel/main.py` |
| `src/sentinel/pipeline/` | Stage 级业务逻辑（blacklist gate / classification / risk / batch / dashboard） | 保持 `src/sentinel/main.py` 只做 Flow wiring、CLI 与 service lifecycle |
| `src/sentinel/blacklist/` | 黑名单过滤、Milvus stores、输入事件落库与回捞 | stores 使用批量接口，事件 collection 保持静态 schema |
| `src/sentinel/graph/` | Graphiti/Neo4j adapter、构图、检索 | 对外封装 Graphiti 生命周期、Episode 写入和混合检索 |
| `src/sentinel/ragflow/` | RAGFlow 检索客户端与 prompt-safe 证据格式化 | 只做 retrieval API 读取和不可信证据注入；不上传、解析或写入 RAGFlow 数据集 |
| `src/sentinel/trend_prediction/` | Dashboard 八类趋势/严重度分类、意图分析与趋势预测 | 类别选择和运行时组装留在代码中；非 zero-shot 自适应 prompt 正文在 `config/profile/` 维护 |
| `src/sentinel/web/` | Web 看板 API、实时分析任务管理、结果序列化与 SPA 挂载 | 保持 FastAPI router/factory 边界，不在 `src/sentinel/main.py` 增加 Web 业务 |
| `src/sentinel/utils/` | 跨模块共享工具 | 只放真正跨模块复用的工具，避免为了单个调用点抽象 |
| `src/graphiti_core/` | vendored Graphiti 内核 | 默认不改；构图方案、Graphiti 行为适配、图谱写入或检索底层任务可改，需说明影响范围并扩大验证 |
| `frontend/` | 基于 Art Design Pro 二开的 Sentinel Web 前端 | 业务代码放在 `src/api/sentinel/`、`src/views/sentinel/`、`src/components/sentinel/` 和 `src/router/modules/sentinel.ts`；顶层应用栏目可放在对应的 `src/views/settings/`、`src/views/about/` 与独立 route module |
| `scripts/` | 本地运维、检查、演示脚本 | 调用稳定的 `sentinel.*` 接口，不承载运行时业务核心 |

### 3. 变更流程

1. 先确认当前分支、工作树和未提交改动。
2. 阅读本次变更相关的专题文档和模块。
3. 将变更限制在任务相关文件内。
4. 更新代码时同步更新测试、命令文档和环境变量文档。
5. 运行与变更相关的验证命令。
6. 提交前确保 pre-commit hooks 已运行；如果 hook 修改了文件，重新 `git add` 后再次提交。

多人或多智能体并行时，应从 `main` 派生分支并在 `.worktrees/` 下隔离工作。单智能体小改动可按当前上下文处理，但必须保护已有未提交改动。

### 4. 配置规则

- 配置统一由 `sentinel.config.SentinelSettings` 读取和校验。
- 非密结构化配置放在 `config/config.yaml`，示例维护在 `config/config.example.yaml`。
- 密钥放在 `.env` 或进程环境变量中，不提交 `.env`。
- 环境变量说明维护在 [docs/env-vars.md](env-vars.md)。
- 测试中构造 `SentinelSettings` 时必须显式隔离本地配置来源，避免依赖未跟踪的 `config/config.yaml` 或 `.env`。
- Secret 字段取明文时使用 `SentinelSettings` 提供的显式方法，不在日志中输出密钥。
- Runtime profile 与 prompt 的完整编辑说明见 [config/profile/README.md](../config/profile/README.md)。profile 路径固定为 `config/profile/`，不通过环境变量或 `SentinelSettings` 切换；所有 prompt 路径必须在 `profile.yaml` 中显式声明。
- `get_profile_config()` 会缓存 YAML 和 prompt 正文。修改 `profile.yaml` 或 prompt Markdown 后必须重启运行进程，不要期待热加载。
- 源码和 Docker Compose 部署必须提供完整 `config/profile/`；不要为 wheel-only 场景增加隐式 package fallback 或第二套默认 prompt，除非另行批准配置语义变更。

#### Profile prompt 编辑规则

- 动态变量使用 Python format 语法 `{variable}`；需要输出字面花括号时使用 `{{literal}}`。loader 不预检占位符。Stage 渲染时的普通 format 异常会统一净化为 `PromptRenderError` 并终止该次 Pipeline；错误不得包含原异常消息或事件值，`BaseException` 不应被包装。
- 机器可读 JSON schema、允许值和解析契约留在 Python 代码中，由 Stage 作为 `output_schema` 等动态值注入；Markdown 只维护自然语言指令和固定输出措辞。不要把机器契约复制到 prompt 文件形成第二份定义。
- 测试应断言稳定标记、关键动态值和结构，不要断言整段可编辑措辞。仓库 profile 另有精确 catalog/variable contract 测试，确保所有已提交 prompt 都已声明、无孤立文件，并恰好使用各 Stage 支持的变量。
- 新增或修改 pipeline prompt 时：先更新 `profile.yaml` 的对应路径或 Markdown，再核对调用 Stage 提供的变量；如需新增动态变量，同步修改 Stage 和精确变量契约测试。新增机器输出字段时先修改 Python schema/解析器，再将其作为动态 contract 注入。
- 新增 Dashboard 类别 prompt 时：先确认是否真的要扩展固定的八类趋势 taxonomy；同步更新 `classification_taxonomy.py` 的 descriptions/keywords/names、`profile.yaml` 的 category pair、两个 Markdown 文件，以及 catalog/variable、领域语义和实际路由测试。仅调整现有类别措辞时只改对应 pair。Pipeline 的 `profile.classification.categories` 是另一套事件类型，不能代替 Dashboard taxonomy。
- Graph extraction 是例外：它的 Markdown 原样传给 Graphiti，不调用 Sentinel `render_prompt()`；不要按 Sentinel 变量契约为其添加 `{variable}` 插值预期。

### 5. 测试规则

- 每次代码变更至少运行相关测试。
- 影响共享模型、配置、pipeline、Graphiti adapter、Milvus stores、LiteLLM 工具函数或公共脚本时，扩大到相关测试组或 `uv run pytest tests/ -m "not integration"`。
- 集成测试只在明确具备 Docker、Neo4j、Milvus、LLM/Rerank API 等条件时运行。
- 不能运行测试或测试失败时，在交付说明中写明命令、失败原因和判断。
- 文档-only 变更通常运行 pre-commit 即可；若文档变更同步修改工具链配置，则运行对应工具链验证命令。

### 6. 质量门禁

- 项目使用 Ruff 进行格式化、lint 自动修复和导入排序。
- 提交前通过 pre-commit 自动执行 Ruff。
- 手动验证全部 hooks 使用：

```bash
uv run pre-commit run --all-files
```

- 如果 hook 修改文件，执行：

```bash
git status -sb
git add <modified-files>
uv run pre-commit run --all-files
```

### 7. 文档同步

- 新增或改变命令时更新 [docs/commands.md](commands.md)。
- 新增或改变环境变量时更新 [docs/env-vars.md](env-vars.md) 和 `.env.example`。
- 新增或改变前端环境变量时同步更新 `frontend/.env.example`。
- 改变模块边界或数据流时更新 [docs/architecture.md](architecture.md)。
- 增加禁止事项或高风险操作时更新 [docs/restrictions.md](restrictions.md)。

### 8. Git 规则

- 提交消息使用英文 Angular Conventional Commits。
- 格式为 `<type>(<scope>): <subject>` 或 `<type>: <subject>`。
- 常用类型：`feat`、`fix`、`docs`、`style`、`refactor`、`test`、`chore`。
- 示例：`docs(agent): add development guidelines`。
- 默认只本地提交，不直接 push 到 `origin/*`，除非维护者明确要求。
- 不使用 reset、revert、checkout 等操作覆盖他人未提交改动。
