---
name: deprecation-and-migration
title: 废弃与迁移
phase: SHIP
description: 废弃策略：标记→警告→迁移→移除。兼容层→并行运行→切换→清理
triggers:
  - 废弃
  - 迁移
  - 升级
  - deprecate
  - migration
  - 兼容性
  - 版本升级
---

## 概述

安全的废弃和迁移流程，最小化对用户的影响。

## 废弃策略

1. **标记** — 在旧接口上添加 `@deprecated` 注解或文档标记
2. **警告** — 运行时发出 DeprecationWarning，说明替代方案和截止版本
3. **迁移** — 提供迁移指南和 codemod 脚本
4. **移除** — 在截止版本后移除

## 迁移流程

1. **兼容层** — 新旧接口共存，新接口包装旧实现
2. **并行运行** — 双写/双读，验证一致性
3. **切换** — 默认使用新实现，旧实现作为 fallback
4. **清理** — 移除旧实现和兼容层

## 验证

- [ ] 废弃接口有 DeprecationWarning
- [ ] 迁移指南已更新
- [ ] 移除旧实现后测试全部通过
