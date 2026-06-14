"""orca_code.dashboard — Flask web dashboard for session monitoring.

Usage:
    python -m orca_code.dashboard     # starts on http://localhost:8499
    python -m orca_code.dashboard --port 8500
"""

from __future__ import annotations

import time

from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

# ── Data sources ──────────────────────────────────────────────────────────────

def _get_session():
    try:
        from orca_code.session import session
        return session
    except ImportError:
        return None

def _get_tool_registry():
    try:
        from orca_code.tools import tool_registry
        return tool_registry
    except ImportError:
        return None

# ── HTML template ─────────────────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Orca Code Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,sans-serif;background:#0d1117;color:#c9d1d9;padding:2rem}
h1{color:#58a6ff;margin-bottom:1rem}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1.5rem;margin-bottom:1rem}
.card h2{color:#f0f6fc;font-size:1.1rem;margin-bottom:1rem}
.stat{display:inline-block;min-width:120px;margin:0.5rem 1rem 0.5rem 0}
.stat .value{font-size:2rem;font-weight:bold;color:#58a6ff}
.stat .label{font-size:0.8rem;color:#8b949e}
.tool-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:0.5rem}
.tool-item{background:#21262d;padding:0.5rem 0.8rem;border-radius:4px;font-size:0.85rem}
.tool-item .name{color:#f0f6fc}
.tool-item .risk{float:right;font-size:0.7rem;padding:1px 6px;border-radius:3px}
.risk-READ{background:#23863633;color:#3fb950}
.risk-WRITE{background:#d2992233;color:#d29922}
.risk-EXEC{background:#da363333;color:#f85149}
.events{max-height:300px;overflow-y:auto;font-family:monospace;font-size:0.8rem}
.event{padding:0.3rem 0;border-bottom:1px solid #21262d}
.refresh{color:#8b949e;font-size:0.8rem;margin-top:1rem}
</style>
</head>
<body>
<h1>🐋 Orca Code Dashboard</h1>

<div class="card">
<h2>Session</h2>
<div class="stat"><div class="value">{{ turns }}</div><div class="label">Turns</div></div>
<div class="stat"><div class="value">{{ tool_calls }}</div><div class="label">Tool Calls</div></div>
<div class="stat"><div class="value">{{ input_tokens }}</div><div class="label">Input Tokens</div></div>
<div class="stat"><div class="value">{{ output_tokens }}</div><div class="label">Output Tokens</div></div>
<div class="stat"><div class="value">{{ elapsed }}</div><div class="label">Elapsed</div></div>
</div>

<div class="card">
<h2>Tools ({{ tool_count }})</h2>
<div class="tool-list">
{% for t in tools %}
<div class="tool-item">
<span class="name">{{ t.name }}</span>
<span class="risk risk-{{ t.risk }}">{{ t.risk }}</span>
</div>
{% endfor %}
</div>
</div>

<div class="card">
<h2>Recent Activity</h2>
<div class="events">
{% for e in events %}
<div class="event">{{ e }}</div>
{% endfor %}
</div>
</div>

<p class="refresh">Auto-refresh: 5s | Orca Code v{{ version }}</p>
<script>setTimeout(()=>location.reload(),5000)</script>
</body>
</html>"""

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    sess = _get_session()
    registry = _get_tool_registry()

    tools = []
    if registry:
        for name in registry.list_names()[:30]:
            from orca_code.permissions import TOOL_RISK
            risk = TOOL_RISK.get(name, None)
            tools.append({
                "name": name,
                "risk": risk.value if risk else "EXEC",
            })

    events = []
    if sess and sess.messages:
        for m in sess.messages[-5:]:
            role = m.get("role", "?")
            content = str(m.get("content", ""))[:80]
            events.append(f"[{role}] {content}")

    return render_template_string(
        DASHBOARD_HTML,
        turns=sess.turns if sess else 0,
        tool_calls=sess.tool_calls if sess else 0,
        input_tokens=f"{sess.total_input_tokens:,}" if sess else "0",
        output_tokens=f"{sess.total_output_tokens:,}" if sess else "0",
        elapsed=sess.elapsed if sess else "0s",
        tools=tools,
        tool_count=len(tools),
        events=events or ["No activity yet"],
        version="5.1.0",
    )

@app.route("/stats")
def stats():
    sess = _get_session()
    if not sess:
        return jsonify({"error": "No active session"})
    return jsonify({
        "turns": sess.turns,
        "tool_calls": sess.tool_calls,
        "input_tokens": sess.total_input_tokens,
        "output_tokens": sess.total_output_tokens,
        "cached_tokens": sess.total_cached_tokens,
        "reasoning_tokens": sess.total_reasoning_tokens,
        "elapsed": sess.elapsed,
    })

@app.route("/tools")
def tools_list():
    registry = _get_tool_registry()
    if not registry:
        return jsonify({"error": "No registry"})
    return jsonify({"tools": registry.list_names(), "count": len(registry)})

@app.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": time.time()})


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Orca Code Dashboard")
    parser.add_argument("--port", type=int, default=8499)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    print(f"🐋 Orca Code Dashboard → http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
