# FFmpeg 与 requirements 配置修正计划

## 问题判断

| 问题 | 影响 |
| --- | --- |
| `.env.example` 没有 `FFMPEG_PATH` / `FFPROBE_PATH` | Windows 本地安装 FFmpeg 后不方便显式配置 |
| 代码没有加载 `.env` | README 里的 `copy .env.example .env` 对运行进程不生效 |
| `requirements.txt` 默认包含 `static-ffmpeg` | Docker 已安装系统 FFmpeg，本地也可以装系统 FFmpeg，默认依赖容易误导 |
| `start.py` 仍检查旧 OpenAI 环境变量 | 当前项目实际使用 MiniMax/OpenAI 兼容 Provider 配置 |
| README 没讲 FFmpeg 具体配置 | 用户不知道应该装系统 FFmpeg、配路径，还是依赖 pip 包 |

## 修改范围

| 文件 | 操作 |
| --- | --- |
| `requirements.txt` | 移除 `static-ffmpeg`，新增 `python-dotenv` |
| `.env.example` | 增加 FFmpeg 路径配置示例 |
| `backend/config.py` | 启动时加载项目根目录 `.env` |
| `backend/video_processor.py` | FFmpeg 查找顺序改为环境变量、系统 PATH、可选 static-ffmpeg |
| `start.py` | 加载 `.env`，检查 FFmpeg 与当前 MiniMax 配置 |
| `README.md` | 增加 FFmpeg 配置说明 |

## 验证

| 检查 | 命令 |
| --- | --- |
| Python 编译 | `python -m compileall backend scripts start.py` |
| FFmpeg 检查 | `python start.py --check` |
| Git 检查 | `git diff --check` |
