"""Registered configuration groups and human-readable form metadata."""

from dataclasses import dataclass

from anyagent.configs.agent import FrontendSettings, LangChainSettings, ModelSettings
from anyagent.configs.base import BaseSettings
from anyagent.configs.default import DEFAULT_CONFIGS
from anyagent.configs.models import CmdConfig, DatabaseSettings, LoggingSettings


@dataclass(frozen=True)
class ConfigGroup:
    title: str
    description: str
    schema: type[BaseSettings]
    apply_mode: str
    fields: dict[str, tuple[str, str, bool]]


GROUPS = {
    "model_config": ConfigGroup(
        "模型连接",
        "先填入模型服务提供的地址、模型名称和密钥，再开启模型。",
        ModelSettings,
        "next_run",
        {
            "enabled": (
                "启用模型",
                "开启后才能聊天。首次使用请先填写下方连接信息。",
                False,
            ),
            "base_url": (
                "接口地址",
                "填写模型服务的接口前缀，例如 https://api.openai.com/v1；不要填写 /chat/completions。",
                False,
            ),
            "model": ("模型名称", "按服务商提供的名称填写，例如 gpt-4.1-mini。", False),
            "api_key": (
                "API Key",
                "填写服务商提供的密钥。无需认证的本地服务可填 local。",
                False,
            ),
            "streaming": (
                "流式输出",
                "开启时逐步显示回复；关闭时等待完整回复。两种模式都支持工具。",
                False,
            ),
            "temperature": (
                "回答随机性",
                "越低越稳定，越高越有变化。通常保留默认值即可。",
                True,
            ),
            "timeout_seconds": (
                "单次模型等待时间（秒）",
                "模型服务超过这个时间未响应时结束调用。",
                True,
            ),
            "max_retries": (
                "失败重试次数",
                "失败后重新调用的次数；重试可能增加等待时间和模型费用。",
                True,
            ),
            "stream_usage": (
                "请求流式用量信息",
                "仅在模型服务明确支持时开启。通常保持关闭。",
                True,
            ),
        },
    ),
    "langchain_config": ConfigGroup(
        "Agent 行为",
        "调整助手的回答方式和运行限制，首次使用可保留默认值。",
        LangChainSettings,
        "restart",
        {
            "runner": (
                "执行引擎",
                "langchain 使用官方封装；langgraph 使用显式状态图；loop 为无框架的本地循环。",
                False,
            ),
            "system_prompt": (
                "助手指令",
                "描述希望助手如何回答、何时使用工具。",
                False,
            ),
            "max_steps": ("执行步骤上限", "限制模型与工具循环的图执行步数。", True),
            "max_sessions": ("最多会话数", "达到上限后需要删除不用的会话。", True),
            "max_history_messages": (
                "保留的历史消息数",
                "按完整问答轮次保留最近的消息；奇数向下取偶数。",
                True,
            ),
            "max_concurrent_runs": (
                "同时执行的会话数",
                "同一个会话始终只允许一次执行。",
                True,
            ),
            "run_timeout_seconds": (
                "整轮执行时限（秒）",
                "包含模型调用与工具执行。",
                True,
            ),
            "max_input_chars": ("单条消息字数上限", "网页与后端使用同一限制。", True),
            "max_output_chars": (
                "最终回复字数上限",
                "过长的回复不会保存到历史。",
                True,
            ),
            "max_event_chars": (
                "过程信息大小上限",
                "限制文本增量和工具过程信息的总大小。",
                True,
            ),
            "cleanup_timeout_seconds": (
                "连接清理时限（秒）",
                "停止或完成生成后回收模型连接的等待时间。",
                True,
            ),
        },
    ),
    "frontend_config": ConfigGroup(
        "网页偏好",
        "选择网页打开时的默认连接方式。",
        FrontendSettings,
        "hot_reload",
        {
            "default_transport": (
                "默认连接方式",
                "WebSocket 和 HTTP 都支持聊天；保存后已打开的聊天页会自动同步。",
                False,
            ),
            "restart_poll_interval_ms": (
                "重启状态检查间隔（毫秒）",
                "网页等待重启时检查服务状态的间隔。",
                True,
            ),
            "restart_wait_timeout_seconds": (
                "重启等待上限（秒）",
                "超过此时间会提示手动重试，不会自动再次重启。",
                True,
            ),
            "cancel_timeout_ms": (
                "停止确认等待时间（毫秒）",
                "WebSocket 停止生成后等待服务确认的时间。",
                True,
            ),
        },
    ),
    "database_config": ConfigGroup(
        "会话存储",
        "会话和已完成的聊天记录保存在本机 SQLite 数据库，重启后继续使用。",
        DatabaseSettings,
        "restart",
        {
            "file_path": (
                "数据库文件位置",
                "通常保留默认值。更换文件会打开另一份数据库，不会自动搬迁已有会话。文件须位于 data 内，使用 .db、.sqlite 或 .sqlite3 扩展名。",
                True,
            ),
            "busy_timeout_seconds": (
                "数据库锁等待时间（秒）",
                "其他写入占用数据库时等待的时间。通常保持默认值。",
                True,
            ),
        },
    ),
    "logging_config": ConfigGroup(
        "日志",
        "记录运行情况以便排查问题，通常无需修改。",
        LoggingSettings,
        "restart",
        {
            "level": (
                "日志详细程度",
                "INFO 记录对话、模型回复和工具参数/结果；DEBUG 补充模型轮次及执行阶段。明确的认证字段脱敏，不记录连接密钥。",
                False,
            ),
            "third_party_level": (
                "依赖日志最低级别",
                "默认 WARNING，仅展示依赖的警告和错误；仍受上面的日志级别限制。HTTP 请求访问日志关闭，数据库和模型 HTTP 客户端的 DEBUG/INFO 始终过滤，避免输出参数或密钥。",
                True,
            ),
            "file_path": (
                "日志文件位置",
                "必须位于 data/logs 内。修改位置不会移动已有日志。",
                True,
            ),
            "max_bytes": (
                "单个日志文件大小（字节）",
                "达到此大小后轮换为新的日志文件。",
                True,
            ),
            "backup_count": (
                "保留的旧日志文件数",
                "超出数量的最旧日志会被删除。",
                True,
            ),
        },
    ),
    "cmd_config": ConfigGroup(
        "服务",
        "高级部署设置。首次使用建议保留默认值。",
        CmdConfig,
        "restart",
        {
            "server.host": (
                "监听地址",
                "本机使用保留 127.0.0.1；部署到局域网可用 0.0.0.0。",
                False,
            ),
            "server.port": ("服务端口", "修改后网页需要通过新的端口访问。", False),
            "paths.data_dir": (
                "数据目录",
                "仅允许根目录 data 内的路径；修改不会移动已有数据。",
                True,
            ),
        },
    ),
}

