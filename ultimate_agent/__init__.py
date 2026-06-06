"""Orca Code — desktop AI assistant.

Backward-compatible package. All names available at ultimate_agent.* level.
For new code, import directly from submodules:
    from ultimate_agent.config import CONFIG
    from ultimate_agent.tools_core import execute_command
"""

# Re-export everything from all modules for backward compatibility
from ultimate_agent.config import *
from ultimate_agent.utils import *
from ultimate_agent.security import *
from ultimate_agent.tools_core import *
from ultimate_agent.tools_office import *
from ultimate_agent.tools_web import *
from ultimate_agent.tools_dev import *
from ultimate_agent.tools_skills import *
from ultimate_agent.tools_automation import *
from ultimate_agent.tts_mcp import *
from ultimate_agent.session import *
from ultimate_agent.main import *
