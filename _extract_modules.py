"""One-shot extraction: split orca_code_legacy.py into package modules."""
import ast, sys, os

LEGACY = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orca_code_legacy.py')
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orca_code')

with open(LEGACY, 'r', encoding='utf-8') as f:
    source = f.read()
source_lines = source.split('\n')

tree = ast.parse(source)

# Collect all top-level nodes
nodes = []
for node in ast.iter_child_nodes(tree):
    start = node.lineno - 1
    end = node.end_lineno
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.decorator_list:
        start = min(d.lineno - 1 for d in node.decorator_list)
    src = '\n'.join(source_lines[start:end])
    nodes.append((start, end, src, node))

# Module routing
MODULES = {
    'config.py':       [],
    'utils.py':        [],
    'security.py':     [],
    'tools_core.py':   [],
    'tools_office.py': [],
    'tools_web.py':    [],
    'tools_dev.py':    [],
    'tools_skills.py': [],
    'tools_automation.py': [],
    'tts_mcp.py':      [],
    'session.py':      [],
    'main.py':         [],
}

CONFIG_NAMES = {
    'SCRIPT_DIR','CONFIG_JSON','CONFIG_TXT','DEFAULT_CONFIG','_TXT_KEY_MAP',
    '_SENSITIVE_KEYS','console','client','HTTP_SESSION',
    'search_cache','page_cache','_balance_cache','_balance_lock',
    'WORKING_DIR','SAVE_DIR','TEMP_DIR','LOGS_DIR','SKILLS_DIR','OUTPUT_DIR',
    'CACHE_DIR','MEMORY_DIR','TERM_WIDTH','HAS_MEMORY','mem_mgr',
    'HAS_SPEECH_RECOGNITION','SPEECH_BACKEND','HAS_PILLOW','HAS_OPENCV',
    'HAS_TTS','HAS_BERT_VITS2','VISION_MODEL','VISION_BASE_URL','VISION_API_KEY',
    '_load_json_config','_load_txt_config','mask_key','load_config',
    'handle_profile_cmd','handle_config_cmd','ensure_pkg','SimpleCache','get_api_balance',
    # Config-derived globals
    'API_KEY','BASE_URL','MODEL','MAX_OUTPUT_TOKENS','ENABLE_THINK_MODE',
    'SILENT_CMD','TAVILY_API_KEY','USER_CITY','AUTO_INSTALL_DEPS',
    'ENABLE_GUI_AUTO','ENABLE_BROWSER_AUTO','CONTEXT_MAX_TOKENS',
    'PREFERRED_SHELL','MAX_WORKERS','KEEP_ROUNDS','PERSONA','CMD_TIMEOUT',
    'REASONING_EFFORT','ENABLE_TTS','ENABLE_VOICE','IS_DEEPSEEK','IS_LOCAL',
    'IS_GEMMA','IS_QWEN','IS_MINISTRAL','USE_SIMPLE_PROMPT','IS_MULTIMODAL',
    '_MULTIMODAL_PATTERNS',
}

UTIL_NAMES = {
    '_detect_encoding','resolve_tool_path','_validate_write_path',
    '_estimate_tokens','cleanup_temp_files','fix_truncated_json',
    '_sanitize_ansi','_sanitize_for_save','_strip_html',
    '_FORBIDDEN_DIRS','_FORBIDDEN_NAMES','_FORBIDDEN_SUFFIXES','_FORBIDDEN_DIRS_INTERNAL',
}

SECURITY_NAMES = {
    '_DANGEROUS_PATTERNS','_is_safe_url','_SKILL_BLACKLIST',
    '_SKILL_DANGEROUS_ATTRS','_SKILL_SAFE_BUILTINS','_scan_skill_ast',
    '_safe_exec_skill','_TEST_LOCATION_HASH',
}

CORE_NAMES = {'execute_command','read_file','write_file','list_files',
    'search_files','search_content','get_device_type','get_system_info','get_env_summary'}

OFFICE_NAMES = {'read_excel','write_excel','read_word','write_word',
    'take_screenshot','ocr_image','_ocr_lock','_ocr_engine'}

WEB_NAMES = {'web_fetch','read_webpage','_optimize_search_query','_score_results',
    '_search_with_tavily','_ddg_fallback','web_search','get_weather',
    '_get_system_location','_match_city_by_coords','get_location'}

DEV_NAMES = {'_run_git','git_status','git_diff','git_log','git_blame',
    '_extract_symbol','go_to_definition','find_references','analyze_image','capture_camera'}

SKILLS_NAMES = {'_loaded_skills','_md_skill_cache','_autoload_skills_cache',
    '_parse_skill_md','load_skill','create_skill','edit_skill','list_skills',
    'list_md_skills','load_md_skill','_scheduler_tasks','_scheduler_lock',
    '_scheduler_shutdown','_scheduler_thread','_parse_cron','_cron_match',
    '_run_task','_schedule_loop','add_task','list_tasks','remove_task'}

