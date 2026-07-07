---
name: security-and-hardening
title: 安全加固
phase: REVIEW
description: 安全审计：输入验证、认证授权、数据保护、依赖审计
triggers:
  - 安全
  - security
  - 漏洞
  - 渗透
  - OWASP
  - 加固
  - 安全审查
---

## 概述

对代码进行安全审查。参考 [OWASP Top 10](https://owasp.org/www-project-top-ten/) 和 OWASP Top 10 for LLMs。

## 检查清单

### 输入验证
- SQL 注入：使用参数化查询，不拼接 SQL
- XSS：输出编码，不使用 `innerHTML`
- 命令注入：不使用 `os.system()` / `subprocess(shell=True)`
- SSRF：验证 URL，限制内网访问

### 认证授权
- 权限检查在每个入口点
- 不存在权限提升路径

### 数据保护
- 密钥不在代码中硬编码
- 敏感数据不在日志中输出
- 传输层使用 TLS

### 依赖安全
- 检查已知 CVE
- 锁定依赖版本

## 红旗信号

- 任何形式的 `eval()` / `exec()`
- 硬编码的密钥或 token
- SQL 拼接
- 不做输入验证的 API

## 验证

- [ ] 检查清单所有项目已审查
- [ ] 无 CRITICAL 或 HIGH 级别漏洞
