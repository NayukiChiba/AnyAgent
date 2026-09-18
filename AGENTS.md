# AnyAgent 提交规范

本文件适用于整个仓库。所有贡献者和编码 Agent 创建提交时都应遵守以下规则。

## 提交粒度

- 每个提交只解决一个明确问题，或交付一个可独立说明和审查的改动。
- 按改动目的拆分，避免把工程配置、业务功能、无关重构和文档更新集中到一个提交。
- 拆分后的提交应保持依赖可同步、已有功能可运行；后续提交可以依赖前面的提交。
- 不机械地按文件或行数拆分。实现同一行为所必需的文件应一起提交，相关测试随实现提交，依赖声明与 `uv.lock` 一起提交。
- 可以独立交付的文档或规范调整单独提交；必须与行为同步的接口契约和使用说明随行为提交。
- 修改涉及多个主题时，先确定提交顺序，再逐项暂存和提交，不等整轮工作全部结束后统一提交。
- 提交前检查暂存区，只暂存本次提交需要的文件或代码块；不默认使用 `git add .` 或 `git add -A`。
- 已有提交不会因本规范自动重写。重写历史、合并提交或修改已发布提交需有用户明确授权。

## Commit 消息

每条 commit 必须同时包含标题和正文。只有 `type` 和 `scope` 使用英文，标题描述和正文均使用中文；文件名、命令和技术标识保留原样。遵循 Conventional Commits：

```text
<type>(<scope>): <中文改动描述>

修改原因：
说明本次修改要解决的问题。

改动内容：
- 说明具体修改的文件、行为或规范。

验证结果：
- 记录实际执行的检查及结果。
```

- 标题使用中文动词短语，简洁描述改动目的，建议不超过 72 个字符。
- `scope` 可省略；使用时选择具体模块，如 `config`、`startup`、`runner`、`mcp`、`rag`。
- `type` 使用 `feat`、`fix`、`refactor`、`test`、`docs`、`build`、`ci` 或 `chore`。
- 正文使用中文，必须说明为什么修改、具体做了什么、如何验证；不能只重复标题或写“更新文件”。
- 正文中的文件、行为和验证结果必须与本次提交一致，不把后续计划写成已完成内容。
- 只记录实际运行过的检查；未运行时说明原因，不把静态检查描述为启动或集成验证。
- 破坏性变更在标题的 `type`/`scope` 后使用 `!`，并在正文追加“不兼容变更：”，用中文说明影响和迁移方式。
- 多行消息写入临时文件，通过 `git commit --file <path>` 提交，保留真实换行。

示例：

