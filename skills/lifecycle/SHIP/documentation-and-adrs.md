---
name: documentation-and-adrs
title: 文档与架构决策记录
phase: SHIP
description: ADR 格式、README 优先文档、CHANGELOG 管理
triggers:
  - 文档
  - ADR
  - 架构决策
  - documentation
  - README
  - CHANGELOG
  - 架构
---

## 概述

记录架构决策（ADR）和维护文档是 SHIP 阶段的必要步骤。

## ADR 格式

```markdown
# ADR-XXX: 标题

## 状态
已提议 / 已接受 / 已废弃 / 已取代

## 背景
为什么需要做这个决策？

## 决策
我们决定做什么。

## 后果
这样做的好处和代价。

## 备选方案
考虑了哪些其他方案，为什么不选。
```

## 文档原则

- README 是项目的入口，包含快速开始和核心概念
- CHANGELOG 按 Keep a Changelog 格式维护
- 内联代码注释只在"为什么"层面，不在"是什么"层面

## 验证

- [ ] 架构决策有 ADR 记录
- [ ] README 有快速开始部分
- [ ] CHANGELOG 已更新
