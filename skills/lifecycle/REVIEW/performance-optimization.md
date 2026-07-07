---
name: performance-optimization
title: 性能优化
phase: REVIEW
description: Core Web Vitals、数据库查询、打包体积、渲染性能。先测量再优化。
triggers:
  - 性能
  - performance
  - 优化
  - 慢
  - 延迟
  - LCP
  - 加载速度
  - 卡顿
---

## 概述

性能优化第一原则：先测量，再优化。不要猜测瓶颈在哪里。

## 指标目标

| 指标 | 目标 | 测量工具 |
|------|------|---------|
| LCP | ≤2.5s | Lighthouse / Web Vitals |
| INP | ≤200ms | Lighthouse |
| CLS | ≤0.1 | Lighthouse |
| TTFB | ≤800ms | DevTools Network |
| FCP | ≤1.8s | Lighthouse |

## 检查领域

### 前端
- 图片：压缩、懒加载、响应式
- JS：代码分割、tree-shaking、移除未使用代码
- CSS：未使用样式、关键 CSS 内联
- 字体：font-display: swap、子集化

### 后端
- 数据库：检查 N+1 查询、添加索引、连接池
- 缓存：添加 HTTP 缓存、内存缓存
- API：响应体大小、压缩、分页

## 80/20 原则

找到最大的瓶颈（通常只有一个），优化它，然后重新测量。不要花时间优化只占 5% 时间的热点。

## 验证

- [ ] 优化前有基准测量
- [ ] 优化后有对比测量
- [ ] 优化目标已达成
