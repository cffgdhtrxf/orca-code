---
name: shipping-and-launch
title: 发布与上线
phase: SHIP
description: 预发布检查清单：并行审查 code-reviewer、security-auditor、test-engineer，给出 go/no-go 决策
triggers:
  - 发布
  - 上线
  - launch
  - ship
  - deploy
  - 灰度
  - 发版
---

## 概述

发布前的最终检查。并行调用 3 个 specialist persona 审查，汇总后给出 go/no-go 决策。

## 流程

### Phase A：并行审查
同时触发三个角色：
- **code-reviewer** — 代码质量审查
- **security-auditor** — 安全审查
- **test-engineer** — 测试覆盖审查

### Phase B：汇总
收集三个角色的发现：
- 是否有 CRITICAL 级别的发现？
- 是否有未通过的测试？
- 是否有安全漏洞？

### Phase C：决策
- **GO** — 所有审查通过，无 blocking issues
- **NO-GO** — 存在 blocking issues，列出必须修复的事项
- **GO WITH RISKS** — 有 non-blocking 问题，记录在 release notes

## 发布检查清单

- [ ] 所有 P0 测试通过
- [ ] 代码审查通过
- [ ] 安全审查通过
- [ ] CHANGELOG 已更新
- [ ] 版本号已更新
- [ ] 有回滚计划

## 验证

- [ ] 3 个角色已完成审查
- [ ] 发布了 go/no-go 决策
- [ ] 决策记录了理由
