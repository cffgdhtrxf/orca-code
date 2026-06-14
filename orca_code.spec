# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Orca Code single-file executable."""

a = Analysis(
    ['orca_code.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config.example.json', '.'),
        ('skills/', 'skills/'),
        ('models/', 'models/'),
        ('memory/', 'memory/'),
        ('orca_code/prompts/', 'orca_code/prompts/'),
    ],
    binaries=[
        ('orca_native/python/orca_native.pyd', 'orca_native/'),
    ],
    hiddenimports=[
        'openai', 'rich', 'requests', 'charset_normalizer',
        'orca_code', 'orca_code.config', 'orca_code.main',
        'orca_code.session', 'orca_code.tool_registry',
        'orca_code.tools_core', 'orca_code.tools_web', 'orca_code.tools_office',
        'orca_code.tools_dev', 'orca_code.tools_skills', 'orca_code.tools_automation',
        'orca_code.tts_mcp', 'orca_code.subagent', 'orca_code.lsp',
        'orca_code.permissions', 'orca_code.security', 'orca_code.constitution',
        'orca_code.utils', 'orca_code.session_messages', 'orca_code.session_prompt',
        'orca_code.session_ui', 'orca_code.session_stream',
        'orca_code.cli', 'orca_code.cli.commands',
        'orca_code.core', 'orca_code.core.errors', 'orca_code.core.event_bus',
        'orca_code.infrastructure', 'orca_code.infrastructure.config_loader',
        'orca_code.infrastructure.platform', 'orca_code.infrastructure.provider_client',
        'orca_code.infrastructure.feature_flags', 'orca_code.infrastructure.helpers',
        'orca_code.infrastructure.secrets', 'orca_code.infrastructure.prompt_loader',
        'orca_code.providers', 'orca_code.providers.base', 'orca_code.providers.registry',
        'orca_code.providers.deepseek', 'orca_code.providers.openai_compat',
        'orca_code.providers.anthropic_compat', 'orca_code.providers.local',
        'orca_code.orchestrator', 'orca_code.server', 'orca_code.bridge',
        'orca_code.daemon', 'orca_code.session_persistence',
        'orca_code.memory',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'unittest', 'email', 'http', 'xml', 'html',
        'pydoc', 'distutils', 'setuptools',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='orca_code',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