CHOICE_LABELS = {
    "websocket": "WebSocket",
    "http": "HTTP（SSE）",
    "langchain": "LangChain（官方封装）",
    "langgraph": "LangGraph（显式状态图）",
    "loop": "本地循环（无框架）",
}
APPLY_NOTICES = {
    "next_run": "保存后下一次聊天立即生效，正在生成的回复不受影响。",
    "hot_reload": "保存后立即生效，不需要重启服务或重新打开聊天页面。",
    "restart": "保存后需要重启服务才能生效；当前服务继续使用原设置。",
}


def form_fields(group: ConfigGroup) -> list[dict]:
    """Combine display text with bounds and types from the validation schema."""
    schema = group.schema.model_json_schema()
    result = []
    for path, (label, hint, advanced) in group.fields.items():
        node = schema
        for part in path.split("."):
            if "$ref" in node:
                node = schema["$defs"][node["$ref"].rsplit("/", 1)[-1]]
            node = node["properties"][part]
        control = (
            "select"
            if "enum" in node
            else {
                "boolean": "switch",
                "integer": "number",
                "number": "number",
                "string": "text",
            }[node["type"]]
        )
        if node.get("format") == "password":
            control = "password"
        elif path == "system_prompt":
            control = "textarea"
        result.append(
            {
                "path": path,
                "label": label,
                "hint": hint,
                "advanced": advanced,
                "control": control,
                "min": node.get("minimum"),
                "max": node.get("maximum"),
                "step": 1 if node["type"] == "integer" else 0.1,
                "choices": [
                    {"value": value, "label": CHOICE_LABELS.get(value, value)}
                    for value in node.get("enum", [])
                ],
            }
        )
    return result


def defaults_for(name: str) -> dict:
    # Secrets are never prefilled in a public form.
    return {**DEFAULT_CONFIGS[name]}
