import os
import re
import shutil
import uuid
import asyncio
import subprocess
import platform
import yt_dlp
import logging
import math
import psutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

def _resolve_executable(name: str) -> str:
    """解析 ffmpeg/ffprobe 的完整可执行路径。

    搜索顺序:
    1. 环境变量 FFMPEG_PATH / FFPROBE_PATH
    2. shutil.which (系统 PATH)
    3. 可选 static-ffmpeg 自带二进制
    找不到则抛出 RuntimeError。
    """
    env_key = "FFMPEG_PATH" if name == "ffmpeg" else "FFPROBE_PATH"
    env_path = os.getenv(env_key)
    if env_path and os.path.isfile(env_path):
        return env_path

    found = shutil.which(name)
    if found:
        return found

    # 可选 fallback：如果用户额外安装了 static-ffmpeg，则使用其二进制
    try:
        import static_ffmpeg.run
        ffmpeg_exe, ffprobe_exe = static_ffmpeg.run.get_or_fetch_platform_executables_else_raise()
        if name == "ffmpeg":
            return ffmpeg_exe
        return ffprobe_exe
    except Exception:
        pass

    raise RuntimeError(
        f"未找到 {name}。"
        f"请安装 FFmpeg 并加入系统 PATH，或设置环境变量 {env_key} 指向 {name} 可执行文件。"
    )

# 分段转录：每段时长（秒），默认20分钟
SEGMENT_DURATION_SEC = int(os.getenv("SEGMENT_DURATION_SEC", "1200"))

def _get_adaptive_workers() -> int:
    """根据当前 CPU 负载动态计算并发 worker 数。

    | CPU 利用率 | worker 数           |
    |-----------|--------------------|
    | >= 70%    | 1（最小化额外负载）   |
    | >= 50%    | min(2, 物理核心数)   |
    | >= 30%    | min(3, 物理核心数)   |
    | < 30%     | min(4, 物理核心数)   |
    """
    cpu_cores = psutil.cpu_count(logical=False) or 4
    cpu_usage = psutil.cpu_percent(interval=0.5)
    logger.info(f"CPU 利用率: {cpu_usage:.1f}%, 物理核心: {cpu_cores}")

    if cpu_usage >= 70:
        return 1
    elif cpu_usage >= 50:
        return min(2, cpu_cores)
    elif cpu_usage >= 30:
        return min(3, cpu_cores)
    return min(4, cpu_cores)

