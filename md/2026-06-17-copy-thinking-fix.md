# 2026-06-17 复制按钮与思考框修复计划

## 冒烟观察

| 检查点 | 结果 |
|---|---|
| 浏览器当前页 | `http://0.0.0.0:8000/`，标题为 `AI Video Reader` |
| 可见助手消息数量 | 2 |
| 可见复制按钮数量 | 0 |
| 可见思考框数量 | 0 |
| 当前历史助手消息内容 | `content` 以 `<think>` 开头，思考内容被当作普通正文存储 |

## 根因判断

| 问题 | 根因 |
|---|---|
| 复制按钮缺失 | `_renderMessage()` 只渲染历史正文，没有复用流式结束后的复制按钮结构和事件绑定 |
| 思考内容没有进入框 | 模型把思考内容放在 `content` 的 `<think>...</think>` 片段中，后端当前只识别 `delta.reasoning_content` |
| 思考结束后框消失 | 前端没有收到 `type: thinking` 事件，`finalizeChatAssistant()` 判断思考内容为空后删除了 `<details>` |

## 修复范围

| 文件 | 动作 |
|---|---|
| `backend/minimax_client.py` | 增加基于 `<think>` 与 `</think>` 的流式分流，继续兼容 `reasoning_content` |
| `static/js/ui.js` | 历史消息渲染时解析已有 `<think>` 内容，渲染思考框与复制按钮 |
| `static/js/ui.js` | 提取复制按钮创建与事件绑定，流式消息和历史消息共用同一实现 |
| `static/js/app.js` | 保持现有流式调用路径，确认不引入重复接口 |

## 验证计划

| 类型 | 命令或操作 | 通过标准 |
|---|---|---|
| 静态检查 | `python -m py_compile backend/minimax_client.py backend/main.py` | 退出码为 0 |
| 后端冒烟 | 运行包含 `<think>` 分块的本地函数级检查 | 输出包含 `thinking` 与 `content` 两类事件 |
| 浏览器验证 | 重新加载页面查看历史对话 | 每条助手消息有复制按钮，历史 `<think>` 被放入思考框 |
| 端到端验证 | 在页面发送一条新消息 | 流式思考进入思考框，结束后思考框保留，复制按钮出现 |
