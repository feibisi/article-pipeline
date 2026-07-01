# 贡献指南

## 开发环境

```bash
# 安装开发依赖
pip install -e ".[test]"

# 运行测试
pytest tests/ -v
```

## 代码结构

```
article_pipeline/
├── db.py              # SQLite 任务队列
├── research.py        # cocobook MCP + DDG 搜索
├── outline.py         # 结构化大纲生成
├── synthesis.py       # 综合分析层 (Layer 1)
├── framework.py       # 框架设计层 (Layer 2)
├── style.py           # 风格定义层 (Layer 3)
├── prosody.py         # 语感引导层 (Layer 4)
├── compile.py         # 编译层 (Layer 5)
├── writer.py          # LLM 写作
├── review/            # 质量评分模块
│   ├── __init__.py    # 主评分逻辑
│   ├── ai_detection.py
│   ├── fabrication.py
│   ├── humanizer.py
│   ├── style_compliance.py
│   └── value_density.py
├── pipeline.py        # 编排全流程
├── publish.py         # WordPress 发布
└── review_server.py   # Web UI
```

## 添加新品类

1. 在 `genres/*/framework.yaml` 定义方法论
2. 在 `style.py` 的 `_PRESETS` 添加风格预设
3. 在 `writer.py` 的 `GENRE_RULES` 添加规则

## 添加评分维度

在 `review/__init__.py` 的 `compute_overall_score()` 添加权重，在 `run_self_review()` 实现检测逻辑。

## 文档变更

- 系统变更 → 更新 `docs/SYSTEM-DEFINITION.md`
- 风格变更 → 更新 `docs/STYLE-SYSTEM.md`
- 完成任务 → 更新 `docs/ROADMAP.md`

## 提交规范

```
feat: 添加新功能
fix: 修复问题
docs: 文档更新
refactor: 重构代码
test: 测试相关
```
