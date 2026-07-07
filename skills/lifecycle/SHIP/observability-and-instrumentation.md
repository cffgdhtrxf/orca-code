---
name: observability-and-instrumentation
title: 可观测性与监控
phase: SHIP
description: 结构化日志、指标（RED/USE）、分布式追踪、告警、仪表盘
triggers:
  - 监控
  - 日志
  - metrics
  - 告警
  - observability
  - 可观测性
  - 追踪
---

## 概述

在发布前确保系统可观测：知道系统在做什么、出问题时能快速定位。

## 三大支柱

### 1. 结构化日志
- JSON 格式，包含 timestamp、level、module、message、context
- 不要记录敏感数据
- 错误日志包含 stack trace

### 2. 指标（Metrics）
- RED 方法（Rate/Errors/Duration）：每个服务端点
- USE 方法（Utilization/Saturation/Errors）：每个资源

### 3. 追踪（Tracing）
- 关键用户请求的完整链路
- 数据库查询、外部 API 调用的耗时

## 告警规则

- 告警基于症状（用户感受到的问题），不是原因
- 每条告警有对应的操作手册
- 没有对应操作的告警是噪音

## 验证

- [ ] 关键路径有日志
- [ ] 错误率可监控
- [ ] 有基本的告警规则
