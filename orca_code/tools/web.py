"""orca_code.tools.web — Tool class wrappers."""

from __future__ import annotations

from orca_code.tools.base import Tool
from orca_code.permissions import RiskLevel


class WebFetchTool(Tool):
    name = "web_fetch"
    description = "Fetch raw web page content"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL"}
        }
    }
    required = ['url']
    risk_level = RiskLevel.READ

    def execute(self, url: str) -> str:
        from orca_code.tools_web import web_fetch
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return web_fetch(**kwargs)


class ReadWebpageTool(Tool):
    name = "read_webpage"
    description = "Extract readable text from web page"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL"}
        }
    }
    required = ['url']
    risk_level = RiskLevel.READ

    def execute(self, url: str) -> str:
        from orca_code.tools_web import read_webpage
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return read_webpage(**kwargs)


class WebSearchTool(Tool):
    name = "web_search"
    description = "Web search"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search keywords"},
            "topic": {"type": "string", "description": "news or general"},
            "days": {"type": "integer", "description": "Recent N days"}
        }
    }
    required = ['query']
    risk_level = RiskLevel.READ

    def execute(self, query: str, topic: str = None, days: str = None) -> str:
        from orca_code.tools_web import web_search
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return web_search(**kwargs)


class GetWeatherTool(Tool):
    name = "get_weather"
    description = "Query weather by city"
    parameters = {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "City name"}
        }
    }
    required = ['location']
    risk_level = RiskLevel.READ

    def execute(self, location: str) -> str:
        from orca_code.tools_web import get_weather
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return get_weather(**kwargs)


class GetLocationTool(Tool):
    name = "get_location"
    description = "Get current location"
    parameters = {"type": "object", "properties": {}, "required": []}
    required = []
    risk_level = RiskLevel.READ

    def execute(self) -> str:
        from orca_code.tools_web import get_location
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return get_location(**kwargs)


def register_web_tools(registry) -> int:
    """Register all web tools. Returns count of new registrations."""
    tools = [WebFetchTool(), ReadWebpageTool(), WebSearchTool(), GetWeatherTool(), GetLocationTool()]
    count = 0
    for tool in tools:
        if tool.name not in registry:
            registry.register(tool)
            count += 1
    return count
