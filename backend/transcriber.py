import os
import time
import logging
from pathlib import Path
from typing import Optional

# 设置 HuggingFace 镜像（国内加速）— 必须在 faster_whisper 导入之前
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# hf-mirror.com 直链下载（绕过 huggingface_hub 的 HEAD 验证问题）
_HF_MIRROR = "https://hf-mirror.com"
_MODEL_FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]
_DOWNLOAD_RETRIES = 3


def _download_file(url: str, dest: Path):
    """下载单个文件到 dest，带重试和指数退避。"""
    import requests

    for attempt in range(1, _DOWNLOAD_RETRIES + 1):
        try:
            logger.info(f"下载 {dest.name} (尝试 {attempt}/{_DOWNLOAD_RETRIES}): {url}")
            resp = requests.get(url, stream=True, timeout=600)
            resp.raise_for_status()

            tmp = dest.with_suffix(dest.suffix + ".tmp")
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
            tmp.replace(dest)

            size = dest.stat().st_size
            if size == 0:
                raise RuntimeError(f"下载完成但文件为空: {dest.name}")
            logger.info(f"  {dest.name} 完成 ({size:,} bytes)")
            return
        except Exception as e:
            # 清理可能残留的临时文件
            tmp_path = dest.with_suffix(dest.suffix + ".tmp")
            if tmp_path.exists():
                tmp_path.unlink()
            if attempt == _DOWNLOAD_RETRIES:
                raise
            wait = 2 ** attempt
            logger.warning(f"  {dest.name} 下载失败 (尝试 {attempt}): {e}，{wait}s 后重试")
            time.sleep(wait)


def _ensure_model_local(model_size: str) -> str:
    """确保 Whisper 模型文件已下载到本地目录。

    优先使用本地缓存；缺失时从 hf-mirror.com 直接下载（requests GET）。
    返回本地目录路径，可直接传给 WhisperModel(model_path)。
    """
    repo = f"Systran/faster-whisper-{model_size}"
    local_dir = Path.home() / ".cache" / f"faster-whisper-{model_size}"
    local_dir.mkdir(parents=True, exist_ok=True)

    for filename in _MODEL_FILES:
        dest = local_dir / filename
        if dest.exists() and dest.stat().st_size > 0:
            continue
        url = f"{_HF_MIRROR}/{repo}/resolve/main/{filename}"
        _download_file(url, dest)

    return str(local_dir)


