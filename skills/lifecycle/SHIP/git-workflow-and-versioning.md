---
name: git-workflow-and-versioning
title: Git工作流与版本管理
phase: SHIP
description: 分支策略、Conventional Commits、rebase、冲突解决、标签管理
triggers:
  - git
  - 提交
  - 分支
  - merge
  - rebase
  - 版本管理
  - commit
---

## 概述

标准的 Git 工作流和版本管理规范。

## 提交消息格式

使用 Conventional Commits：
```
<type>(<scope>): <description>

feat:    新功能
fix:     Bug 修复
refactor: 重构
test:    测试
docs:    文档
chore:   工具/配置
```

## 流程

1. 从最新的 main 创建功能分支
2. 增量提交（每个 task 一个 commit）
3. 提交前运行测试
4. PR/MR 前 rebase 到最新 main
5. 合并后用 `git tag vX.Y.Z` 打标签

## 验证

- [ ] 提交消息符合 Conventional Commits 格式
- [ ] 分支基于最新的 main
- [ ] 所有测试通过