class VideoProcessor:
    """视频处理器，使用yt-dlp下载和转换视频"""

    def __init__(self):
        self.ffmpeg_path = _resolve_executable("ffmpeg")
        self.ffprobe_path = _resolve_executable("ffprobe")
        logger.info(f"ffmpeg: {self.ffmpeg_path}")
        logger.info(f"ffprobe: {self.ffprobe_path}")
        self.ydl_opts = {
            'format': 'bestaudio/best',  # 优先下载最佳音频源
            'outtmpl': '%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                # 直接在提取阶段转换为单声道 16k（空间小且稳定）
                'preferredcodec': 'm4a',
                'preferredquality': '192'
            }],
            # 全局FFmpeg参数：单声道 + 16k 采样率 + faststart
            'postprocessor_args': ['-ac', '1', '-ar', '16000', '-movflags', '+faststart'],
            'prefer_ffmpeg': True,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,  # 强制只下载单个视频，不下载播放列表
        }

    async def normalize_local_media_to_m4a(self, input_path: Path, output_dir: Path) -> str:
        """
        将本地上传的音视频转为单声道 16kHz AAC m4a，供 Faster-Whisper 使用（与 yt-dlp 后处理参数对齐）。
        若输入文件无音频轨道，抛出明确异常。
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        unique_id = str(uuid.uuid4())[:8]
        out_path = output_dir / f"upload_norm_{unique_id}.m4a"

        if not input_path.exists():
            raise Exception(f"输入文件不存在: {input_path}")
        file_size_mb = input_path.stat().st_size / (1024 * 1024)
        logger.info(f"开始转换: {input_path.name} ({file_size_mb:.1f} MB) -> {out_path.name}")

        # 先探测是否有音频流
        ffprobe = self.ffprobe_path
        def _probe_audio():
            probe_cmd = [
                ffprobe, "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index,codec_name",
                "-of", "csv=p=0",
                str(input_path.resolve()),
            ]
            r = subprocess.run(probe_cmd, capture_output=True, text=True)
            return r.stdout.strip(), r.returncode

        audio_info, probe_rc = await asyncio.to_thread(_probe_audio)
        if not audio_info:
            raise Exception(
                "该视频文件没有音频轨道（静音视频/纯画面录制），无法进行语音转录。"
                "请上传带有音频的视频文件。"
            )
        logger.info(f"检测到音频流: {audio_info}")

        ffmpeg = self.ffmpeg_path
        cmd = [
            ffmpeg, "-y", "-nostdin",
            "-i", str(input_path.resolve()),
            "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(out_path.resolve()),
        ]

        def _run():
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raw_err = (r.stderr or r.stdout or "").strip()
                lines = raw_err.splitlines()
                err_lines = [l for l in lines if l
                             and not l.startswith("ffmpeg version")
                             and not l.startswith("built with")
                             and not l.startswith("configuration:")
                             and not l.startswith("Copyright")
                             and not l.startswith("  lib")]
                err = "\n".join(err_lines[-15:]).strip() or raw_err[:500]
                raise Exception(f"FFmpeg 转换失败 (code {r.returncode}):\n{err}")
            if not out_path.exists():
                raise Exception("FFmpeg 未生成输出文件")

        await asyncio.to_thread(_run)
        logger.info(f"转换完成: {out_path.name}")
        return str(out_path)

    async def split_audio_into_segments(self, audio_path: str, output_dir: Path, segment_duration: int = None) -> list:
        """
        将音频按时长拆分。用 stream copy（不重新编码），速度极快。

        Returns:
            [(segment_path, start_sec, end_sec), ...]
        """
        if segment_duration is None:
            segment_duration = SEGMENT_DURATION_SEC
        output_dir.mkdir(parents=True, exist_ok=True)
        ffprobe = self.ffprobe_path
        ffmpeg = self.ffmpeg_path

        def _get_duration():
            cmd = [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            return float(r.stdout.strip()) if r.stdout.strip() else 0

        total_duration = await asyncio.to_thread(_get_duration)
        logger.info(f"音频总时长: {total_duration:.1f}s ({total_duration/60:.1f}min)")

        if total_duration <= segment_duration * 1.1:
            logger.info("音频时长未超过分段阈值，不拆分")
            return [(audio_path, 0.0, total_duration)]

        num_segments = math.ceil(total_duration / segment_duration)

        workers = _get_adaptive_workers()
        logger.info(
            f"将音频拆分为 {num_segments} 段（stream copy 模式，"
            f"并发 worker={workers}）"
        )

        unique_id = str(uuid.uuid4())[:8]
        ext = Path(audio_path).suffix or ".m4a"
        # 预计算所有段的参数
        all_segment_params = []
        for i in range(num_segments):
            start_sec = i * segment_duration
            duration = min(segment_duration, total_duration - start_sec)
            seg_path = output_dir / f"seg_{unique_id}_{i:03d}{ext}"
            cmd = [
                ffmpeg, "-y", "-nostdin",
                "-ss", str(start_sec),
                "-i", str(audio_path),
                "-t", str(duration),
                "-c", "copy",
                "-movflags", "+faststart",
                str(seg_path),
            ]
            all_segment_params.append((cmd, str(seg_path), start_sec, start_sec + duration, i))

        def _run_seg(c):
            r = subprocess.run(c, capture_output=True, text=True)
            if r.returncode != 0:
                raise Exception(f"FFmpeg 分段失败: {r.stderr[:500]}")

        # 分批并行执行：每批 worker 个段同时处理
        segments = []
        for batch_start in range(0, num_segments, workers):
            batch = all_segment_params[batch_start : batch_start + workers]
            await asyncio.gather(*[
                asyncio.to_thread(_run_seg, param[0])
                for param in batch
            ])
            for param in batch:
                _, seg_path_str, start_sec, end_sec, idx = param
                segments.append((seg_path_str, start_sec, end_sec))
                logger.info(
                    f"  段 {idx+1}/{num_segments}: "
                    f"{start_sec:.0f}s - {end_sec:.0f}s"
                )

        return segments

    async def extract_keyframes(self, video_path: str, output_dir: Path, max_frames: int = 30) -> list:
        """
        从视频中提取关键帧，用于多模态视觉分析。

        Args:
            video_path: 视频文件路径
            output_dir: 输出目录
            max_frames: 最大帧数

        Returns:
            [(frame_path, timestamp_sec), ...] 关键帧列表
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        unique_id = str(uuid.uuid4())[:8]
        ffprobe = self.ffprobe_path
        ffmpeg = self.ffmpeg_path

        # 获取视频时长
        def _get_duration():
            cmd = [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            return float(r.stdout.strip()) if r.stdout.strip() else 0

        duration = await asyncio.to_thread(_get_duration)
        if duration <= 0:
            raise Exception("无法获取视频时长")

        # 计算抽帧间隔，确保不超过 max_frames
        interval = max(1, duration / max_frames)
        logger.info(f"视频 {duration:.0f}s，每 {interval:.0f}s 抽一帧，最多 {max_frames} 帧")

        frames = []
        frame_dir = output_dir / f"frames_{unique_id}"
        frame_dir.mkdir(exist_ok=True)

        cmd = [
            ffmpeg, "-y", "-nostdin",
            "-i", str(video_path),
            "-vf", f"fps=1/{interval},scale=1280:-1",
            "-q:v", "3",
            str(frame_dir / "frame_%04d.jpg"),
        ]

        def _extract():
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                err = (r.stderr or "").strip()
                # 去掉版本banner
                lines = [l for l in err.splitlines() if l and not l.startswith("ffmpeg version") and not l.startswith("built with") and not l.startswith("configuration:")]
                raise Exception(f"FFmpeg 抽帧失败:\n{chr(10).join(lines[-10:])}")

        await asyncio.to_thread(_extract)

        for f in sorted(frame_dir.glob("frame_*.jpg")):
            idx = int(f.stem.split("_")[1]) - 1
            ts = idx * interval
            frames.append((str(f), ts))

        logger.info(f"提取了 {len(frames)} 帧")
        return frames
    async def has_audio_stream(self, file_path: str) -> bool:
        """检测文件是否有音频流。"""
        ffprobe = self.ffprobe_path

        def _probe():
            cmd = [
                ffprobe, "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index",
                "-of", "csv=p=0",
                str(file_path),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            return bool(r.stdout.strip())
        return await asyncio.to_thread(_probe)

    async def fetch_subtitles(self, url: str, output_dir: Path) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        先尝试从平台获取字幕文本，比下载音频快得多。

        Returns:
            (subtitle_markdown, video_title, language_code)
            subtitle_markdown 为 None 表示无可用字幕。
        """
        import asyncio

        output_dir.mkdir(exist_ok=True)
        unique_id = str(uuid.uuid4())[:8]
        sub_dir = output_dir / f"subs_{unique_id}"

        try:
            # 1. 快速探测：获取视频信息和字幕可用性，不下载任何内容
            check_opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
            with yt_dlp.YoutubeDL(check_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, url, False)

            video_title = info.get("title", "unknown")
            manual_subs: dict = info.get("subtitles") or {}
            auto_caps: dict = info.get("automatic_captions") or {}

            # 过滤掉 live_chat 等非语音轨道
            manual_langs = [k for k in manual_subs if not k.startswith("live_chat")]
            auto_langs = [k for k in auto_caps if not k.startswith("live_chat")]

            if not manual_langs and not auto_langs:
                logger.info(f"视频无可用字幕: {url}")
                return None, video_title, None

            # 优先手动字幕，其次自动字幕
            prefer_manual = bool(manual_langs)
            candidate_langs = manual_langs if prefer_manual else auto_langs

            # 按优先级选语言：英语 > 简体中文 > 繁体中文 > 其他（取第一个）
            _priority = ["en", "en-orig", "zh-Hans", "zh-Hant", "zh", "ja", "ko", "fr", "de", "es"]
            prefer_lang = next(
                (lang for lang in _priority if lang in candidate_langs),
                candidate_langs[0],
            )
            logger.info(
                f"发现{'手动' if prefer_manual else '自动'}字幕，选用语言: {prefer_lang}"
                f"（候选 {len(candidate_langs)} 种）"
            )

            # 2. 仅下载字幕，跳过音视频
            sub_dir.mkdir(exist_ok=True)
            dl_opts = {
                "writesubtitles": prefer_manual,
                "writeautomaticsub": not prefer_manual,
                "subtitlesformat": "vtt/srt/best",
                "subtitleslangs": [prefer_lang],
                "skip_download": True,
                "outtmpl": str(sub_dir / "sub.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
            }
            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                await asyncio.to_thread(ydl.download, [url])

            # 3. 查找下载的字幕文件
            sub_files = list(sub_dir.glob("*.vtt")) + list(sub_dir.glob("*.srt"))
            if not sub_files:
                logger.warning("字幕下载后未找到文件，回退音频模式")
                return None, video_title, None

            sub_file = sub_files[0]

            # 从文件名提取语言代码 (e.g. sub.en.vtt → en)
            stem_parts = sub_file.stem.split(".")
            file_lang = stem_parts[-1] if len(stem_parts) > 1 else prefer_lang

            # 4. 解析字幕文件
            if sub_file.suffix == ".vtt":
                entries = self._parse_vtt(str(sub_file))
            else:
                entries = self._parse_srt(str(sub_file))

            if not entries:
                logger.warning("字幕解析结果为空，回退音频模式")
                return None, video_title, None

            # 5. 格式化为与 Whisper 输出兼容的 Markdown
            formatted = self._format_subtitle_entries(entries, file_lang)
            logger.info(f"字幕获取成功: lang={file_lang}, {len(entries)} 条目")
            return formatted, video_title, file_lang

        except Exception as e:
            logger.warning(f"字幕获取失败（将回退至音频下载）: {e}")
            return None, None, None
        finally:
            if sub_dir.exists():
                try:
                    shutil.rmtree(str(sub_dir))
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # 字幕解析辅助方法
    # ------------------------------------------------------------------

    def _parse_vtt(self, filepath: str) -> list:
        """解析 WebVTT 字幕文件，返回去重后的条目列表。

        特别处理 YouTube 自动字幕的「滚动追加」格式：
        同一句话会被分成多个 cue 逐字追加，只保留每组的「最终版本」。
        """
        raw_entries = []
        seen_texts: set = set()

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.error(f"读取 VTT 文件失败: {e}")
            return []

        # 移除 WEBVTT 文件头，按空行分割 cue 块
        content = re.sub(r"^WEBVTT[^\n]*\n", "", content)
        blocks = re.split(r"\n{2,}", content.strip())

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            lines = block.split("\n")
            timing_idx = next((i for i, l in enumerate(lines) if "-->" in l), -1)
            if timing_idx < 0:
                continue

            timing_line = lines[timing_idx]
            text_lines = lines[timing_idx + 1:]

            match = re.match(
                r"(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?)\s*-->\s*"
                r"(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?)",
                timing_line,
            )
            if not match:
                continue

            start_str = self._normalize_time(match.group(1))
            end_str = self._normalize_time(match.group(2))

            raw_text = " ".join(text_lines)
            # 去除 HTML / VTT 内联标签（包括 YouTube 逐字时间码标签）
            text = re.sub(r"<[^>]+>", "", raw_text)
            text = (
                text.replace("&amp;", "&")
                    .replace("&lt;", "<")
                    .replace("&gt;", ">")
                    .replace("&nbsp;", " ")
                    .replace("&#39;", "'")
                    .replace("&quot;", '"')
                    .strip()
            )
            # 合并行内多余空白
            text = re.sub(r"\s+", " ", text).strip()

            if not text or text in seen_texts:
                continue

            seen_texts.add(text)
            raw_entries.append({"start": start_str, "end": end_str, "text": text})

        # ── 二次去重：过滤 YouTube「滚动追加」的中间状态 ──────────────────
        # 若条目 i 的文本是条目 i+1 文本的起始子串，则条目 i 是中间状态，丢弃。
        # 同时丢弃纯空白/单字符的噪音条目。
        if not raw_entries:
            return []

        entries = []
        for i, entry in enumerate(raw_entries):
            text = entry["text"]
            if len(text) < 2:
                continue
            # 检查后续若干条是否以当前文本开头（滚动追加的特征）
            is_intermediate = False
            for j in range(i + 1, min(i + 4, len(raw_entries))):
                next_text = raw_entries[j]["text"]
                if next_text.startswith(text) and len(next_text) > len(text):
                    is_intermediate = True
                    break
            if not is_intermediate:
                entries.append(entry)

        return entries

    def _parse_srt(self, filepath: str) -> list:
        """解析 SRT 字幕文件，返回去重后的条目列表。"""
        entries = []
        seen_texts: set = set()

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.error(f"读取 SRT 文件失败: {e}")
            return []

        blocks = re.split(r"\n{2,}", content.strip())

        for block in blocks:
            lines = block.strip().split("\n")
            timing_idx = next((i for i, l in enumerate(lines) if "-->" in l), -1)
            if timing_idx < 0:
                continue

            timing_line = lines[timing_idx]
            text_lines = lines[timing_idx + 1:]

            match = re.match(
                r"(\d{1,2}:\d{2}:\d{2}[.,]\d+)\s*-->\s*(\d{1,2}:\d{2}:\d{2}[.,]\d+)",
                timing_line,
            )
            if not match:
                continue

            start_str = self._normalize_time(match.group(1))
            end_str = self._normalize_time(match.group(2))

            text = " ".join(text_lines)
            text = re.sub(r"<[^>]+>", "", text).strip()

            if not text or text in seen_texts:
                continue

            seen_texts.add(text)
            entries.append({"start": start_str, "end": end_str, "text": text})

        return entries

    def _normalize_time(self, time_str: str) -> str:
        """将 HH:MM:SS.mmm 或 MM:SS.mmm 统一转为 MM:SS 格式。"""
        time_str = re.sub(r"[.,]\d+$", "", time_str)
        parts = time_str.split(":")
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{h * 60 + m:02d}:{s:02d}"
        elif len(parts) == 2:
            m, s = int(parts[0]), int(parts[1])
            return f"{m:02d}:{s:02d}"
        return time_str

    def _format_subtitle_entries(self, entries: list, language: str) -> str:
        """将字幕条目格式化为与 Whisper 输出兼容的 Markdown，供下游管道直接使用。"""
        lines = [
            "# Video Transcription",
            "",
            f"**Detected Language:** {language}",
            "**Language Probability:** 1.00",
            "",
            "## Transcription Content",
            "",
        ]
        for entry in entries:
            lines.append(f"**[{entry['start']} - {entry['end']}]**")
            lines.append("")
            lines.append(entry["text"])
            lines.append("")
        return "\n".join(lines)

    async def download_and_convert(
        self,
        url: str,
        output_dir: Path,
        prefetched_title: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        下载视频并转换为m4a格式。

        prefetched_title: 若调用方已通过 fetch_subtitles 探测过视频信息，
        可直接传入视频标题，跳过重复的 extract_info 网络请求。
        """
        try:
            # 创建输出目录
            output_dir.mkdir(exist_ok=True)

            # 生成唯一的文件名
            unique_id = str(uuid.uuid4())[:8]
            output_template = str(output_dir / f"audio_{unique_id}.%(ext)s")

            # 更新yt-dlp选项
            ydl_opts = self.ydl_opts.copy()
            ydl_opts['outtmpl'] = output_template

            logger.info(f"开始下载视频: {url}")

            import asyncio
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if prefetched_title:
                    # 标题和时长已在 fetch_subtitles 中获取，直接下载，跳过重复探测
                    video_title = prefetched_title
                    expected_duration = 0
                    logger.info(f"复用预取标题，跳过 extract_info: {video_title}")
                else:
                    # 获取视频信息（放到线程池避免阻塞事件循环）
                    info = await asyncio.to_thread(ydl.extract_info, url, False)
                    video_title = info.get('title', 'unknown')
                    expected_duration = info.get('duration') or 0
                    logger.info(f"视频标题: {video_title}")

                # 下载视频（放到线程池避免阻塞事件循环）
                await asyncio.to_thread(ydl.download, [url])

            # 查找生成的m4a文件
            audio_file = str(output_dir / f"audio_{unique_id}.m4a")

            if not os.path.exists(audio_file):
                # 如果m4a文件不存在，查找其他音频格式
                for ext in ['webm', 'mp4', 'mp3', 'wav']:
                    potential_file = str(output_dir / f"audio_{unique_id}.{ext}")
                    if os.path.exists(potential_file):
                        audio_file = potential_file
                        break
                else:
                    raise Exception("未找到下载的音频文件")

            # 校验时长，如果和源视频差异较大，尝试一次ffmpeg规范化重封装
            ffprobe = self.ffprobe_path
            ffmpeg = self.ffmpeg_path
            try:
                probe_cmd = [ffprobe, "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", audio_file]
                out = subprocess.check_output(probe_cmd).decode().strip()
                actual_duration = float(out) if out else 0.0
            except Exception as _:
                actual_duration = 0.0

            if expected_duration and actual_duration and abs(actual_duration - expected_duration) / expected_duration > 0.1:
                logger.warning(
                    f"音频时长异常，期望{expected_duration}s，实际{actual_duration}s，尝试重封装修复…"
                )
                try:
                    fixed_path = str(output_dir / f"audio_{unique_id}_fixed.m4a")
                    fix_cmd = [ffmpeg, "-y", "-i", audio_file, "-vn", "-c:a", "aac",
                               "-b:a", "160k", "-movflags", "+faststart", fixed_path]
                    subprocess.check_call(fix_cmd)
                    # 用修复后的文件替换
                    audio_file = fixed_path
                    # 重新探测
                    probe_cmd2 = [ffprobe, "-v", "error", "-show_entries", "format=duration",
                                  "-of", "default=noprint_wrappers=1:nokey=1", audio_file]
                    out2 = subprocess.check_output(probe_cmd2).decode().strip()
                    actual_duration2 = float(out2) if out2 else 0.0
                    logger.info(f"重封装完成，新时长≈{actual_duration2:.2f}s")
                except Exception as e:
                    logger.error(f"重封装失败：{e}")

            logger.info(f"音频文件已保存: {audio_file}")
            return audio_file, video_title

        except Exception as e:
            logger.error(f"下载视频失败: {str(e)}")
            raise Exception(f"下载视频失败: {str(e)}")

    def get_video_info(self, url: str) -> dict:
        """
        获取视频信息

        Args:
            url: 视频链接

        Returns:
            视频信息字典
        """
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    'title': info.get('title', ''),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', ''),
                    'upload_date': info.get('upload_date', ''),
                    'description': info.get('description', ''),
                    'view_count': info.get('view_count', 0),
                }
        except Exception as e:
            logger.error(f"获取视频信息失败: {str(e)}")
            raise Exception(f"获取视频信息失败: {str(e)}")

    async def extract_keyframes_to_dir(
        self,
        video_path: str,
        output_dir: Path,
        interval: int = 30,
        max_frames: int = 60,
        scale: int = 1280,
        quality: int = 3,
    ) -> list:
        """
        从视频提取关键帧到指定目录。
        Returns: [(frame_path, timestamp_sec), ...]
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        ffprobe = self.ffprobe_path
        ffmpeg = self.ffmpeg_path

        def _get_duration():
            cmd = [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            return float(r.stdout.strip()) if r.stdout.strip() else 0

        duration = await asyncio.to_thread(_get_duration)
        if duration <= 0:
            raise Exception("无法获取视频时长")

        actual_interval = max(interval, duration / max_frames)
        logger.info(f"视频 {duration:.0f}s，每 {actual_interval:.0f}s 提取一帧")

        cmd = [
            ffmpeg, "-y", "-nostdin",
            "-i", str(video_path),
            "-vf", f"fps=1/{actual_interval},scale={scale}:-1",
            "-q:v", str(quality),
            "-threads", "0",
            str(output_dir / "frame_%04d.jpg"),
        ]

        def _extract():
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                err = (r.stderr or "").strip()
                lines = [l for l in err.splitlines() if l and not l.startswith("ffmpeg version")]
                raise Exception(f"FFmpeg 抽帧失败:\n{chr(10).join(lines[-10:])}")

        await asyncio.to_thread(_extract)

        frames = []
        for f in sorted(output_dir.glob("frame_*.jpg")):
            idx = int(f.stem.split("_")[1]) - 1
            ts = idx * actual_interval
            frames.append((str(f), ts))

        logger.info(f"提取了 {len(frames)} 帧到 {output_dir}")
        return frames

    async def extract_audio_for_whisper(self, video_path: str, output_dir: Path) -> str:
        """
        从视频提取音频用于 Whisper 转录。返回音频文件路径。
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_path = output_dir / "audio.m4a"
        ffmpeg = self.ffmpeg_path

        has_audio = await self.has_audio_stream(video_path)
        if not has_audio:
            raise Exception("视频没有音频轨道")

        cmd = [
            ffmpeg, "-y", "-nostdin",
            "-i", str(video_path),
            "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(audio_path),
        ]

        def _run():
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise Exception(f"音频提取失败: {r.stderr[:500]}")

        await asyncio.to_thread(_run)
        return str(audio_path)
