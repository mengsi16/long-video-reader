#!/usr/bin/env python3
"""
video-reader 启动脚本
"""

import os
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

def check_dependencies():
    """检查依赖是否安装"""
    import sys
    required_packages = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "yt-dlp": "yt_dlp",
        "faster-whisper": "faster_whisper",
        "openai": "openai",
        "python-dotenv": "dotenv"
    }

    missing_packages = []
    for display_name, import_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(display_name)

    if missing_packages:
        print("[ERROR] 缺少以下依赖包:")
        for package in missing_packages:
            print(f"   - {package}")
        print("\n请运行以下命令安装依赖:")
        print("source venv/bin/activate && pip install -r requirements.txt")
        return False

    print("[OK] 所有依赖已安装")
    return True

def check_ffmpeg():
    """检查FFmpeg是否安装"""
    import shutil
    ffmpeg_path = os.getenv("FFMPEG_PATH")
    ffprobe_path = os.getenv("FFPROBE_PATH")

    if ffmpeg_path and ffprobe_path:
        print(f"FFmpeg: {ffmpeg_path}")
        print(f"FFprobe: {ffprobe_path}")
        return True

    ffmpeg_found = shutil.which("ffmpeg")
    ffprobe_found = shutil.which("ffprobe")
    if ffmpeg_found and ffprobe_found:
        print(f"FFmpeg: {ffmpeg_found}")
        print(f"FFprobe: {ffprobe_found}")
        return True

    print("未找到 FFmpeg/FFprobe")
    print("请安装 FFmpeg 并加入系统 PATH，或在 .env 中设置 FFMPEG_PATH 和 FFPROBE_PATH")
    return False

def load_environment():
    """加载项目根目录 .env。"""
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")

def setup_environment():
    """设置环境变量"""
    if os.getenv("MINIMAX_API_KEY"):
        print("[OK] 已设置默认模型 API Key")
    else:
        print("[WARN] 未设置 MINIMAX_API_KEY，可在页面 AI Provider 管理中添加")

    if not os.getenv("WHISPER_MODEL_SIZE"):
        os.environ["WHISPER_MODEL_SIZE"] = "base"

    return True

def main():
    """主函数"""
    # 检查是否使用生产模式（禁用热重载）
    production_mode = "--prod" in sys.argv or os.getenv("PRODUCTION_MODE") == "true"
    check_only = "--check" in sys.argv

    print("video-reader 启动检查")
    if production_mode:
        print("生产模式 - 热重载已禁用")
    else:
        print("开发模式 - 热重载已启用")
    print("=" * 50)

    # 检查依赖
    if not check_dependencies():
        sys.exit(1)

    load_environment()

    # 检查FFmpeg
    if not check_ffmpeg():
        print("[WARN] FFmpeg 未安装，可能影响某些视频格式的处理")

    # 设置环境
    setup_environment()

    print("\n启动检查完成!")
    print("=" * 50)
    if check_only:
        return

    # 启动服务器
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))

    print("\n启动服务器...")
    print(f"   地址: http://localhost:{port}")
    print(f"   按 Ctrl+C 停止服务")
    print("=" * 50)

    try:
        # 切换到backend目录并启动服务
        backend_dir = Path(__file__).parent / "backend"
        os.chdir(backend_dir)

        cmd = [
            sys.executable, "-m", "uvicorn", "main:app",
            "--host", host,
            "--port", str(port)
        ]

        # 只在开发模式下启用热重载
        if not production_mode:
            cmd.append("--reload")

        subprocess.run(cmd)

    except KeyboardInterrupt:
        print("\n\n服务已停止")
    except Exception as e:
        print(f"\n[ERROR] 启动失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
