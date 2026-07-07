# Orca Code 项目指南

## 设计哲学

### 开箱即用（Out-of-box Experience First）

Orca Code 的首要设计目标是**开箱即用**：

1. **密钥管理**：直接修改 `config.json`、填入 API 密钥即可运行。环境变量/密钥链是推荐但不强制的方式。`warn_plaintext_keys()` 只打印警告，不阻止启动。
2. **自动安装依赖**：设置 `auto_install_deps: true` 后，缺失的 Python 包（如 headroom-ai）会在首次使用时自动 pip install。
3. **无环境变量依赖**：不需要 `CI=1`、`ORCA_ALLOW_PLAINTEXT=1` 等环境变量来绕过检查。测试也不依赖外部环境。
4. **优雅降级**：可选依赖（headroom、GUI 自动化、浏览器自动化等）缺失时自动降级，不影响核心功能。

### 架构原则

- **安全性**：3 层安全模型（安全网 → 权限系统 → 沙箱），Security Spectre 静态模式作为补充
- **模块化**：功能模块通过 `try/except ImportError` 优雅降级，不强制依赖
- **生命周期工作流**：DEFINE → PLAN → BUILD → VERIFY → REVIEW → SHIP 6 个阶段，通过 slash 命令和 auto-trigger 驱动
- **Token 压缩**：headroom-ai 可选的 6 算法压缩，自动降级为规则摘要

## 关键文件

| 文件 | 说明 |
|------|------|
| `config.json` | 配置和密钥（明文可接受） |
| `orca_code/slash_commands.py` | 所有 / 命令处理器 |
| `orca_code/security.py` | 3 层安全模型 |
| `orca_code/security_scan.py` | 静态安全模式（移植自 SkillSpector） |
| `orca_code/session_compaction.py` | 上下文压缩（headroom + 降级） |
| `orca_code/constitution.py` | Constitution + Anti-Rationalization |
| `skills/lifecycle/` | 23 个生命周期 SKILL.md |
| `agents/` | 4 个 agent persona prompt |

## 密钥优先级

```
环境变量 > 系统密钥链 > 加密文件 > config.json 明文
```

优先级最高的是环境变量，最简单的是 config.json 明文。两者都不配置时启动会打印警告但不会退出。

## 运行

```bash
pip install -e .           # 核心安装
pip install -e ".[all]"    # 全部依赖（含 headroom 压缩）
# 或设置 auto_install_deps: true 自动安装
python orca_code.py        # 启动
```
