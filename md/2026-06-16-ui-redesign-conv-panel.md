# 2026-06-16 UI 重构：对话面板 + 可调整三栏 + 连通性测试

## 现状问题

| 区域 | 问题 |
|---|---|
| 中间对话 | 用户/助手消息展示样式丑，没有 markdown 渲染、没有流式光标、空状态没设计 |
| 对话列表 | 藏在右侧 tab 里，只能"新建对话"，没有重命名/删除入口 |
| 三栏布局 | `left-panel`/`center-panel`/`right-panel` 都是固定宽度，拖不动 |
| 连通性测试 | 弹窗 + 写"测试中..."，看不到延迟，体验割裂 |

## 设计参考

`amazon-bestsellers/frontend/src/components/` 的设计：
- `Sidebar.tsx`：列表 + 状态点 + hover 显示删除图标
- `LiveStream.tsx`：用户右气泡 / 助手左文本 + 流式光标 + 自动滚动
- `App.tsx` 第 854-900 行：mousedown/mousemove/mouseup 三段式拖拽

## 新布局

四栏，全部可拖拽：

| 栏 | 宽度 | 内容 |
|---|---|---|
| ① 视频源 | 默认 200px，最小 160 / 最大 320 | 视频列表 + "AI Provider" 按钮（从顶栏搬下来） |
| ② 对话列表 | 默认 240px，最小 200 / 最大 400 | 新建按钮 + conv 行（标题/时间/重命名/删除） |
| ③ 对话流 | flex-1，最小 480 | 用户气泡 + 助手 markdown + 输入框 |
| ④ 详情 | 默认 360px，最小 280 / 最大 520 | 关键帧 / 转录 tabs |

3 个 resize handle（6px，hover 显 accent 线，body.is-resizing-columns 抑制选择）。

## 改造清单

### 后端

| 文件 | 改动 |
|---|---|
| `backend/database.py` | 加 `update_conversation(conv_id, **kwargs)` |
| `backend/main.py` | 加 `PUT /api/conversations/{id}`；`api_test_provider` 加 `elapsed_ms` 字段（用 `time.monotonic()` 包住 `models.list`） |

### 前端

| 文件 | 改动 |
|---|---|
| `static/index.html` | 4 栏布局；AI Provider 按钮从顶栏移到视频源栏底部；删除设置 cog 按钮（不再需要） |
| `static/css/style.css` | `.chat-bubble-user` / `.chat-bubble-assistant` / `.conv-row` / `.resize-handle` / `.test-status` 全部新增 |
| `static/js/api.js` | `updateConversation(id, {title})`；`testProvider(id)` 接收并展示 `elapsed_ms` |
| `static/js/ui.js` | `renderConvList()` / `renderChatMessages()` / `renderTestStatus()` |
| `static/js/app.js` | 新增 `_startResize(side, e)`；`_renameConv(id)`；`_deleteConv(id)`；连通性测试状态机 |

### 业务行为

- 重命名：行内 `<input>`，Enter 提交，Esc 取消，失焦提交
- 删除：hover 显垃圾桶，点击直接删（参考 amazon 风格，不要 confirm 弹窗）
- 测试连通：点击 ⟳ → 立即显示 `Loader2` 圈圈 → 完成后显示 `123ms` 或失败图标 + 错误信息；始终 inline 在按钮旁，不弹窗
- 拖拽：mousedown 记录起始 X + 当前宽度 → mousemove 累加 + clamp(min,max) → mouseup 解绑；宽度写 localStorage

## 验证

1. 后端 smoke 跑通
2. 浏览器：
   - 拖拽每个 handle，宽度符合 clamp
   - 新建/重命名/删除 conv 各跑一次
   - 输入消息看流式光标
   - 点测试连通看圈圈 → 延迟数字
3. 刷新后宽度保持（localStorage）
