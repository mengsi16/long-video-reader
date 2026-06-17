# 2026-06-16 Chat Fail-Fast Fix 完工报告

## 根因链（修复前）

| 步骤 | 现象 | 原因 |
|---|---|---|
| 1 | 用户在设置 UI 保存 key/url | 仅写入 `localStorage`，从不上行 |
| 2 | 前端发起 chat 请求 | 没带 key/url（视而不见） |
| 3 | 后端 `api_chat` 接收请求 | 直接调用 `minimax_client.chat_stream()` |
| 4 | `chat_stream` 内部 `get_client()` | openai v2.x SDK 在 `__init__` 抛 `OpenAIError("Missing credentials")` |
| 5 | 异常被 `try/except` 吞掉 | SSE 流出 0 字节就关闭 |
| 6 | 前端 fetch 收不到数据 | 报 "network error"，用户无任何线索 |

辅助问题：
- 没有任何 `[chat]` 日志
- 异常完全没冒泡
- 前端 `onError` 回调是死代码
- 鉴权 401 同样被吞

## 架构改造

| 改造点 | 修复后 |
|---|---|
| Provider 配置 | 后端 SQLite `providers` 表，前端可增删查改 + 测连通 + 改默认（仿 one-api OpenAI 兼容通道模型） |
| api_chat 入口 | 接收 `provider_id`，未传则取 `get_default_provider()` |
| 异常处理 | 移出 `try/except` 让 fail-fast 冒泡；api_chat 内层统一转 SSE `{"type":"error", "error": str(e)}` 事件 |
| 日志 | `[chat]` 记录 masked key / provider / model / msg_len / chunks / elapsed / err |
| 启动兜底 | 没有 provider 时，从环境变量 `MINIMAX_API_KEY` + `MINIMAX_BASE_URL` 引导一个默认 provider |
| 前端拆文件 | 合并到 `static/js/{api,ui,app}.js`，删除 `static/app.js`（AGENTS.md 第 11 条） |
| 前端 cache | `?v=N` + 强制 no-cache 防旧代码被缓存 |
| 前端错误处理 | `api.js sendMessage` 增加 `resp.ok` 检查 + `type: error` SSE 事件回调 |

## 实施清单

| 文件 | 改动 | 状态 |
|---|---|---|
| `backend/database.py` | 新增 `providers` 表 + 7 个 CRUD 函数 | ✅ |
| `backend/minimax_client.py` | `get_client` 空 key 抛 `ValueError`；移除 `chat_stream` 的 try/except | ✅ |
| `backend/main.py` | 新增 6 个 Provider 端点 + 改造 `api_chat` + 启动兜底 + 日志 | ✅ |
| `static/app.js` | 删除 | ✅ |
| `static/js/api.js` | 重写：加 Provider CRUD + `sendMessage` 错误处理 | ✅ |
| `static/js/ui.js` | 加 `renderProvidersList` + `showProviderForm` | ✅ |
| `static/js/app.js` | 新建 VideoReader + Provider 管理 | ✅ |
| `static/index.html` | 改 script 路径 + 加 Provider 模态框 | ✅ |
| `static/css/style.css` | 删旧设置样式 + 加 Provider 样式 | ✅ |
| `scripts/smoke_chat.py` | 冒烟测试：mock 服务器 + 成功/失败两条路径 | ✅ |

## 验证结果

### 1. 后端冒烟测试（`scripts/smoke_chat.py`）

```
启动 mock 服务器...
========== 场景: 成功路径 (mock=success) ==========
  test endpoint: {'ok': True, 'models': ['MiniMax-M3', 'MiniMax-Text-01']}
  复用 conv=3 (video_id=4)
  事件统计: chunk=4 done=1 error=0
  拼接内容: '你好，视频分析'
  期望: 有 chunk + 1 个 done + 内容含'你好' -> ✅

========== 场景: 鉴权失败 (mock=auth_fail) ==========
  test endpoint: {'ok': True, 'models': [...]}
  事件统计: chunk=0 done=0 error=1
  期望: 1 个 error + 0 chunk -> ✅

🎉 所有冒烟测试通过
```

### 2. 后端日志（fail-fast 验证）

```
INFO:main:[chat] conv=3 provider=2(smoke-success) key=sk-s***-key model=MiniMax-M3 msg_len=6
INFO:main:[chat] done conv=3 provider=2 chunks=4 elapsed=5.0s

INFO:main:[chat] conv=3 provider=3(smoke-auth_fail) key=sk-s***-key model=MiniMax-M3 msg_len=6
ERROR:main:[chat] fail conv=3 provider=3 elapsed=4.6s err=Error code: 401 - {'error': {'message': 'Incorrect API key provided', 'type': 'auth'}}
```

key 已脱敏；chunks/elapsed/err 全部有日志可追踪。

### 3. 浏览器端到端验证

| 操作 | 结果 |
|---|---|
| 打开 AI Provider 模态框 | ✅ 显示现有 provider 列表 |
| 添加新 provider | ✅ 立即出现在列表，按钮计数 1 → 2 |
| 设为默认 | ✅ 移到列表头部，显示星标 |
| 关闭模态框 | ✅ 计数按钮同步显示 |
| 发送 chat 消息 | ✅ 走到后端，命中 provider=4(test-provider) |
| 真实错误时 UI 显示 | ✅ "发送失败: Error code: 503"（不再是黑盒 "network error"） |

后端日志同步显示：
```
INFO:main:[chat] conv=3 provider=4(test-provider) key=sk-t***-key model=MiniMax-M3 msg_len=27
ERROR:main:[chat] fail conv=3 provider=4 elapsed=7.9s err=Error code: 503
```

## AGENTS.md 对照

| 规则 | 落实 |
|---|---|
| 2. 不绕过错误，遵守 fail-fast | `get_client` 抛 ValueError；`chat_stream` 移 try/except；api_chat 内层仅做 SSE 转换 |
| 3. 先冒烟，再设计，再实现 | `scripts/smoke_chat.py` 先于任何"假设的失败"运行 |
| 7. 接口先探 | 改前端前 curl 探 `/api/providers`、`/api/videos`、`/api/conversations/{id}/chat` |
| 9. 计划入 md/ | 本报告 + 原计划 `chat-fail-fast-fix.md` |
| 11. 旧模块删 | `static/app.js` 已删 |
| 12. 单文件 < 800 行 | `main.py` 拆 6 个 Provider 端点；前端拆 3 个 js |
| 16. 不能 pytest 后不做端到端 | 已用浏览器手动跑全流程 |
| 18. 日志落盘 | `[chat]` 三种结果（done / fail / 异常路径）全有日志 |
| 21. 禁 TDD | 没有任何"先写测试再写实现"，所有代码都是直接实现目标 |

## 后续用户操作

用户在浏览器里点 AI Provider 按钮 → 添加真实 MiniMax provider → 测试连通 → 设为默认 → 就能正常对话了。
