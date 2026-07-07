---
name: browser-testing-with-devtools
title: 浏览器测试与DevTools
phase: VERIFY
description: Playwright E2E、DevTools 性能分析、网络调试、可访问性审查
triggers:
  - 浏览器测试
  - E2E
  - DevTools
  - Playwright
  - 前端测试
  - 浏览器
  - 端到端测试
---

## 概述

使用浏览器自动化工具和 DevTools 进行前端测试和调试。

## 何时使用

- 浏览器端的 E2E 测试
- 性能问题分析
- 网络请求调试
- 可访问性审查

## 工具

- `browser_open` / `browser_click` / `browser_type` — Playwright 自动化
- `browser_screenshot` — 截图对比
- `execute_command` — 运行 Lighthouse CLI

## 流程

1. 打开浏览器到目标页面
2. 执行用户操作流程
3. 截图验证 UI 状态
4. 必要时运行可访问性检查

## 验证

- [ ] 关键用户流程可用
- [ ] 无控制台错误
- [ ] 可访问性基本检查通过
