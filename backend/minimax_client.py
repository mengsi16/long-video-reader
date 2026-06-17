import base64
import logging
from pathlib import Path
from typing import AsyncGenerator, Optional
import sys
sys.path.insert(0, str(Path(__file__).parent))
import openai
from config import MINIMAX_API_KEY, MINIMAX_BASE_URL, MINIMAX_MODEL

logger = logging.getLogger(__name__)

THINK_START_TAG = "<think>"
THINK_END_TAG = "</think>"


class ThinkContentSplitter:
    def __init__(self):
        self.pending = ""
        self.in_thinking = False

    def feed(self, text: str) -> list[tuple[str, str]]:
        self.pending += text
        return self._drain(end_of_stream=False)

    def finish(self) -> list[tuple[str, str]]:
        return self._drain(end_of_stream=True)

    def _drain(self, end_of_stream: bool) -> list[tuple[str, str]]:
        events = []
        while self.pending:
            if self.in_thinking:
                end_idx = self.pending.find(THINK_END_TAG)
                if end_idx == -1:
                    keep = 0 if end_of_stream else len(THINK_END_TAG) - 1
                    emit_len = max(0, len(self.pending) - keep)
                    if emit_len:
                        events.append(("thinking", self.pending[:emit_len]))
                        self.pending = self.pending[emit_len:]
                    break
                if end_idx:
                    events.append(("thinking", self.pending[:end_idx]))
                self.pending = self.pending[end_idx + len(THINK_END_TAG):]
                self.in_thinking = False
            else:
                start_idx = self.pending.find(THINK_START_TAG)
                if start_idx == -1:
                    keep = 0 if end_of_stream else len(THINK_START_TAG) - 1
                    emit_len = max(0, len(self.pending) - keep)
                    if emit_len:
                        events.append(("content", self.pending[:emit_len]))
                        self.pending = self.pending[emit_len:]
                    break
                if start_idx:
                    events.append(("content", self.pending[:start_idx]))
                self.pending = self.pending[start_idx + len(THINK_START_TAG):]
                self.in_thinking = True
        return events


def strip_thinking_tags(text: str) -> str:
    splitter = ThinkContentSplitter()
    content_parts = []
    for kind, part in splitter.feed(text):
        if kind == "content":
            content_parts.append(part)
    for kind, part in splitter.finish():
        if kind == "content":
            content_parts.append(part)
    return "".join(content_parts).strip()


def get_client(api_key: str = None, base_url: str = None) -> openai.AsyncOpenAI:
    key = api_key or MINIMAX_API_KEY
    if not key:
        raise ValueError("API key is empty. Please configure a provider in settings.")
    return openai.AsyncOpenAI(
        api_key=key,
        base_url=base_url or MINIMAX_BASE_URL,
    )

def build_frame_image_content(frame_path: str, detail: str = "default") -> dict:
    path = Path(frame_path)
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    ext = path.suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}
    media_type = mime.get(ext, "image/jpeg")
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{media_type};base64,{data}",
            "detail": detail,
        },
    }

def build_chat_messages(
    user_message: str,
    frames: list,
    transcript_text: str,
    history: list,
    selected_frame_ids: list = None,
) -> list:
    messages = []
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    content = []
    if transcript_text:
        content.append({
            "type": "text",
            "text": f"以下是视频的音频转录文本：\n\n{transcript_text[:8000]}",
        })

    frames_to_use = frames
    if selected_frame_ids:
        frames_to_use = [f for f in frames if f["id"] in selected_frame_ids]

    for frame in frames_to_use[:20]:
        content.append(build_frame_image_content(frame["file_path"]))

    content.append({"type": "text", "text": user_message})
    messages.append({"role": "user", "content": content})
    return messages

def build_index_messages(prompt: str, frames: list = None) -> list:
    content = [{"type": "text", "text": prompt}]
    for frame in frames or []:
        content.append(build_frame_image_content(frame["file_path"]))
    return [{"role": "user", "content": content}]

def build_chat_messages_with_context(
    user_message: str,
    context_pack: str,
    history: list,
) -> list:
    messages = []
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({
        "role": "user",
        "content": (
            "以下是视频阅读工具根据用户问题自动选出的上下文包。"
            "请优先依据这些章节摘要、关键帧注释和转录片段回答，并引用章节和时间范围。\n\n"
            f"{context_pack}\n\n"
            f"用户问题：{user_message}"
        ),
    })
    return messages

async def chat_once(
    messages: list,
    system_prompt: str = None,
    api_key: str = None,
    base_url: str = None,
    model: str = None,
    max_tokens: int = 2048,
    temperature: float = 0.2,
) -> str:
    client = get_client(api_key, base_url)
    all_messages = []
    if system_prompt:
        all_messages.append({"role": "system", "content": system_prompt})
    all_messages.extend(messages)
    response = await client.chat.completions.create(
        model=model or MINIMAX_MODEL,
        messages=all_messages,
        stream=False,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return strip_thinking_tags(response.choices[0].message.content or "")

async def chat_stream(
    messages: list,
    system_prompt: str = None,
    api_key: str = None,
    base_url: str = None,
    model: str = None,
) -> AsyncGenerator[tuple, None]:
    client = get_client(api_key, base_url)
    all_messages = []
    if system_prompt:
        all_messages.append({"role": "system", "content": system_prompt})
    all_messages.extend(messages)

    stream = await client.chat.completions.create(
        model=model or MINIMAX_MODEL,
        messages=all_messages,
        stream=True,
        temperature=0.7,
        max_tokens=4096,
    )
    splitter = ThinkContentSplitter()
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        # 思考内容（MiniMax / DeepSeek-R1 / o1 类模型）
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            yield ("thinking", reasoning)
        # 正文
        if delta.content:
            for kind, text in splitter.feed(delta.content):
                if text:
                    yield (kind, text)
    for kind, text in splitter.finish():
        if text:
            yield (kind, text)
