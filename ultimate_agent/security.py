
import re, ipaddress, urllib.parse, hashlib, logging
import ast as _ast
from pathlib import Path
from typing import Optional

"""ultimate_agent.security — Dangerous patterns, URL check, sandbox."""


_TEST_LOCATION_HASH = "1949a70bb82d437571480ce084c08aa1ba9799b68c6180643212afd77ad193f4"
_DANGEROUS_PATTERNS = [
    # Only block commands that irreversibly destroy the file system
    r'rm\s+(-rf?|-r\s+-f?)\s+/',
    r'mkfs\.',
    r'dd\s+if=.*of=/dev',
]
def _is_safe_url(url: str) -> tuple:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"禁止协议: {parsed.scheme}"
    if not parsed.hostname:
        return False, "无效 URL"
    return True, ""
_SKILL_BLACKLIST = [
    "os", "sys", "subprocess", "shutil", "ctypes", "urllib", "requests",
    "socket", "http", "ftplib", "telnetlib", "smtplib",
    "open", "exec", "eval", "compile", "__import__", "globals", "locals",
    "getattr", "setattr", "delattr", "hasattr",
    "breakpoint", "__builtins__", "__builtin__",
    "Path", "pathlib",
]
_SKILL_DANGEROUS_ATTRS = {
    "__class__", "__bases__", "__subclasses__", "__mro__",
    "__globals__", "__builtins__", "__builtin__", "__import__",
    "__dict__", "__code__", "__closure__", "__func__", "__self__",
    "__init__", "__new__", "__del__", "__reduce__", "__reduce_ex__",
    "__getattribute__", "__getattr__", "__setattr__",
    "system", "popen", "exec", "eval", "compile",
}
_SKILL_SAFE_BUILTINS = {
    "len": len, "str": str, "int": int, "float": float, "bool": bool,
    "list": list, "dict": dict, "tuple": tuple, "set": set,
    "print": print, "range": range, "enumerate": enumerate, "zip": zip,
    "map": map, "filter": filter, "sum": sum, "min": min, "max": max,
    "abs": abs, "round": round, "sorted": sorted, "reversed": reversed,
    "isinstance": isinstance, "Exception": Exception,
    "TypeError": TypeError, "ValueError": ValueError,
}
def _scan_skill_ast(code: str, name: str) -> Optional[str]:
    try:
        tree = _ast.parse(code, filename=f"<skill:{name}>")
    except SyntaxError as e:
        return f"技能语法错误: {e}"

    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Import, _ast.ImportFrom)):
            return f"技能禁止导入模块 (检测到 import 语句)"

        # [Fix 5] Check ALL Attribute nodes for dangerous attr names (catches __subclasses__, __class__, etc.)
        if isinstance(node, _ast.Attribute):
            if isinstance(node.attr, str) and node.attr in _SKILL_DANGEROUS_ATTRS:
                return f"技能禁止访问危险属性: {node.attr}"
            # [Fix 2] Detect module.__import__ bypass (e.g., math.__import__('os'))
            if node.attr == '__import__':
                return f"技能禁止调用 __import__ (包括通过模块访问)"

        if isinstance(node, _ast.Call):
            if isinstance(node.func, _ast.Name):
                if node.func.id in _SKILL_BLACKLIST:
                    return f"技能禁止调用: {node.func.id}"
            elif isinstance(node.func, _ast.Attribute):
                if isinstance(node.func.value, _ast.Name):
                    if node.func.value.id in _SKILL_BLACKLIST:
                        return f"技能禁止调用: {node.func.value.id}"
                    # [Fix 2] Detect module.__import__ or module.eval etc.
                    if node.func.attr in ('__import__', 'eval', 'exec', 'compile'):
                        return f"技能禁止调用: {node.func.value.id}.{node.func.attr}"

    return None
def _safe_exec_skill(code: str, name: str):
    error = _scan_skill_ast(code, name)
    if error:
        return error

    # [SECURITY] Only inject pure builtins + math — NO json/re/datetime modules.
    # Modules expose __subclasses__() chains that can escape to os.system().
    import math
    restricted = {
        "__builtins__": {
            **_SKILL_SAFE_BUILTINS,
            "True": True, "False": False, "None": None,
            "issubclass": issubclass,
        },
        "math": math,
    }
    local_ns = {}
    try:
        exec(compile(code, f"<skill:{name}>", "exec"), restricted, local_ns)
    except Exception as e:
        return f"技能执行错误: {e}"
    return local_ns