# AnyAgent 提交规范

本文件适用于整个仓库。所有贡献者和编码 Agent 创建提交时都应遵守以下规则。

## 提交粒度

- 每个提交只解决一个明确问题，或交付一个可独立说明和审查的改动。
- 按改动目的拆分，避免把工程配置、业务功能、无关重构和文档更新集中到一个提交。
- 拆分后的提交应保持项目可安装、已有功能可运行；后续提交可以依赖前面的提交。
- 不机械地按文件或行数拆分。实现同一行为所必需的文件应一起提交，相关测试随实现提交，依赖声明与 `uv.lock` 一起提交。
- 可以独立交付的文档或规范调整单独提交；必须与行为同步的接口契约和使用说明随行为提交。
- 修改涉及多个主题时，先确定提交顺序，再逐项暂存和提交，不等整轮工作全部结束后统一提交。
- 提交前检查暂存区，只暂存本次提交需要的文件或代码块；不默认使用 `git add .` 或 `git add -A`。
- 已有提交不会因本规范自动重写。重写历史、合并提交或修改已发布提交需有用户明确授权。

## Commit 消息

每条 commit 必须同时包含标题和正文，使用英文。遵循 Conventional Commits：

```text
<type>(<scope>): <summary>

Why:
Explain the problem or reason for this change.

Changes:
- Describe the concrete files, behavior, or rules changed.

Validation:
- Record the checks actually run and their results.
```

- 标题使用祈使句，简洁描述改动目的，建议不超过 72 个字符。
- `scope` 可省略；使用时选择具体模块，如 `config`、`startup`、`runner`、`mcp`、`rag`。
- `type` 使用 `feat`、`fix`、`refactor`、`test`、`docs`、`build`、`ci` 或 `chore`。
- 正文必须说明为什么修改、具体做了什么、如何验证；不能只重复标题或写“update files”。
- 正文中的文件、行为和验证结果必须与本次提交一致，不把后续计划写成已完成内容。
- 只记录实际运行过的检查；未运行时说明原因，不把静态检查描述为启动或集成验证。
- 破坏性变更使用 `!` 并在正文追加 `BREAKING CHANGE:`，说明影响和迁移方式。
- 多行消息写入临时文件，通过 `git commit --file <path>` 提交，保留真实换行。

示例：

```text
feat(config): load startup settings from TOML

Why:
Runtime paths and server defaults need one configurable source.

Changes:
- Add configs/app.toml for path and server values.
- Load and validate settings through anyagent.configs.
- Resolve relative paths against the project root.

Validation:
- Configuration tests passed.
- Ruff lint and formatting checks passed.
```

## 提交前检查

1. 检查 `git status --short`、`git diff` 和 `git diff --cached`，确认改动范围正确。
2. 运行与改动相关的验证；Python 代码运行 Ruff，行为变化运行对应测试，启动逻辑变化验证实际启动和退出。
3. 运行 `git diff --cached --check`，检查暂存内容的空白问题。
4. 确认没有提交 `plans/`、`data/`、虚拟环境、缓存、凭据或运行产物；不要用强制暂存绕过这些目录的忽略规则。
5. 确认 commit 标题和正文完整，再创建提交。用户已有改动仅在授权范围内纳入。
6. 提交后检查提交内容与工作区状态，向用户报告提交编号、改动主题和实际验证结果。

## 项目约定

- 项目通过根目录 `main.py` 启动。
- 路径值和启动默认值集中在 `configs/`；Python 中的配置加载和路径解析集中在 `src/anyagent/configs/`，其他模块使用解析后的配置。
- 平台管理的运行数据默认统一保存到根目录 `data/`；版本化启动配置不保存密钥或运行时生成文件。
- `plans/` 是本地临时规划目录，不提交 Git，由用户自行上传到 GitHub Issue。
- 源码注释和日志使用英文，复杂公开接口采用 Google 风格 docstring。
