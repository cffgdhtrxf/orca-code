"""orca_code.config_validator — Startup config validation (P2-28).

Validates config.json at server startup. Checks:
  - Required fields present
  - Type validation (str, int, bool)
  - URL format
  - API key presence
  - Value ranges

Returns structured validation results with error/warning/info levels.
Errors prevent startup, warnings are shown but allowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass
class ValidationIssue:
    level: str       # "error", "warning", "info"
    field: str       # dot-separated path
    message: str
    suggestion: str = ""


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.level == "error" for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "warning")

    def format_for_display(self) -> str:
        if not self.issues:
            return "✓ 配置验证通过 — 无问题"

        lines = []
        for issue in self.issues:
            prefix = {"error": "✗", "warning": "⚠", "info": "ℹ"}.get(issue.level, "?")
            lines.append(f"  {prefix} [{issue.field}] {issue.message}")
            if issue.suggestion:
                lines.append(f"       修复: {issue.suggestion}")

        summary = f"配置验证: {self.error_count} 错误, {self.warning_count} 警告"
        return summary + "\n" + "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Field specs
# ═══════════════════════════════════════════════════════════════════════════════

REQUIRED_FIELDS: dict[str, dict] = {
    "api_key": {
        "type": str, "required": True,
        "description": "LLM API 密钥",
        "sensitive": True,
    },
    "base_url": {
        "type": str, "required": True,
        "description": "LLM API 地址",
        "validate_url": True,
        "example": "https://api.deepseek.com/v1",
    },
    "model_name": {
        "type": str, "required": True,
        "description": "模型名称",
        "example": "deepseek-chat",
    },
    "max_output_tokens": {
        "type": (int, float), "required": True,
        "description": "最大输出 token 数",
        "min": 1, "max": 131072,
    },
    "context_max_tokens": {
        "type": (int, float), "required": True,
        "description": "上下文最大 token 数",
        "min": 1000, "max": 200000,
    },
    "enable_think_mode": {
        "type": (str, bool), "required": False,
        "description": "启用思考模式 (true/false)",
    },
    "permission_mode": {
        "type": str, "required": False,
        "description": "权限模式",
        "allowed": ["read-only", "auto", "yolo"],
    },
    "max_workers": {
        "type": (int, float), "required": False,
        "description": "最大并行工作线程",
        "min": 1, "max": 32,
    },
    "cmd_timeout": {
        "type": (int, float), "required": False,
        "description": "命令超时秒数",
        "min": 5, "max": 600,
    },
    "keep_last_rounds": {
        "type": (int, float), "required": False,
        "description": "保留最近轮数",
        "min": 2, "max": 200,
    },
    "working_dir": {
        "type": str, "required": False,
        "description": "工作目录",
    },
}

OPTIONAL_FIELDS: dict[str, dict] = {
    "tavily_api_key": {"type": str, "required": False, "description": "Tavily 搜索 API 密钥"},
    "vision_api_key": {"type": str, "required": False, "description": "Vision 模型 API 密钥"},
    "vision_base_url": {"type": str, "required": False, "description": "Vision 模型 API 地址"},
    "vision_model": {"type": str, "required": False, "description": "Vision 模型名称"},
    "user_city": {"type": str, "required": False, "description": "用户城市（天气用）"},
    "enable_gui_auto": {"type": (str, bool), "required": False, "description": "启用 GUI 自动化"},
    "enable_browser_auto": {"type": (str, bool), "required": False, "description": "启用浏览器自动化"},
    "enable_tts": {"type": (str, bool), "required": False, "description": "启用 TTS 语音"},
    "enable_voice": {"type": (str, bool), "required": False, "description": "启用语音输入"},
    "local_model": {"type": (str, bool), "required": False, "description": "本地模型模式"},
    "multimodal": {"type": (str, bool), "required": False, "description": "多模态支持"},
    "auto_install_deps": {"type": (str, bool), "required": False, "description": "自动安装依赖"},
    "silent_cmd": {"type": (str, bool), "required": False, "description": "静默命令模式"},
    "preferred_shell": {"type": str, "required": False, "description": "首选 Shell"},
    "persona": {"type": str, "required": False, "description": "AI 人格"},
    "reasoning_effort": {"type": str, "required": False, "description": "推理力度",
                         "allowed": ["low", "medium", "high", "max"]},
    "permission_rules": {"type": dict, "required": False, "description": "权限规则"},
    "mcp_servers": {"type": dict, "required": False, "description": "MCP 服务器配置"},
}


def validate_config(config: dict[str, Any], config_path: Path | None = None) -> ValidationResult:
    """Validate a config dictionary against the field specs.

    Args:
        config: The config dictionary to validate.
        config_path: Optional path for error messages.

    Returns:
        ValidationResult with issues list.
    """
    result = ValidationResult()

    if not isinstance(config, dict):
        result.issues.append(ValidationIssue(
            "error", "config",
            f"配置必须是 JSON 对象 (dict)，实际是 {type(config).__name__}",
            f"检查 {(config_path or 'config.json')} 是否为有效的 JSON 对象",
        ))
        return result

    # Check required fields
    for field_name, spec in REQUIRED_FIELDS.items():
        value = config.get(field_name)

        if value is None or value == "":
            if spec.get("required", True):
                result.issues.append(ValidationIssue(
                    "error", field_name,
                    f"缺少必需字段: {spec['description']}",
                    f'在 config.json 中添加 "{field_name}": {spec.get("example", "<value>")}',
                ))
            continue

        # Type check
        expected_type = spec["type"]
        if not isinstance(value, expected_type):
            result.issues.append(ValidationIssue(
                "error", field_name,
                f"类型错误: 期望 {expected_type.__name__}，实际 {type(value).__name__}",
                f"将 '{field_name}' 改为正确的类型",
            ))
            continue

        # Range check
        if "min" in spec and isinstance(value, (int, float)):
            if value < spec["min"]:
                result.issues.append(ValidationIssue(
                    "error", field_name,
                    f"值太小: {value} < {spec['min']}",
                    f'将 "{field_name}" 设为 >= {spec["min"]}',
                ))
        if "max" in spec and isinstance(value, (int, float)):
            if value > spec["max"]:
                result.issues.append(ValidationIssue(
                    "warning", field_name,
                    f"值太大: {value} > {spec['max']}",
                    f'建议将 "{field_name}" 设为 <= {spec["max"]}',
                ))

        # URL validation
        if spec.get("validate_url") and isinstance(value, str):
            try:
                parsed = urlparse(value)
                if not parsed.scheme or not parsed.netloc:
                    raise ValueError("Invalid URL")
            except Exception:
                result.issues.append(ValidationIssue(
                    "error", field_name,
                    f"URL 格式无效: {value}",
                    f'修正 URL 格式，如 "{spec.get("example", "https://api.example.com/v1")}"',
                ))

        # Allowed values
        if "allowed" in spec and isinstance(value, str):
            if value not in spec["allowed"]:
                result.issues.append(ValidationIssue(
                    "warning", field_name,
                    f"非标准值: '{value}' (允许: {', '.join(spec['allowed'])})",
                    f'建议设为 {spec["allowed"]} 之一',
                ))

    # Check optional fields
    for field_name, spec in OPTIONAL_FIELDS.items():
        value = config.get(field_name)
        if value is None:
            continue

        expected_type = spec["type"]
        if isinstance(expected_type, tuple):
            if not isinstance(value, expected_type):
                types_str = " | ".join(t.__name__ for t in expected_type)
                result.issues.append(ValidationIssue(
                    "warning", field_name,
                    f"类型警告: 期望 {types_str}，实际 {type(value).__name__}",
                    f'检查 "{field_name}" 的类型',
                ))
        elif not isinstance(value, expected_type):
            result.issues.append(ValidationIssue(
                "warning", field_name,
                f"类型警告: 期望 {expected_type.__name__}，实际 {type(value).__name__}",
                f'检查 "{field_name}" 的类型',
            ))

        if "allowed" in spec and isinstance(value, str):
            if value not in spec["allowed"]:
                result.issues.append(ValidationIssue(
                    "warning", field_name,
                    f"非标准值: '{value}' (允许: {', '.join(spec['allowed'])})",
                    "",
                ))

    # Info: API key format check (non-blocking)
    api_key = config.get("api_key", "")
    if api_key and not api_key.startswith("sk-") and not api_key.startswith("ant-"):
        result.issues.append(ValidationIssue(
            "info", "api_key",
            "API 密钥格式可能不标准",
            "大多数 API 密钥以 'sk-' 开头",
        ))

    # Info: working directory check
    wd = config.get("working_dir", "")
    if wd:
        wd_path = Path(wd)
        if not wd_path.exists():
            result.issues.append(ValidationIssue(
                "warning", "working_dir",
                f"工作目录不存在: {wd}",
                "创建该目录或改为已存在的路径",
            ))

    return result


def validate_and_report(config: dict[str, Any], config_path: Path | None = None) -> bool:
    """Validate config and print results. Returns True if no errors."""
    result = validate_config(config, config_path)
    print(result.format_for_display())
    return not result.has_errors
