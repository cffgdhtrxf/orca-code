"""orca_code.security_scan — Static analysis patterns for AI agent skills.

Ports the most impactful static analysis patterns from NVIDIA SkillSpector
into Orca Code's security layer. Covers 6 of the 17 SkillSpector categories
with ~50 high-signal regex patterns.

This is an ADDITIONAL scan layer on top of the existing AST sandbox
(security.py Layer 2). Runs before skill execution to catch dynamic patterns
that AST scanning may miss.

Usage:
    from orca_code.security_scan import scan_skill
    issues = scan_skill(code_string, "skill_name")
    # issues = [(severity, category, description), ...]
"""

import logging
import re

logger = logging.getLogger("orca_code.security_scan")

# ═══════════════════════════════════════════════════════════════════════════════
# Pattern groups — each is a list of (regex, severity, category, description)
# Severity: CRITICAL / HIGH / MEDIUM / LOW
# ═══════════════════════════════════════════════════════════════════════════════

PROMPT_INJECTION_PATTERNS = [
    (r'(?i)ignore\s+(all\s+)?(previous|above|below)\s+(instructions|commands|directives)',
     "HIGH", "Prompt Injection", "Instruction override attempt"),
    (r'(?i)system\s*(prompt|instruction|message)[:\s]*["\'].*["\']',
     "HIGH", "Prompt Injection", "System prompt override"),
    (r'(?i)forget|disregard|ignore\s+(your\s+)?(training|rules|guidelines|safety)',
     "HIGH", "Prompt Injection", "Safety override attempt"),
    (r'(?i)you\s+(are\s+)?(now|are\s+free|can\s+ignore|don\'t\s+need\s+to)',
     "MEDIUM", "Prompt Injection", "Role escape attempt"),
    (r'(?i)(DO\s+NOT|NEVER|ALWAYS)\s+(output|respond|return|show|display|include)',
     "MEDIUM", "Prompt Injection", "Behavior override via emphasis"),
    (r'<!--[\s\S]*?(?:SYSTEM|IGNORE|OVERRIDE|HIDDEN)[\s\S]*?-->',
     "CRITICAL", "Prompt Injection", "Hidden instructions in HTML comments"),
    (r'\[\/\/\]:\s*#\s*\(.*?(?:ignore|override|system).*?\)',
     "HIGH", "Prompt Injection", "Hidden instructions in Markdown comments"),
]

DATA_EXFILTRATION_PATTERNS = [
    (r'(?i)(?:requests|urllib|httpx|aiohttp)\.(?:get|post|put)\(.*?(?:os\.environ|process\.env|token|api_key|secret|password)',
     "CRITICAL", "Data Exfiltration", "Env/sensitive data sent to external URL"),
    (r'(?i)(?:subprocess|os\.system|os\.popen)\(.*?(?:curl|wget)\s+.*?(?:http|https):\/\/.*?\s*[-|\|>]',
     "CRITICAL", "Data Exfiltration", "Data piped to external server"),
    (r'(?i)(?:discord\.com/api/webhooks|hooks\.slack\.com|api\.telegram\.org|webhook\.site)',
     "HIGH", "Data Exfiltration", "Known exfiltration endpoint (webhook)"),
    (r'(?i)(?:nslookup|dig|ping|traceroute)\s+.*`.*(?:whoami|hostname|id|pwd|env)',
     "MEDIUM", "Data Exfiltration", "DNS-based data exfiltration"),
    (r'(?i)open\(.*[\'\"](?:/etc/|/proc/|/sys/|/home/|~/)',
     "MEDIUM", "Data Exfiltration", "Filesystem enumeration via open()"),
    (r'(?i)(?:os\.environ|os\.getenv|environ\.get)\(.*\)[\s\S]{0,50}(?:curl|wget|requests|urllib)',
     "CRITICAL", "Data Exfiltration", "Environment variable harvest + send"),
]

PRIVILEGE_ESCALATION_PATTERNS = [
    (r'(?i)(?:sudo|runas|chmod\s+4777|chown\s+root)',
     "HIGH", "Privilege Escalation", "Privilege escalation command"),
    (r'(?i)(?:/etc/sudoers|/etc/passwd|/etc/shadow|/etc/group)',
     "HIGH", "Privilege Escalation", "System credential file access"),
    (r'(?i)(?:ssh-keygen|authorized_keys|id_rsa|id_ed25519)',
     "MEDIUM", "Privilege Escalation", "SSH key manipulation"),
    (r'(?i)(?:kubectl|helm)\s+(?:apply|create|delete|exec)\s',
     "MEDIUM", "Privilege Escalation", "Kubernetes command execution"),
    (r'(?i)docker\s+(?:exec|run|attach)\s+(?:--privileged|-it|-v)',
     "HIGH", "Privilege Escalation", "Docker escape via privileged mode"),
]

