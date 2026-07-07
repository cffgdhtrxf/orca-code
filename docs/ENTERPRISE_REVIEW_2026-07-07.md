# Orca Code v5.1 — 企业级代码审查报告

**审查日期**: 2026-07-07  
**审查范围**: 75+ Python 模块, 12 测试文件, 5 Rust crate  
**严重等级**: P0=立即修复, P1=本次发布前, P2=2 sprint 内, P3=技术债务

---

## P0 — 必须立即修复

### P0-1 CI 失败吞没
**文件**: `.github/workflows/ci.yml`
**问题**: 每一行 lint/mypy/test/build 命令都加了 `|| echo "completed"`，导致 CI 永远 ✅ 绿色。
**修复**: 移除所有 `|| echo "completed"`，让 CI 真正报告失败。

### P0-2 Python exec() 沙箱逃逸
**文件**: `orca_code/security.py:_safe_exec_skill()` (line 348-368)
**问题**: `exec()` 即使 AST 扫描通过，也存在已知逃逸技术（frame 操纵、`__code__` 替换、metaclass 滥用）。
**修复**: 改用 subprocess 隔离执行，移除直接 exec()。

### P0-3 API 密钥明文存储
**文件**: `orca_code/infrastructure/secrets.py` (line 358-378)
**问题**: `warn_plaintext_keys()` 仅打印警告，不阻止启动。
**修复**: 含有真实 API 密钥的明文配置应阻止启动并提示迁移命令。

---

## P1 — 应在本次发布前修复

### P1-1 main.py 拆分 (801 行)
**文件**: `orca_code/main.py`
**问题**: 集成了 CLI 输入、slash 命令、消息循环、自动保存、记忆管理、TTS、LSP。
**修复**: 提取到 `cli_loop.py` + `slash_commands.py` + `multimodal_handler.py`。

### P1-2 server.py 拆分 (1278 行)
**文件**: `orca_code/server.py`
**问题**: 路由、控制器、服务层混在一起。
**修复**: 按路由拆分。

### P1-3 双工具系统合并
**文件**: `orca_code/tools_core.py`, `orca_code/tools/*.py`, `orca_code/tools/bridge.py`
**问题**: flat function 和 class-based 两种工具系统并存，bridge.py 负责同步。
**修复**: 选择 class-based 系统作为主方案，删除 flat 函数，移除 bridge.py。

### P1-4 循环导入变通方案
**文件**: `orca_code/tool_registry.py` (line 1014-1031)
**问题**: `_LAZY_TOOLS` 延迟解析标记用于规避 main.py 循环导入。
**修复**: 将 `recall_conversation` / `update_profile` 移出 main.py 到独立模块。

### P1-5 `_resolve()` 线程安全
**文件**: `orca_code/tool_registry.py` (line 1023-1030)
**问题**: 延迟初始化时 TOOL_MAP 在调用时被突变，多线程竞态。
**修复**: 启动时一次性解析所有工具，或加锁。

### P1-6 CI 覆盖目标 70% → 85%
**文件**: `pyproject.toml` (line 221)
**问题**: 覆盖率目标偏低。
**修复**: 提高至 85%。

### P1-7 循环导入重构
**文件**: `orca_code/main.py` 与各子模块
**问题**: main.py 同时是导入中心和被导入目标。
**修复**: 提取独立模块破坏循环。

---

## P2 — 应在 2 sprint 内完成

### P2-1 GUI/浏览器测试加入 CI
**文件**: `.github/workflows/ci.yml`
**问题**: 明确跳过 GUI 和浏览器测试。

### P2-2 全面审计 `except: pass`
**文件**: 全仓库 40+ 处
**问题**: 静默吞异常，隐藏错误。

### P2-3 conftest.py 增强
**文件**: `tests/conftest.py`
**问题**: 只有 3 个 fixture。
**修复**: 添加 mock HTTP server、mock LLM 响应、mock 文件系统 fixture。

### P2-4 覆盖不足的模块加测试
**文件**: `tests/`
**问题**: `server.py` (1278 行) 和 `config.py` (236 行) 基本无单元测试。

### P2-5 `except: pass` 审计替换
**文件**: 全仓库
**修复**: 至少记录日志，不静默吞异常。
