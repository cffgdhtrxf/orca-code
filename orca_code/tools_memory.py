"""orca_code.tools_memory — Memory and profile tools.

Extracted from main.py to break circular import chains.
main.py was both an importer AND import target, causing
_LAZY_TOOLS workarounds in tool_registry.py.
"""

import json
from datetime import datetime
from pathlib import Path


def update_profile(note: str) -> str:
    if hasattr(update_profile, '_mem_mgr') and update_profile._mem_mgr:
        try:
            existing = update_profile._mem_mgr.get_meta("user_profile") or ""
            existing += f" {note.strip()}"
            if len(existing) > 500:
                existing = existing[-500:]
            update_profile._mem_mgr.set_meta("user_profile", existing.strip())
            return f"Profile updated: {note.strip()[:100]}"
        except Exception as e:
            return f"Error updating profile: {e}"
    return "Profile system not available."


def recall_conversation(query: str, limit: int = 5) -> str:
    if not hasattr(recall_conversation, '_mem_mgr') or not recall_conversation._mem_mgr:
        return "Memory system not available."
    if not hasattr(recall_conversation, '_session'):
        recall_conversation._session = _SessionProxy()
    session = recall_conversation._session
    if session.recall_count >= 3:
        return "Recall limit reached (3 per turn)."
    session.recall_count += 1
    try:
        limit = min(max(1, limit), 20)
        results = recall_conversation._mem_mgr.search_hybrid(query, limit=limit, graph_depth=1)
        if not results:
            return "No matching memories found."
        user_msgs = [r for r in results if r["role"] == "user"]
        real_topics = []
        noise_patterns = ["之前我们聊过什么", "之前聊过什么", "记忆", "你记得", "你还记得"]
        for r in user_msgs:
            text = r["content"][:80].replace("\n", " ")
            if text and not any(n in text for n in noise_patterns):
                if text not in real_topics:
                    real_topics.append(text)
        lines = [f"[Memory search: '{query}' — {len(results)} results]"]
        if real_topics:
            lines.append(f"These topics were discussed in past sessions: {'; '.join(real_topics[:5])}")
            lines.append("Answer the user's question based on the above. Do NOT say 'no history' if topics exist above.")
            lines.append("---")
        else:
            lines.append("No substantive past topics found in the results below.")
        for r in results:
            ts = r["timestamp"][:16] if r["timestamp"] else "--"
            role_label = "User" if r["role"] == "user" else "Assistant"
            snippet = r.get("snippet", r["content"][:300])
            lines.append(f"[{ts}] {role_label}: {snippet}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching memory: {e}"


class _SessionProxy:
    """Minimal session proxy for recall_count tracking outside main.py session."""
    def __init__(self):
        self.recall_count = 0


def inject_session(mem_mgr, session_obj=None):
    """Inject runtime dependencies into tool functions.

    Called once from main.py at startup. This is explicit dependency
    injection, replacing the previous implicit import coupling.
    """
    update_profile._mem_mgr = mem_mgr
    recall_conversation._mem_mgr = mem_mgr
    if session_obj is not None:
        recall_conversation._session = session_obj
