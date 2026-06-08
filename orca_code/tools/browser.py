"""orca_code.tools.browser — Tool class wrappers."""

from __future__ import annotations

from orca_code.tools.base import Tool
from orca_code.permissions import RiskLevel


class BrowserOpenTool(Tool):
    name = "browser_open"
    description = "Open browser to URL"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL"},
            "headless": {"type": "boolean", "description": "Headless"}
        }
    }
    required = ['url']
    risk_level = RiskLevel.EXEC

    def execute(self, url: str, headless: str = None) -> str:
        from orca_code.tools_automation import browser_open
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return browser_open(**kwargs)


class BrowserClickTool(Tool):
    name = "browser_click"
    description = "Click element by selector"
    parameters = {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector"}
        }
    }
    required = ['selector']
    risk_level = RiskLevel.EXEC

    def execute(self, selector: str) -> str:
        from orca_code.tools_automation import browser_click
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return browser_click(**kwargs)


class BrowserTypeTool(Tool):
    name = "browser_type"
    description = "Type text into input"
    parameters = {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS selector"},
            "text": {"type": "string", "description": "Text"}
        }
    }
    required = ['selector', 'text']
    risk_level = RiskLevel.EXEC

    def execute(self, selector: str, text: str) -> str:
        from orca_code.tools_automation import browser_type
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return browser_type(**kwargs)


class BrowserScreenshotTool(Tool):
    name = "browser_screenshot"
    description = "Screenshot browser"
    parameters = {
        "type": "object",
        "properties": {
            "output_path": {"type": "string", "description": "Save path"}
        }
    }
    required = []
    risk_level = RiskLevel.EXEC

    def execute(self, output_path: str = None) -> str:
        from orca_code.tools_automation import browser_screenshot
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return browser_screenshot(**kwargs)


class BrowserCloseTool(Tool):
    name = "browser_close"
    description = "Close browser"
    parameters = {"type": "object", "properties": {}, "required": []}
    required = []
    risk_level = RiskLevel.EXEC

    def execute(self) -> str:
        from orca_code.tools_automation import browser_close
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return browser_close(**kwargs)


def register_browser_tools(registry) -> int:
    """Register all browser tools. Returns count of new registrations."""
    tools = [BrowserOpenTool(), BrowserClickTool(), BrowserTypeTool(), BrowserScreenshotTool(), BrowserCloseTool()]
    count = 0
    for tool in tools:
        if tool.name not in registry:
            registry.register(tool)
            count += 1
    return count