class Transcriber:
    """音频转录器，使用Faster-Whisper进行语音转文字"""

    def __init__(self, model_size: str = "base"):
        """
        初始化转录器

        Args:
            model_size: Whisper模型大小 (tiny, base, small, medium, large)
        """
        self.model_size = model_size
        self.model = None
        self.last_detected_language = None

    def _load_model(self):
        """延迟加载模型，文件损坏时自动重新下载"""
        if self.model is None:
            import config
            import shutil
            device = getattr(config, 'WHISPER_DEVICE', 'cpu')
            compute_type = getattr(config, 'WHISPER_COMPUTE_TYPE', 'int8')

            model_path = _ensure_model_local(self.model_size)
            logger.info(f"模型本地路径: {model_path}")

            logger.info(f"正在加载Whisper模型: {self.model_size} (device={device}, compute_type={compute_type})")
            try:
                self.model = WhisperModel(
                    model_path,
                    device=device,
                    compute_type=compute_type,
                )
            except RuntimeError as e:
                if "incomplete" in str(e).lower() or "corrupt" in str(e).lower():
                    logger.warning(f"模型文件损坏: {e}，清除后重新下载")
                    shutil.rmtree(model_path)
                    model_path = _ensure_model_local(self.model_size)
                    self.model = WhisperModel(
                        model_path,
                        device=device,
                        compute_type=compute_type,
                    )
                else:
                    raise
            logger.info("模型加载完成")

    async def transcribe_segments(
        self,
        segments: list,
        language: Optional[str] = None,
        progress_callback=None,
    ) -> str:
        """
        分段转录音频，合并结果为一份完整转录。

        Args:
            segments: [(audio_path, start_sec, end_sec), ...] 由 VideoProcessor.split_audio_into_segments 返回
            language: 指定语言（可选）
            progress_callback: async fn(current_segment, total_segments) 进度回调

        Returns:
            合并后的转录文本（Markdown格式，时间戳已偏移到全局时间）
        """
        self._load_model()
        import asyncio

        total = len(segments)
        all_transcript_lines = []
        detected_language = None
        detected_probability = 0.0

        all_transcript_lines.append("# Video Transcription")
        all_transcript_lines.append("")
        all_transcript_lines.append("## Transcription Content")
        all_transcript_lines.append("")

        for idx, (seg_path, start_sec, end_sec) in enumerate(segments):
            logger.info(f"转录第 {idx+1}/{total} 段: {start_sec:.0f}s - {end_sec:.0f}s")

            if progress_callback:
                await progress_callback(idx + 1, total)

            def _do_transcribe_segment():
                return self.model.transcribe(
                    seg_path,
                    language=language,
                    beam_size=5,
                    best_of=5,
                    temperature=[0.0, 0.2, 0.4],
                    vad_filter=True,
                    vad_parameters={
                        "min_silence_duration_ms": 900,
                        "speech_pad_ms": 300,
                    },
                    no_speech_threshold=0.7,
                    compression_ratio_threshold=2.3,
                    log_prob_threshold=-1.0,
                    condition_on_previous_text=False,
                )

            seg_segments, seg_info = await asyncio.to_thread(_do_transcribe_segment)

            if detected_language is None:
                detected_language = seg_info.language
                detected_probability = seg_info.language_probability

            for seg in seg_segments:
                # 将段内时间戳偏移到全局时间
                global_start = start_sec + seg.start
                global_end = start_sec + seg.end
                ts_start = self._format_time(global_start)
                ts_end = self._format_time(global_end)
                text = seg.text.strip()
                all_transcript_lines.append(f"**[{ts_start} - {ts_end}]**")
                all_transcript_lines.append("")
                all_transcript_lines.append(text)
                all_transcript_lines.append("")

        # 回填语言信息
        if detected_language:
            lang_line = f"**Detected Language:** {detected_language}"
            prob_line = f"**Language Probability:** {detected_probability:.2f}"
            all_transcript_lines.insert(2, lang_line)
            all_transcript_lines.insert(3, prob_line)
            all_transcript_lines.insert(4, "")
            self.last_detected_language = detected_language

        result = "\n".join(all_transcript_lines)
        logger.info(f"分段转录完成: {total} 段")
        return result

    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> str:
        """
        转录音频文件

        Args:
            audio_path: 音频文件路径
            language: 指定语言（可选，如果不指定则自动检测）

        Returns:
            转录文本（Markdown格式）
        """
        try:
            # 检查文件是否存在
            if not os.path.exists(audio_path):
                raise Exception(f"音频文件不存在: {audio_path}")

            # 加载模型
            self._load_model()

            logger.info(f"开始转录音频: {audio_path}")

            # 直接调用会阻塞事件循环；放入线程避免阻塞
            import asyncio
            def _do_transcribe():
                return self.model.transcribe(
                    audio_path,
                    language=language,
                    beam_size=5,
                    best_of=5,
                    temperature=[0.0, 0.2, 0.4],  # 使用温度递增策略
                    # 更稳健：开启VAD与阈值，降低静音/噪音导致的重复
                    vad_filter=True,
                    vad_parameters={
                        "min_silence_duration_ms": 900,  # 静音检测时长
                        "speech_pad_ms": 300  # 语音填充
                    },
                    no_speech_threshold=0.7,  # 无语音阈值
                    compression_ratio_threshold=2.3,  # 压缩比阈值，检测重复
                    log_prob_threshold=-1.0,  # 日志概率阈值
                    # 避免错误累积导致的连环重复
                    condition_on_previous_text=False
                )
            segments, info = await asyncio.to_thread(_do_transcribe)

            detected_language = info.language
            self.last_detected_language = detected_language  # 保存检测到的语言
            logger.info(f"检测到的语言: {detected_language}")
            logger.info(f"语言检测概率: {info.language_probability:.2f}")

            # 组装转录结果
            transcript_lines = []
            transcript_lines.append("# Video Transcription")
            transcript_lines.append("")
            transcript_lines.append(f"**Detected Language:** {detected_language}")
            transcript_lines.append(f"**Language Probability:** {info.language_probability:.2f}")
            transcript_lines.append("")
            transcript_lines.append("## Transcription Content")
            transcript_lines.append("")

            # 添加时间戳和文本
            for segment in segments:
                start_time = self._format_time(segment.start)
                end_time = self._format_time(segment.end)
                text = segment.text.strip()

                transcript_lines.append(f"**[{start_time} - {end_time}]**")
                transcript_lines.append("")
                transcript_lines.append(text)
                transcript_lines.append("")

            transcript_text = "\n".join(transcript_lines)
            logger.info("转录完成")

            return transcript_text

        except Exception as e:
            logger.error(f"转录失败: {str(e)}")
            raise Exception(f"转录失败: {str(e)}")

    def _format_time(self, seconds: float) -> str:
        """
        将秒数转换为时分秒格式

        Args:
            seconds: 秒数

        Returns:
            格式化的时间字符串
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = int(seconds % 60)

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"

    def get_supported_languages(self) -> list:
        """
        获取支持的语言列表
        """
        return [
            "zh", "en", "ja", "ko", "es", "fr", "de", "it", "pt", "ru",
            "ar", "hi", "th", "vi", "tr", "pl", "nl", "sv", "da", "no"
        ]

    def get_detected_language(self, transcript_text: Optional[str] = None) -> Optional[str]:
        """
        获取检测到的语言

        Args:
            transcript_text: 转录文本（可选，用于从文本中提取语言信息）

        Returns:
            检测到的语言代码
        """
        # 如果有保存的语言，直接返回
        if self.last_detected_language:
            return self.last_detected_language

        # 如果提供了转录文本，尝试从中提取语言信息
        if transcript_text and "**Detected Language:**" in transcript_text:
            lines = transcript_text.split('\n')
            for line in lines:
                if "**Detected Language:**" in line:
                    lang = line.split(":")[-1].strip()
                    return lang if lang else None

        return None
