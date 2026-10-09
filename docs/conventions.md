> 所属项目：[AGENTS.md](../AGENTS.md)

## 代码规范

### 命名约定

| 类型 | 约定 | 示例 |
|------|------|------|
| 文件名 | snake_case | `logging.py`, `litellm_text.py` |
| 类名 | PascalCase | `SentinelPipelineFlow`, `EventClassifier` |
| 函数名 | snake_case | `normalize_event()`, `add_event_to_graph()` |
| 变量名 | snake_case | `normalized_event`, `risk_threshold` |
| 常量 | UPPER_SNAKE_CASE | `MAX_QUERY_LENGTH`, `GRAPHITI_DRY_RUN` |
| 私有模块级变量 | `_` 前缀 | `_ACTIVE_LLMS`, `_PROCESSED_EVENTS` |
| 枚举值 | UPPER_SNAKE_CASE | `EventSource.NEWS`, `RiskLevel.HIGH` |

### 领域术语命名

在代码、注释和文档中描述领域概念时，统一使用下列术语：

| 术语 | 含义与用法 | 避免使用 |
|------|-----------|---------|
| `Settings` | 全项目唯一的配置入口（`sentinel.config.SentinelSettings`，基于 pydantic-settings）：统一吸收所有环境变量的读取、类型转换、默认值、回退链与密钥处理；调用方只读已校验、已类型化的字段；模块级单例 `settings` | config 模块、配置类、env helper |
| Secret 字段 | Settings 中以 `SecretStr` 声明的凭证字段（各类 API key、数据库密码、Milvus token）：repr/日志默认遮蔽，取明文须显式 `.get_secret_value()`，且只在构造真实 client 的 live 边界校验缺失 | 密码、凭据、credential |

### 代码格式化

- 使用 **ruff** 进行格式化、lint 检查和导入排序
- 导入排序通过 Ruff `I` 规则统一处理，不单独引入 isort
- 提交前由 pre-commit 自动运行 Ruff；必要时可手动运行 `uv run pre-commit run --all-files`
- 缩进：4 空格（Python 标准）
- 字符串：单引号优先，docstring 使用三重双引号
- 行尾：LF

### 注释和文档字符串

- 模块级 docstring：每个 `.py` 文件以模块说明开头，描述该模块在整个系统中的角色
- 函数 docstring：使用 Google 风格（Args / Returns / 作用），中文描述
- 类属性 docstring：Pydantic 模型字段使用 `Field(description="...")` 标注
- 行内注释：使用中文解释业务逻辑（如 `# 实例化 TypeClassifier + RiskEvaluator 两个 Agent`）
- 日志记录使用 f-string 或 `%s` 占位符

### 提交信息格式

提交信息必须遵守 Angular Conventional Commits，并使用英文：

```text
<type>(<scope>): <subject>
```

scope 可省略：

```text
<type>: <subject>
```

要求：

- 第一行不超过 72 个字符
- subject 使用祈使句或简短动词短语
- type 使用 `feat`、`fix`、`docs`、`style`、`refactor`、`test`、`chore`
- 不使用中文提交信息

示例：

- `docs(agent): rewrite agent instructions`
- `docs(development): add project guidelines`
- `chore(pre-commit): add ruff hooks`
