"""orca_code.tool_validator — Tool argument validation (P2-33).

Validates tool call arguments against their JSON schemas before execution.
Prevents silent failures from malformed arguments and gives clear error messages.

Usage:
    from orca_code.tool_validator import validate_tool_args

    errors = validate_tool_args("read_file", {"path": "/tmp/test"})
    if errors:
        print(errors[0])  # "Missing required field: path"
"""

from __future__ import annotations

from typing import Any


def validate_tool_args(tool_name: str, args: dict, schema: dict | None = None) -> list[str]:
    """Validate tool arguments against the tool's JSON schema.

    Args:
        tool_name: Name of the tool.
        args: The arguments to validate.
        schema: Optional JSON Schema for the tool's parameters.
                If None, uses a built-in schema from TOOL_SCHEMAS.

    Returns:
        List of error messages. Empty list = valid.
    """
    if schema is None:
        schema = TOOL_SCHEMAS.get(tool_name, {})

    if not schema:
        return []  # No schema = no validation

    errors: list[str] = []

    # Check required fields
    required: list[str] = schema.get("required", [])
    properties: dict = schema.get("properties", {})

    for field in required:
        if field not in args or args[field] is None or args[field] == "":
            errors.append(f"缺少必需参数: '{field}' ({properties.get(field, {}).get('description', '无描述')})")

    # Check field types
    for field, value in args.items():
        if field not in properties:
            continue  # Unknown fields are allowed (extras)

        prop = properties[field]
        expected_type = prop.get("type", "string")

        if expected_type == "string" and not isinstance(value, str):
            errors.append(f"参数 '{field}' 应为字符串，实际为 {type(value).__name__}")
        elif expected_type == "integer" and not isinstance(value, (int, float)):
            errors.append(f"参数 '{field}' 应为整数，实际为 {type(value).__name__}")
        elif expected_type == "number" and not isinstance(value, (int, float)):
            errors.append(f"参数 '{field}' 应为数字，实际为 {type(value).__name__}")
        elif expected_type == "boolean" and not isinstance(value, bool):
            errors.append(f"参数 '{field}' 应为布尔值，实际为 {type(value).__name__}")
        elif expected_type == "array" and not isinstance(value, list):
            errors.append(f"参数 '{field}' 应为数组，实际为 {type(value).__name__}")
        elif expected_type == "object" and not isinstance(value, dict):
            errors.append(f"参数 '{field}' 应为对象，实际为 {type(value).__name__}")

        # Check enum values
        if "enum" in prop and value not in prop["enum"]:
            errors.append(
                f"参数 '{field}' 值 '{value}' 不在允许范围: {', '.join(map(str, prop['enum']))}"
            )

    return errors


def validate_with_suggestion(tool_name: str, args: dict) -> str | None:
    """Validate and return a human-readable error message.

    Returns None if valid, or a formatted error string with suggestions.
    """
    errors = validate_tool_args(tool_name, args)
    if not errors:
        return None

    lines = [f"工具 '{tool_name}' 参数错误:"]
    for e in errors:
        lines.append(f"  ✗ {e}")

    # Add usage hint
    schema = TOOL_SCHEMAS.get(tool_name, {})
    required = schema.get("required", [])
    if required:
        lines.append(f"  必需参数: {', '.join(required)}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Built-in schemas (subset — full schemas in tool_registry.py)
# ═══════════════════════════════════════════════════════════════════════════════

TOOL_SCHEMAS: dict[str, dict] = {
    "read_file": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件绝对路径"},
        },
        "required": ["path"],
    },
    "write_file": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "要写入的内容"},
        },
        "required": ["path", "content"],
    },
    "edit_file": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "old_string": {"type": "string", "description": "要替换的文本"},
            "new_string": {"type": "string", "description": "替换后的文本"},
            "hashline": {"type": "string", "description": "行哈希锚定"},
        },
        "required": ["path", "old_string", "new_string"],
    },
    "execute_command": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
            "working_dir": {"type": "string", "description": "工作目录"},
        },
        "required": ["command"],
    },
    "search_content": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "搜索文本或正则"},
            "directory": {"type": "string", "description": "搜索目录"},
            "file_filter": {"type": "string", "description": "文件名过滤"},
        },
        "required": ["pattern"],
    },
    "search_files": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "glob 模式"},
            "directory": {"type": "string", "description": "搜索起始目录"},
        },
        "required": ["pattern"],
    },
    "web_search": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "topic": {"type": "string", "enum": ["general", "news"], "description": "搜索类型"},
            "days": {"type": "integer", "description": "最近N天"},
        },
        "required": ["query"],
    },
    "web_fetch": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL"},
        },
        "required": ["url"],
    },
    "agent_open": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "子代理任务描述"},
            "tools": {"type": "string", "description": "可用工具列表"},
            "context": {"type": "string", "description": "额外上下文"},
        },
        "required": ["task"],
    },
    "agent_eval": {
        "type": "object",
        "properties": {
            "handle": {"type": "string", "description": "子代理句柄"},
            "timeout": {"type": "integer", "description": "超时秒数"},
        },
        "required": ["handle"],
    },
    "gui_click": {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X 坐标"},
            "y": {"type": "integer", "description": "Y 坐标"},
            "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "鼠标按键"},
            "clicks": {"type": "integer", "description": "点击次数"},
        },
        "required": ["x", "y"],
    },
}
