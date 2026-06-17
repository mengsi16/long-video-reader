# 复制按钮 + 思考折叠 + Provider 切换

## 目标

1. **复制按钮**：每段模型输出完，下方出现一个带边框的小图标按钮，点击后把纯文本复制到剪贴板。
2. **思考折叠**：模型 reasoning_content 单独累积，渲染为可折叠面板（默认收起），与最终 content 分离。
3. **Provider 切换**：除"设为默认"外，用户可点击某行"选用"该 provider（仅本次对话使用），UI 显示当前 active 状态。

---

## 现状

| 关注点 | 文件 | 现状 |
|---|---|---|
| SSE 事件类型 | [main.py:415,422,430](backend/main.py:415) | 只有 `chunk` / `done` / `error` |
| 流式 chunk 来源 | [minimax_client.py:85-87](backend/minimax_client.py:85) | 只 yield `delta.content` |
| 前端流式 append | [ui.js:535-547](static/js/ui.js:535) | `appendChatAssistant` 渲染 markdown + cursor |
| 前端流式 update | [ui.js:562-572](static/js/ui.js:562) | `updateChatAssistant` 重渲染整个 markdown |
| Provider 选用 | [app.js:454-455](static/js/app.js:454) | `activeProviderId = providers.find(p => p.is_default).id` |
| Provider row 渲染 | [ui.js:305-325](static/js/ui.js:305) | 只有 default / test / edit / delete 按钮，无"选用" |

---

## 设计

### 1. 复制按钮

样式参考：两个并排的方框带边框小按钮（用户给的图）。

```
┌──────────────────────────────────┐
│ 这是模型输出的内容...            │
│ 段落二...                        │
└──────────────────────────────────┘
┌──┐ ┌──┐
│📋│ │📁│   <- 复制 / 折叠
└──┘ └──┘
```

- 位置：assistant 气泡下方居中
- 状态：消息 `done` 事件触发后挂上；流式中隐藏
- 行为：点击 → `navigator.clipboard.writeText(content)` → 图标变为 ✓ 0.8s
- 不带折叠按钮的备用方案：先做复制，后续看是否需要加

### 2. 思考折叠

```
┌─────────────────────────────────┐
│ 🧠 已思考 12.4s            ▾    │  <- 折叠头部（默认收起）
├─────────────────────────────────┤
│ 思考内容（默认隐藏）            │
└─────────────────────────────────┘
下面是正式回答 markdown 渲染...
```

- 后端：在 [minimax_client.py:85](backend/minimax_client.py:85) 增加 `if chunk.choices[0].delta.reasoning_content: yield reasoning_content`
- 后端：[main.py:413-415](backend/main.py:413) 区分 `reasoning_chunk` 和 `content_chunk`，分别 yield `type: 'thinking'` 和 `type: 'chunk'`
- 前端：app.js 维护 `thinkingContent` 和 `fullContent` 两个变量；`ui.updateChatAssistant` 接 thinking 参数
- 前端：thinking 面板默认 `<details>` HTML 元素，open=false
- 持久化：数据库不存 thinking，只存最终 content

### 3. Provider 切换

- UI：provider row 整行可点击 → 触发 `_selectProvider(id)`，调用 `_loadProviders` 后设置 `this.activeProviderId = id`
- 视觉：当前选中的 row 加 `.provider-row.active`（区别于 `.is-default`），用左侧 3px 强调色边框
- 行为：点击 row 主体 = 选用；点击右侧 action 按钮（default/test/edit/delete）= 各自动作，stopPropagation
- 默认状态：进入弹窗时，active = 当前 `this.activeProviderId`（首次 = is_default）
- 关闭弹窗时 `activeProviderId` 已更新，下次发消息用这个
- 提示：弹窗底部加一行小字"当前选用：xxx"

---

## 修改清单

### 后端
- [backend/minimax_client.py:85](backend/minimax_client.py:85) — 增加 `reasoning_content` yield
- [backend/main.py:413-415](backend/main.py:413) — 区分 thinking / content，SSE 事件分别为 `thinking` / `chunk`

### 前端 JS
- [static/js/api.js:154-160](static/js/api.js:154) — 新增 `data.type === 'thinking'` 处理
- [static/js/app.js:592](static/js/app.js:592) — `_sendMessage` 拆 `thinkingContent` / `fullContent`；finalize 时挂载复制按钮
- [static/js/app.js:496](static/js/app.js:496) — 新增 `_selectProvider(id)` 切换 active
- [static/js/ui.js:511-520](static/js/ui.js:511) — `_renderMessage` 支持 thinking 数据
- [static/js/ui.js:535-547](static/js/ui.js:535) — `appendChatAssistant` 接受 thinking 容器
- [static/js/ui.js:562-572](static/js/ui.js:562) — `updateChatAssistant` 接受 thinking 参数
- [static/js/ui.js:570](static/js/ui.js:570) — `finalizeChatAssistant` 挂载 `.bubble-actions` 复制按钮
- [static/js/ui.js:294](static/js/ui.js:294) — `renderProvidersList` 行点击 + 接受 activeProviderId
- [static/js/ui.js:325](static/js/ui.js:325) — provider row 加 `.provider-row.active` 类

### CSS
- [static/css/style.css](static/css/style.css) — 新增：
  - `.bubble-actions` 居中小图标按钮
  - `.bubble-action` 28x28 边框方形按钮（参考图样式）
  - `.bubble-action.copied` 复制成功状态
  - `.chat-thinking` 折叠面板（details / summary）
  - `.provider-row.active` 左侧 3px accent 边框
  - `.provider-current` 弹窗底部状态文字

### 验证
1. 浏览器发送消息，模型输出完毕后气泡下方出现复制按钮 → 点击 → 剪贴板含纯文本 → 图标变 ✓
2. 模拟带 reasoning_content 的 SSE 事件，折叠面板默认收起，点击展开
3. 打开 AI Provider 弹窗，点击非默认 row → 视觉高亮 active → 关闭弹窗 → 发送消息使用 active provider

### 端到端
- 加 [scripts/smoke_thinking.py](scripts/smoke_thinking.py) 模拟返回 reasoning_content 的 mock，验证 SSE 事件分流
