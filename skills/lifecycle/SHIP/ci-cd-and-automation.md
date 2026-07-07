---
name: ci-cd-and-automation
title: CI/CD与自动化
phase: SHIP
description: CI 流水线设计、测试自动化、构建优化、部署策略（GitHub Actions 优先）
triggers:
  - CI
  - CD
  - 自动化
  - 流水线
  - pipeline
  - 部署
  - GitHub Actions
---

## 概述

设计可靠的 CI/CD 流水线。GitHub Actions 优先。

## CI 设计原则

1. **快速反馈** — lint 在 2 分钟内完成，测试在 10 分钟内完成
2. **隔离执行** — 每个 job 在独立环境中运行
3. **缓存依赖** — pip/npm/cargo 缓存加速
4. **并发矩阵** — 多版本 Python/Node 并行测试
5. **失败即终止** — lint 失败不继续跑测试

## 典型流水线

```
Lint (ruff + mypy) → Test (pytest matrix) → Security (sandbox tests) → Build (PyInstaller)
```

## 验证

- [ ] CI 流水线配置已写入 `.github/workflows/`
- [ ] 本地模拟 CI 命令可运行
- [ ] 流水线有缓存策略
