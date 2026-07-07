---
name: code-review-and-quality
title: 代码审查与质量
phase: REVIEW
description: 五维审查：正确性、可读性、架构、安全、性能
triggers:
  - review
  - 审查
  - 代码审查
  - code review
  - 质量检查
  - CR
---

## 概述

对代码进行五维审查，发现分类为 Critical / Important / Suggestion。

## 何时使用

- 完成 BUILD 阶段后
- 提交 PR 前自审
- 审查他人代码
- 用户说"帮我 review 一下"

## 流程

### 审查维度

1. **正确性** — 逻辑错误、边界条件、竞态、资源泄漏
2. **可读性** — 命名、注释（必要处）、复杂度
3. **架构** — 抽象层次、模块化、与现有模式一致
4. **安全** — 输入验证、认证、数据泄露（转交 security-and-hardening）
5. **性能** — N+1、不必要的计算、内存（转交 performance-optimization）

### 发现分级

- **CRITICAL**: 将导致 bug、数据丢失或崩溃
- **IMPORTANT**: 显著问题，应在合并前修复
- **SUGGESTION**: 值得改进但不阻塞

## 输出

按分级列出所有发现，给出修改建议和参考文件/行号。

## 验证

- [ ] 5 个维度都已审查
- [ ] 所有 CRITICAL 级别发现已修复