SUPPLY_CHAIN_PATTERNS = [
    (r'(?i)pip\s+install\s+(?:git\+http|https?://|--index-url)',
     "HIGH", "Supply Chain", "Remote pip install (possible typosquatting)"),
    (r'(?i)npm\s+install\s+(?:git\+http|https?://|@[a-z]+/[a-z]+)',
     "MEDIUM", "Supply Chain", "Remote npm install"),
    (r'(?i)(?:curl|wget)\s+.*?\|?\s*(?:ba)?sh\b',
     "CRITICAL", "Supply Chain", "Remote code execution via pipe to shell"),
    (r'(?i)(?:curl|wget)\s+.*?-o\s+.*?\.(?:py|sh|ps1|exe|bat)\s',
     "HIGH", "Supply Chain", "Remote binary download"),
    (r'(?i)(?:pip|npm|cargo|gem)\s+install\s+.*?--(?:no-?deps|ignore-?deps|force)',
     "MEDIUM", "Supply Chain", "Dependency install skipping safety checks"),
]

ANTI_REFUSAL_PATTERNS = [
    (r'(?i)(?:don\'t\s+(?:say|output|respond|refuse|reject)|never\s+(?:refuse|deny|say\s+(?:no|sorry)))',
     "HIGH", "Anti-Refusal", "Refusal suppression attempt"),
    (r'(?i)(?:output\s+(?:without|only|exactly)\s+(?:any|all|the\s+exact)|return\s+only\s+the\s+result)',
     "MEDIUM", "Anti-Refusal", "Disclaimer suppression attempt"),
    (r'(?i)(?:you\s+(?:must|will|have\s+to)\s+(?:obey|comply|follow)\s+(?:all|any|every))',
     "MEDIUM", "Anti-Refusal", "Safety compliance override"),
    (r'(?i)(?:no\s+(?:safety|ethical|moral|legal)\s+(?:guidelines|restrictions|boundaries))',
     "HIGH", "Anti-Refusal", "Safety boundary nullification"),
]

AGENT_SNOOPING_PATTERNS = [
    (r'(?i)(?:~/?\.(?:claude|cursor|codex|opencode|windsurf|github-copilot|gemini)/?)',
     "HIGH", "Agent Snooping", "Agent config directory access"),
    (r'(?i)(?:~/?\.(?:mcp|continue)/?|mcp\.json|mcp_servers\.json)',
     "MEDIUM", "Agent Snooping", "MCP configuration access"),
    (r'(?i)(?:SKILL\.md|skill\.md|AGENTS\.md|CLAUDE\.md|CONTEXT\.md)',
     "LOW", "Agent Snooping", "Skill/metadata file enumeration"),
    (r'(?i)(?:ls\s+-la\s+(?:~/?\.|%USERPROFILE%[/\\\\]\.[a-z]))',
     "MEDIUM", "Agent Snooping", "Agent config directory listing"),
]

# All patterns combined
_ALL_PATTERNS = (
    PROMPT_INJECTION_PATTERNS +
    DATA_EXFILTRATION_PATTERNS +
    PRIVILEGE_ESCALATION_PATTERNS +
    SUPPLY_CHAIN_PATTERNS +
    ANTI_REFUSAL_PATTERNS +
    AGENT_SNOOPING_PATTERNS
)


def scan_skill(code: str, skill_name: str = "<unknown>") -> list[tuple[str, str, str]]:
    """Scan skill code against all security pattern groups.

    Args:
        code: The Python source code to scan.
        skill_name: Name of the skill (for logging).

    Returns:
        List of (severity, category, description) tuples. Empty if clean.
    """
    findings: list[tuple[str, str, str]] = []

    for pattern, severity, category, description in _ALL_PATTERNS:
        try:
            if re.search(pattern, code):
                findings.append((severity, category, description))
                logger.debug(
                    "Skill '%s': [%s] %s — %s",
                    skill_name, severity, category, description,
                )
        except re.error as e:
            logger.warning("Bad regex pattern in security_scan: %s — %s", pattern, e)

    return findings


def scan_skill_blocking(code: str, skill_name: str = "<unknown>") -> str | None:
    """Scan and return blocking error string if CRITICAL/HIGH patterns found.

    Returns:
        Error string if blocked, None if clean.
    """
    findings = scan_skill(code, skill_name)
    blocking = [(sev, cat, desc) for sev, cat, desc in findings
                if sev in ("CRITICAL", "HIGH")]

    if not blocking:
        return None

    lines = [f"SECURITY BLOCK: Skill '{skill_name}' contains {len(blocking)} risk(s):"]
    for sev, cat, desc in blocking[:5]:
        lines.append(f"  [{sev}] {cat}: {desc}")
    if len(blocking) > 5:
        lines.append(f"  ... and {len(blocking) - 5} more")
    return "\n".join(lines)
