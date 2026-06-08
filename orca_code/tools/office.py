"""orca_code.tools.office — Tool class wrappers."""

from __future__ import annotations

from orca_code.tools.base import Tool
from orca_code.permissions import RiskLevel


class ReadExcelTool(Tool):
    name = "read_excel"
    description = "Read Excel file"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path"},
            "sheet_name": {"type": "string", "description": "Sheet name"}
        }
    }
    required = ['path']
    risk_level = RiskLevel.WRITE

    def execute(self, path: str, sheet_name: str = None) -> str:
        from orca_code.tools_office import read_excel
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return read_excel(**kwargs)


class WriteExcelTool(Tool):
    name = "write_excel"
    description = "Write Excel file from JSON"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path"},
            "data": {"type": "string", "description": "JSON data"},
            "sheet_name": {"type": "string", "description": "Sheet name"}
        }
    }
    required = ['path', 'data']
    risk_level = RiskLevel.WRITE

    def execute(self, path: str, data: str, sheet_name: str = None) -> str:
        from orca_code.tools_office import write_excel
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return write_excel(**kwargs)


class ReadWordTool(Tool):
    name = "read_word"
    description = "Extract text from Word document"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path"}
        }
    }
    required = ['path']
    risk_level = RiskLevel.WRITE

    def execute(self, path: str) -> str:
        from orca_code.tools_office import read_word
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return read_word(**kwargs)


class WriteWordTool(Tool):
    name = "write_word"
    description = "Create Word document"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path"},
            "content": {"type": "string", "description": "Text content"},
            "title": {"type": "string", "description": "Document title"}
        }
    }
    required = ['path', 'content']
    risk_level = RiskLevel.WRITE

    def execute(self, path: str, content: str, title: str = None) -> str:
        from orca_code.tools_office import write_word
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return write_word(**kwargs)


class TakeScreenshotTool(Tool):
    name = "take_screenshot"
    description = "Take screenshot"
    parameters = {
        "type": "object",
        "properties": {
            "window_title": {"type": "string", "description": "Window title keyword"},
            "save_path": {"type": "string", "description": "Save path"}
        }
    }
    required = []
    risk_level = RiskLevel.WRITE

    def execute(self, window_title: str = None, save_path: str = None) -> str:
        from orca_code.tools_office import take_screenshot
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return take_screenshot(**kwargs)


class OcrImageTool(Tool):
    name = "ocr_image"
    description = "OCR image to extract text"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Image file path"}
        }
    }
    required = ['path']
    risk_level = RiskLevel.READ

    def execute(self, path: str) -> str:
        from orca_code.tools_office import ocr_image
        kwargs = {k: v for k, v in locals().items() if k != "self" and not callable(v) and v is not None}
        return ocr_image(**kwargs)


def register_office_tools(registry) -> int:
    """Register all office tools. Returns count of new registrations."""
    tools = [ReadExcelTool(), WriteExcelTool(), ReadWordTool(), WriteWordTool(), TakeScreenshotTool(), OcrImageTool()]
    count = 0
    for tool in tools:
        if tool.name not in registry:
            registry.register(tool)
            count += 1
    return count
