# 2026-06-17 助手消息左对齐修复计划

## 冒烟观察

| 检查点 | 结果 |
|---|---|
| 用户标记元素 | 助手消息下方 `.bubble-action` 复制按钮 |
| 当前按钮布局 | `.bubble-actions { justify-content: center; }` 导致按钮居中 |
| 当前助手消息布局 | `.chat-bubble-assistant { justify-content: center; flex-direction: column; align-items: stretch; }` |
| 用户反馈 | 复制按钮居中，开始输出与输出后位置不一致 |

## 根因判断

| 现象 | 根因 |
|---|---|
| 复制按钮居中 | 按钮组继承整行宽度后使用 `justify-content: center` |
| 初始输出和结束输出视觉位置不一致 | 助手消息容器按居中布局设计，流式占位、正文、按钮三个子块没有固定左侧起点 |

## 修复范围

| 文件 | 修改 |
|---|---|
| `static/css/style.css` | 将助手消息容器改为左对齐纵向布局 |
| `static/css/style.css` | 让正文、思考框、按钮组共享 100% 宽度 |
| `static/css/style.css` | 将 `.bubble-actions` 改为左对齐 |

## 验证计划

| 类型 | 操作 | 通过标准 |
|---|---|---|
| 静态检查 | `node --check static/js/ui.js` | 退出码为 0 |
| 浏览器验证 | 刷新页面并打开历史对话 | 复制按钮贴近助手正文左侧起点 |
| 布局验证 | 检查 DOM 盒模型 | `.bubble`、`.bubble-actions` 左边界一致 |
