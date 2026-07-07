---
name: spec-driven-development
title: 规格驱动开发
phase: DEFINE
description: 在编码前编写结构化规格说明，覆盖目标、架构、代码风格、测试策略和边界
triggers:
  - 写spec
  - 规格
  - 需求文档
  - PRD
  - spec
  - 需求分析
  - 技术方案
---

## 概述

在写任何代码之前，先写一份结构化的规格说明（SPEC.md）。规格说明是实现的蓝图，不是需求文档。

## 何时使用

- 任何需要编码的新功能
- 涉及架构决策的改动
- 可能影响现有系统的改动
- 团队协作（即使是一个人团队，spec 也帮助理清思路）

## 流程

### 第一步：项目命令
列出该项目会用到的关键命令，方便后续开发：
```markdown
## Commands
- 构建: `python -m build`
- 测试: `pytest tests/ -v`
- 运行: `python main.py`
```

### 第二步：项目结构
定义文件/目录结构：
```markdown
## Project Structure
src/
├── module_a/
│   ├── __init__.py
│   └── core.py
└── module_b/
    └── ...
```

### 第三步：代码风格
明确风格约定（来自项目已有配置或团队规范）：
- 类型注解必须
- 行长度 100
- import 顺序：标准库 → 第三方 → 本地

### 第四步：测试策略
- 测试框架和运行命令
- 哪些模块需要多少覆盖
- Mock 策略（mock at boundaries only）

### 第五步：边界与限制
- 不做的事情（anti-scope）
- 已知的技术限制
- 未来兼容性考虑

## 输出

写入 `SPEC.md` 到工作区根目录。LLM 在后续 BUILD 阶段会参考此文件。

## 验证

- [ ] SPEC.md 包含全部 5 个部分
- [ ] 测试命令可运行
- [ ] 项目结构路径与实际匹配
