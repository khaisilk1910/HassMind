import json
from pathlib import Path
from openai import AsyncOpenAI

from .db import add_message, get_messages, add_tool_audit
from .settings import settings
from .tools import ToolRuntime, schemas


class Agent:
    def __init__(self, runtime: ToolRuntime):
        key = settings.read_openai_key()
        if not key:
            raise RuntimeError("OpenAI-compatible API key is empty")
        self.runtime = runtime
        self.client = AsyncOpenAI(api_key=key, base_url=settings.openai_base_url)
        path = Path("/app/config/system_prompt.txt")
        self.system_prompt = path.read_text(encoding="utf-8") if path.exists() else "You are HassMind, a Home Assistant agent."

    async def chat(self, session_id: str, user_text: str, source: str = "web") -> str:
        add_message(session_id, "user", user_text, source)
        history = get_messages(session_id, 36)
        messages = [{"role": "system", "content": self.system_prompt}] + history

        for _ in range(settings.max_tool_rounds):
            resp = await self.client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                tools=schemas(),
                tool_choice="auto",
            )
            msg = resp.choices[0].message
            assistant_msg = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                assistant_msg["tool_calls"] = [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]
            messages.append(assistant_msg)

            if not msg.tool_calls:
                text = msg.content or ""
                add_message(session_id, "assistant", text, source)
                return text

            for tc in msg.tool_calls:
                args = {}
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    result = await self.runtime.call(tc.function.name, args)
                    add_tool_audit(tc.function.name, args, result=result)
                    content = json.dumps(result, ensure_ascii=False, default=str)
                except Exception as e:
                    add_tool_audit(tc.function.name, args, error=f"{type(e).__name__}: {e}")
                    content = json.dumps({"error": type(e).__name__, "message": str(e)}, ensure_ascii=False)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})

        text = "Đã đạt giới hạn số vòng gọi công cụ; HassMind dừng để tránh vòng lặp ngoài ý muốn."
        add_message(session_id, "assistant", text, source)
        return text
