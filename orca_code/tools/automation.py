"""orca_code.tools.automation — Tool class wrappers."""

from __future__ import annotations

from orca_code.tools.base import Tool
from orca_code.permissions import RiskLevel


class GuiClickTool(Tool):
    name = "gui_click"
    description = "Click at screen coords"
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X"},
            "y": {"type": "integer", "description": "Y"},
            "button": {"type": "string", "description": "Button"},
            "clicks": {"type": "integer", "description": "Clicks"}
        }
    }
    required = ['x', 'y']
    risk_level = RiskLevel.EXEC

    def execute(self, x: str, y: str, button: str = None, clicks: str = None) -> str:
        from orca_code.tools_automation import gui_click
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return gui_click(**kwargs)


class GuiTypeTool(Tool):
    name = "gui_type"
    description = "Type text at focus"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text"},
            "interval": {"type": "number", "description": "Interval"}
        }
    }
    required = ['text']
    risk_level = RiskLevel.EXEC

    def execute(self, text: str, interval: str = None) -> str:
        from orca_code.tools_automation import gui_type
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return gui_type(**kwargs)


class GuiMoveTool(Tool):
    name = "gui_move"
    description = "Move mouse to coords"
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X"},
            "y": {"type": "integer", "description": "Y"},
            "duration": {"type": "number", "description": "Duration"}
        }
    }
    required = ['x', 'y']
    risk_level = RiskLevel.EXEC

    def execute(self, x: str, y: str, duration: str = None) -> str:
        from orca_code.tools_automation import gui_move
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return gui_move(**kwargs)


class GuiHotkeyTool(Tool):
    name = "gui_hotkey"
    description = "Send keyboard shortcut"
    parameters = {
        "type": "object",
        "properties": {
            "keys": {"type": "array", "description": "Key names"}
        }
    }
    required = ['keys']
    risk_level = RiskLevel.EXEC

    def execute(self, keys: str) -> str:
        from orca_code.tools_automation import gui_hotkey
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return gui_hotkey(**kwargs)


class GuiPressTool(Tool):
    name = "gui_press"
    description = "Press a single key"
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Key name"}
        }
    }
    required = ['key']
    risk_level = RiskLevel.EXEC

    def execute(self, key: str) -> str:
        from orca_code.tools_automation import gui_press
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return gui_press(**kwargs)


class WindowFocusTool(Tool):
    name = "window_focus"
    description = "Focus a window by title"
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Window title"}
        }
    }
    required = ['title']
    risk_level = RiskLevel.EXEC

    def execute(self, title: str) -> str:
        from orca_code.tools_automation import window_focus
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return window_focus(**kwargs)


class FindOnScreenTool(Tool):
    name = "find_on_screen"
    description = "Find text on screen via OCR"
    parameters = {
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Text to find"}
        }
    }
    required = ['description']
    risk_level = RiskLevel.EXEC

    def execute(self, description: str) -> str:
        from orca_code.tools_automation import find_on_screen
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return find_on_screen(**kwargs)


def register_automation_tools(registry) -> int:
    """Register all automation tools. Returns count of new registrations."""
    tools = [GuiClickTool(), GuiTypeTool(), GuiMoveTool(), GuiHotkeyTool(), GuiPressTool(), WindowFocusTool(), FindOnScreenTool()]
    count = 0
    for tool in tools:
        if tool.name not in registry:
            registry.register(tool)
            count += 1
    return count