```text
feat(config): 从 JSON 加载运行配置

修改原因：
运行路径和服务默认值需要统一的配置来源。

改动内容：
- 通过 anyagent/configs/default.py 创建默认的 data/configs/cmd_config.json。
- 通过 anyagent/configs/load.py 加载并校验当前配置。
- 统一以项目根目录为基准解析相对路径。

验证结果：
- 配置测试通过。
- Ruff 静态检查和格式检查通过。
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
- Python 代码只允许绝对导入，禁止 `from . ...`、`from .. ...` 等相对导入；该规则同样适用于包内模块、`__init__.py`、测试和类型检查分支。项目内导入使用完整的 `anyagent...` 模块路径，如 `from anyagent.configs.base import BaseSettings`，并继续遵守洋葱分层的依赖方向。Ruff 的 TID252 规则以 ban-relative-imports="all" 检查此约束。
- 应用源码放在根目录 `anyagent/` 的职责子目录中，包根仅保留用于包标识和版本号的 `__init__.py`，不放业务实现。直接通过 Python 模块导入，不使用 `src/` 层或项目自身的打包安装；uv 只管理依赖，不生成项目的 `egg-info`。`__version__` 与 `pyproject.toml` 中的版本保持一致，不依赖安装元数据。
- 采用依赖向内的洋葱分层：`core/domain/` 放领域模型和规则，`core/ports/` 定义替换契约，`core/services/`、`core/pipeline/` 及工具、MCP、知识和上下文子目录放应用流程。core 不导入 api、runtime、adapters、infrastructure、configs、Web 框架、ORM 或厂商 SDK；必要配置通过运行快照注入；utils 中仅允许依赖无运行配置与资源初始化的 anyagent.utils.logger 日志接口，不依赖其他 utils 模块。
- Port 是应用依赖的能力边界，优先以 Protocol 声明最小方法契约；实现不要求继承。Service 通过构造参数获取端口并组织用例，不为每个 Service 添加无替换需求的接口或统一 BaseService。Protocol 的运行时属性检查不代替签名检查、契约测试或实际执行验收。
- 责任链用于 pipeline 的阶段顺序与中止，洋葱中间件通过 call_next 包裹下游并管理 finally 清理；call_next 最多调用一次，事件流由执行阶段消费，不按每个 token 重跑下游阶段。Port、Service 和配置模型不承担责任链节点职责。
- `api/` 放 HTTP 路由、DTO、鉴权依赖、响应与 SSE 转换；`adapters/` 放 Runner、Provider、MCP 协议及检索实现；`infrastructure/` 放仓储和文件实现；`runtime/` 是依赖装配与生命周期入口，负责显式注册。新增 Runner 不在通用 pipeline 或 API 中添加厂商分支。
- `utils/` 仅放日志等通用技术支撑，不承载业务用例或策略。目录按已进入开发的功能创建，不提前生成未使用的空壳；包入口不创建全局 Manager、数据库、网络连接或任务。
- `anyagent/configs/` 属于洋葱外层支撑：`base.py` 定义共享配置值基类，`models.py` 定义具体配置 schema，`default.py` 创建默认配置，`load.py` 加载当前配置，`paths.py` 集中获取与校验路径，`__init__.py` 导出模型、共享配置和 paths；启动入口、runtime 和需要配置的外层模块直接获取配置，再注入 core。共享配置导入时创建/修复 JSON 是既有行为的明确例外，不将导入副作用扩展到其他包。
- 配置模型继承项目自己的 BaseSettings（基于 Pydantic BaseModel），统一拒绝未知字段、禁止字段重新赋值和校验默认值；基类不负责文件或环境变量加载，不继承 pydantic_settings.BaseSettings。具体字段按需求加严；frozen 不递归冻结集合，运行快照须单独保证隔离。领域对象、Port、Service 和 API DTO 不继承配置基类。
- 实际配置只使用 JSON，按类型保存于 `data/configs/`，主配置为 `cmd_config.json`，日志配置为 `logging_config.json`，不在 `anyagent/configs/` 保存 TOML 或 JSON 配置文件。
- 所有运行目录、文件路径、配置及备份命名规则、相对路径解析和边界校验只在 `anyagent/configs/paths.py` 定义。新增路径在该模块添加获取函数；其他模块通过 `from anyagent.configs import paths` 或已校验配置消费路径，不硬编码目录、不自行拼接业务路径、不根据 cwd 或 __file__ 推导部署根。路径获取函数不创建目录或文件，资源创建由其所有者在对应作用域完成。测试夹具的临时路径和 API URL 不属于运行路径硬编码。
- 配置类型使用独立默认值和校验模型，新增扩展配置不集中写入主配置；配置缺失时只创建该类型默认 JSON，内容无法加载时先在 `data/configs/` 备份原文件再恢复该类型默认值，文件系统权限错误不得作为格式错误覆盖处理。
- 平台管理的配置、密钥和运行数据统一保存到根目录 `data/`，不纳入版本控制。
- `plans/` 是本地临时规划目录，不提交 Git，由用户自行上传到 GitHub Issue。
- 源码注释和日志使用英文，复杂公开接口采用 Google 风格 docstring。

- 日志 INFO 记录项目生命周期与执行结果，DEBUG 记录执行阶段、耗时和数量，不输出聊天正文、工具参数或密钥。依赖日志默认至少 WARNING，由 logging_config 的 third_party_level 配置；数据库与模型 HTTP 客户端的 DEBUG/INFO 始终过滤，main.py 关闭 HTTP 访问日志。
- 全项目（包括 core、configs、infrastructure、adapters、api、runtime 与启动入口）统一使用自定义 `anyagent.utils.logger.AnyAgentLogger`：通过 `from anyagent.utils.logger import logger` 获取共享入口，或通过 `get_logger(__name__)` 获取模块入口。禁止业务代码直接导入原生 logging、调用 logging.getLogger，或自行创建 Handler、设置日志级别和输出。原生 logging 仅作为 utils/logger.py 内部输出与第三方兼容实现；专门验证日志兼容层的测试可使用原生 logging 注入依赖记录。Ruff TID251 禁止导入 logging，仅 utils/logger.py 与 tests/test_logger.py 豁免；新增业务模块不得扩大豁免范围。
- 自定义接口仅公开 debug、info、warning、error、critical、exception 固定方法与只读名称，不返回原生 Logger。级别、队列、过滤、格式、轮转及生命周期集中由 LogManager 管理；日志模块导入不加载配置、不创建文件或线程，LoggingSettings 仅用于类型检查，runtime 显式传入配置。core 对该通用接口的依赖是跨层日志支撑的明确例外，不扩展到配置、文件或其他工具实现。日志路径和轮转参数来自共享配置，日志文件必须位于 `data/logs/`，服务退出时清空队列并关闭本模块的处理器。
- 文档使用 VitePress，`package.json`、锁文件和依赖安装均在 `docs/` 内；修改文档需运行 `npm ci` 和 `npm run build`，不提交构建产物或缓存。

## 当前 Agent 迭代约定

- 首个 Runner 使用 LangChain 官方 SDK，实现最小对话与工具循环；通过 core/ports 注入 ChatService，API 共用服务，不按连接方式重复实现业务流程。
- 前端使用 Vue 3，源码、package.json、锁文件和依赖位于 frontend/；构建输出不提交，构建后的页面由 main.py 启动的 FastAPI 同源提供。
- 对外仅使用 HTTP 和 WebSocket；SSE 属于 HTTP 流式响应，保留作为 HTTP 流式连接选项。
- 会话与已完成的历史通过 SQLAlchemy 异步 SQLite 仓储持久化，执行状态仍保存在单进程内存中。ORM 仅位于 infrastructure，runtime 通过既有 SessionRepository 端口注入 core；各操作使用独立 AsyncSession 和短事务，不在模型调用期间持有数据库事务。
- 数据库配置独立保存于 data/configs/database_config.json，数据库路径仅由 configs/paths.py 校验并限制在 data/ 内。启动连接并创建缺失表，退出待执行清理完成后关闭连接池；数据库损坏或不可读必须报错，不得恢复为空库。create_all 不承担已有表结构迁移。
- 成功轮次以单个事务保存标题和有序历史快照，保留 max_history_messages 的现有窗口；失败或取消不保存半轮消息。会话容量检查与创建在同一写事务内完成。
- 模型地址、名称和 API Key 独立保存于 data/configs/model_config.json，新执行读取最新配置，既有执行使用自己的快照。API 不返回模型密钥；LangChain prompt 与执行预算使用独立配置，启动时读取。
- 当前流式连接断开会取消其执行，失败或取消不提交半轮历史。未来后台 Run、重放和持久恢复需要显式实现与验收，不将当前连接语义描述为这些能力。

- 所有可调运行项在 data/configs 分类 JSON 中保存，默认值统一在 configs/default.py；外层读取配置并注入 core，前端从状态接口获取其所需的公开参数，不在核心或页面硬编码这些运行项。
- model_config.json 的 streaming 控制上游流式/非流式调用，默认开启；关闭后不发送文本 delta，仍保留工具事件和最终结果。开关与 HTTP/WebSocket 连接方式独立，新执行热重载。
- 有效配置缺少新增默认项时，递归补齐并使用同目录临时文件原子更新，保留显式值、密钥和文件权限；未知字段、无效值与必填字段缺失仍按既有备份恢复规范处理。

## 网页设置约定

- 以小白可完成首次配置为验收目标；常规设置通过独立的 /settings 网页完成，不要求用户手动编辑 JSON。字段提供中文名称和用途说明；各组提供默认值恢复与生效时间，高级限制默认收起。
- 新配置同步登记 configs/catalog.py 的组、字段元数据及生效模式；控件类型、数值范围来自配置 schema，避免前后端各自维护一套规则。
- 查询与保存通过 configs/management.py 复用分类 loader 和原子写入；API 只接受登记过的配置名称，不接受任意文件路径。提交携带载入时的 revision，冲突不得覆盖已有修改；无效输入不得写回或触发默认恢复。
- 设置查询、默认值、错误响应和日志均不得暴露实际密钥。密钥输入留空保留现值，清除使用独立显式动作；保存成功后清空网页输入框，仅展示是否已保存密钥。
- 修改尚未保存时切换分类或离开页面必须提醒；恢复默认仅填入草稿，明确保存后才写入。重启项不可显示为已立即生效，模型热更新不影响正在执行的快照。
- 模型连接测试使用保存后的配置和既有 Runner 生命周期，限制并发、时限与输出，使用隔离的内存仓储；不得向用户聊天历史写入测试消息。

- 设置入口位于聊天侧栏底部，移动布局保持可访问。表单控件统一描边、圆角、错误、聚焦与禁用状态；自定义下拉菜单保留标签关联、选中状态、方向键、回车和取消操作。
- 项目重启由 main.py 拥有进程生命周期；API 响应先发出，再关闭服务、清理连接和日志，最终重新执行绝对入口并保留命令行参数。新监听地址与端口准备失败时不得停止当前服务，重复重启不得重复执行。
- 网页通过新的启动标识及就绪状态确认重启完成，检查间隔和等待时限来自 frontend_config；未保存草稿禁用重启，确认已保存会话保留、进行中的对话中止。外部 ASGI 未注入控制器时返回不可用，不任意终止宿主进程。
