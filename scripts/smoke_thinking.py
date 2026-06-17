"""
thinking 冒烟测试 - 验证后端 SSE 能正确发出 type=thinking / type=chunk / type=done 事件
不启动自己的 mock，复用已有的 mock_thinking.py（18081）。
运行：python scripts/smoke_thinking.py
"""
import asyncio
import json
import sys

import httpx

BASE = "http://127.0.0.1:8004"
MOCK_BASE = "http://127.0.0.1:18081"


async def create_provider(client, name, base_url, api_key, model="MiniMax-M3"):
    r = await client.post(
        f"{BASE}/api/providers",
        data={"name": name, "base_url": base_url, "api_key": api_key, "model": model},
    )
    r.raise_for_status()
    return r.json()["provider_id"]


async def set_default(client, pid):
    r = await client.post(f"{BASE}/api/providers/{pid}/set-default")
    r.raise_for_status()


async def list_conversations(client):
    r = await client.get(f"{BASE}/api/conversations")
    r.raise_for_status()
    return r.json()["data"]


async def delete_provider(client, pid):
    r = await client.delete(f"{BASE}/api/providers/{pid}")
    r.raise_for_status()


async def send_chat(client, conv_id, message, provider_id):
    events = []
    async with client.stream(
        "POST",
        f"{BASE}/api/conversations/{conv_id}/chat",
        data={"message": message, "provider_id": str(provider_id)},
    ) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                continue
            events.append(json.loads(payload))
    return events


async def main():
    print(f"后端: {BASE}")
    print(f"mock: {MOCK_BASE}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 先确认 mock 活着
        r = await client.post(f"{MOCK_BASE}/v1/chat/completions", json={})
        if r.status_code != 200:
            print(f"❌ mock 没启起来 ({r.status_code})，请先启动 mock_thinking.py")
            return False
        # 取一个对话
        convs = await list_conversations(client)
        if not convs:
            print("❌ 没有任何 conversation")
            return False
        cid = convs[0]["id"]
        print(f"复用 conv={cid}")

        pid = await create_provider(
            client, "thinking-smoke", f"{MOCK_BASE}/v1", "sk-thinking-smoke"
        )
        print(f"创建 provider id={pid}")
        await set_default(client, pid)

        try:
            events = await send_chat(client, cid, "简单总结一下", pid)
        finally:
            await delete_provider(client, pid)
            print(f"清理 provider {pid}")

    types = [e.get("type") for e in events]
    thinking = [e for e in events if e.get("type") == "thinking"]
    chunks = [e for e in events if e.get("type") == "chunk"]
    dones = [e for e in events if e.get("type") == "done"]
    errors = [e for e in events if e.get("type") == "error"]

    print(f"\n事件序列: {types}")
    print(f"thinking 拼接: {''.join(e['content'] for e in thinking)!r}")
    print(f"content  拼接: {''.join(e['content'] for e in chunks)!r}")

    thinking_text = "".join(e["content"] for e in thinking)
    chunk_text = "".join(e["content"] for e in chunks)
    ok = (
        len(thinking) > 0
        and len(chunks) > 0
        and len(dones) == 1
        and len(errors) == 0
        and len(thinking_text) > 0
        and len(chunk_text) > 0
    )
    print(f"\n断言: thinking>0, chunk>0, done==1, error==0, 文本非空 -> {'✅' if ok else '❌'}")
    return ok


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
