# LICENSE 与 NOTICE 版权声明计划

## 目标

为当前项目补充明确版权归属声明，并提交推送到远程仓库。

## 修改范围

| 文件 | 操作 |
| --- | --- |
| `NOTICE` | 新增项目版权声明 |
| `README.md` | 增加版权与许可证小节 |
| `md/2026-06-17-license-notice-copyright.md` | 记录本次计划 |

## 内容约定

| 项目 | 内容 |
| --- | --- |
| 版权年份 | 2026 |
| 版权持有人 | mengsi16 |
| 许可证 | Apache License 2.0 |

## 验证

| 检查 | 命令 |
| --- | --- |
| 文本检查 | `rg -n "Copyright 2026 mengsi16|Apache License 2.0" README.md NOTICE` |
| Git 检查 | `git diff --check` |
| 推送检查 | `git status --short --branch` |