AUTO_NAMES = {'_gui_confirm','gui_click','gui_type','gui_move',
    '_browser_instance','_browser_lock','_get_browser','browser_open',
    'browser_click','browser_type','browser_screenshot','browser_close'}

TTSMCP_NAMES = {'BertVits2TTS','bert_vits2_engine','_sapi_speaker_cache',
    '_sapi_chinese_voice','_sapi_english_voice','_tts_queue','_tts_processing',
    '_tts_lock','_tts_condition','_detect_tts_lang','_get_sapi_speaker',
    '_tts_worker','_tts_worker_thread','speak_text','voice_input',
    '_load_mcp_config','mcp_call_tool','_enumerate_mcp_tools','init_mcp_tools'}

SESSION_NAMES = {'Session','session','build_system_prompt','_estimate_prefix_tokens',
    '_CACHED_PREFIX_TOKENS','print_gap','print_soft_gap','show_tool_call',
    'show_tool_result','show_tool_done','show_usage','show_welcome',
    'show_help','show_stats','show_cache','sanitize_messages','_msg_tokens',
    '_extract_text','_llm_compress_blocks','smart_trim_messages',
    'save_conversation','auto_save','call_model','process_stream','execute_tool_calls'}

MAIN_NAMES = {'TOOLS','TOOL_MAP','run_tool','update_profile','recall_conversation',
    'get_user_input','_get_user_input_win32','_get_user_input_unix','main'}

def get_name(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name):
                return t.id
    return ''

for start, end, src, node in nodes:
    name = get_name(node)
    routed = False

    if name in CONFIG_NAMES: MODULES['config.py'].append(src); routed = True
    elif name in UTIL_NAMES: MODULES['utils.py'].append(src); routed = True
    elif name in SECURITY_NAMES: MODULES['security.py'].append(src); routed = True
    elif name in CORE_NAMES: MODULES['tools_core.py'].append(src); routed = True
    elif name in OFFICE_NAMES: MODULES['tools_office.py'].append(src); routed = True
    elif name in WEB_NAMES: MODULES['tools_web.py'].append(src); routed = True
    elif name in DEV_NAMES: MODULES['tools_dev.py'].append(src); routed = True
    elif name in SKILLS_NAMES: MODULES['tools_skills.py'].append(src); routed = True
    elif name in AUTO_NAMES: MODULES['tools_automation.py'].append(src); routed = True
    elif name in TTSMCP_NAMES: MODULES['tts_mcp.py'].append(src); routed = True
    elif name in SESSION_NAMES: MODULES['session.py'].append(src); routed = True
    elif name in MAIN_NAMES: MODULES['main.py'].append(src); routed = True

    # Catch remaining config-area assignments
    elif isinstance(node, ast.Assign) and start < 420 and not routed:
        MODULES['config.py'].append(src); routed = True

# Also add imports + module-level code for config.py
# Config needs the imports, platform init, optional deps, etc.
# Extract lines 1-420 from legacy as config preamble
config_preamble_end = None
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name == 'ensure_pkg':
        config_preamble_end = node.end_lineno
        break
    if isinstance(node, ast.ClassDef) and node.name == 'SimpleCache':
        config_preamble_end = node.end_lineno
        break

if config_preamble_end:
    preamble = '\n'.join(source_lines[:config_preamble_end])
else:
    preamble = '\n'.join(source_lines[:475])

# Write modules
DOCSTRINGS = {
    'config.py': '"""orca_code.config — Configuration, globals, cache, client."""',
    'utils.py': '"""orca_code.utils — Encoding, paths, tokens, cleanup."""',
    'security.py': '"""orca_code.security — Dangerous patterns, URL check, sandbox."""',
    'tools_core.py': '"""orca_code.tools_core — Core tools: execute, read, write, list, search."""',
    'tools_office.py': '"""orca_code.tools_office — Excel, Word, screenshot, OCR."""',
    'tools_web.py': '"""orca_code.tools_web — Web fetch, search, weather, location."""',
    'tools_dev.py': '"""orca_code.tools_dev — Git, code nav, vision, Python REPL."""',
    'tools_skills.py': '"""orca_code.tools_skills — Skill system + scheduler."""',
    'tools_automation.py': '"""orca_code.tools_automation — GUI + browser automation."""',
    'tts_mcp.py': '"""orca_code.tts_mcp — TTS, voice input, MCP protocol."""',
    'session.py': '"""orca_code.session — Session, system prompt, UI, messages, API."""',
    'main.py': '"""orca_code.main — Tool registry, user input, main loop."""',
}

for mod_name in MODULES:
    path = os.path.join(OUTDIR, mod_name)
    parts = [DOCSTRINGS.get(mod_name, '""""""'), '', '']

    if mod_name == 'config.py':
        # Config gets the full preamble (imports + init + all config code)
        parts.append(preamble)
        parts.append('')
        # Add remaining config defs
        parts.extend(MODULES[mod_name])
    else:
        parts.extend(MODULES[mod_name])

    content = '\n'.join(parts)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'{mod_name}: {len(MODULES[mod_name])} defs + preamble')

print('Done.')
