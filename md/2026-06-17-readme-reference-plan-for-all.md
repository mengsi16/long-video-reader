# README 参考 plan-for-all 改写计划

## 目标

参考 `E:\PostGraduate\Project\plan-for-all` 项目的 README 风格，重写 `video-reader` 的 README，把 API 清单从 README 移到独立 API 文档。

## 参照结论

| 参照项 | 采用方式 |
| --- | --- |
| 顶部居中标题和一句话定位 | 用于 `video-reader` |
| 先讲痛点，再讲核心思想 | 用于替代当前偏接口说明的写法 |
| 用表格说明原则、文件、能力 | 保留，便于快速扫读 |
| Mermaid 工作流图 | 保留，用于说明视频阅读流程 |
| 安装与使用放后面 | 保留，README 先讲项目价值 |
| API 列表 | 从 README 移到 `md/api.md` |

## 修改范围

| 文件 | 操作 |
| --- | --- |
| `README.md` | 重写为产品/项目说明型 README，移除 API 清单 |
| `md/api.md` | 新增 API 文档，承接原 README 中接口列表 |
| `md/2026-06-17-readme-reference-plan-for-all.md` | 记录本次修改计划 |

## 验证

| 检查 | 命令 |
| --- | --- |
| README 不再出现 API 概览标题 | `rg -n "API 概览|/api/" README.md` |
| API 文档包含接口列表 | `rg -n "/api/videos|/api/conversations|/api/providers" md/api.md` |
| 暂存检查 | `git diff --check` |
