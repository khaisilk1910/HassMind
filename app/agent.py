import asyncio
import json
from pathlib import Path
from time import perf_counter

from openai import AsyncOpenAI

from .db import add_message, get_messages, add_tool_audit
from .observability import exception, get_logger, info, log_context, preview, warning
from .settings import settings
from .tools import ToolRuntime, schemas

logger = get_logger("agent")

_ZALO_FORMAT_PROMPT = (
    "Kênh hiện tại là Zalo và chỉ hiển thị plain text. Không dùng Markdown (#, *, backtick, fenced code), "
    "không xuất HTML/XML hoặc thẻ <FollowUp>. Trình bày dễ đọc bằng emoji vừa phải, dòng trống và bullet Unicode •/◦. "
    "Giữ nguyên entity_id Home Assistant khi cần nêu chi tiết kỹ thuật."
)

_READ_ONLY_TOOLS = {
    "ha_list_entities", "ha_search_states", "ha_get_states", "ha_get_state", "ha_history",
    "ha_recent_events", "ha_entity_registry", "ha_get_config", "ha_get_change",
    "memory_search", "knowledge_search", "skill_list", "skill_read", "web_search",
    "mcp_servers", "mcp_list_tools", "integrations_status", "camera_tts_cameras",
    "camera_tts_job", "zalo_accounts", "ha_custom_integrations_status", "evn_accounts",
    "evn_summary", "evn_daily", "evn_monthly", "lunar_convert_date", "shopping_profiles",
    "shopping_list", "yt_dlp_search", "yt_dlp_get_job",
}
_READ_ONLY_PREFIXES = ("facedetect_",)


def _is_read_only_tool(name: str) -> bool:
    return name in _READ_ONLY_TOOLS or any(name.startswith(prefix) for prefix in _READ_ONLY_PREFIXES)


class Agent:
    def __init__(self, runtime: ToolRuntime):
        key = settings.read_openai_key()
        if not key:
            raise RuntimeError("OpenAI-compatible API key is empty")
        self.runtime = runtime
        self.client = AsyncOpenAI(api_key=key, base_url=settings.openai_base_url)
        path = Path("/app/config/system_prompt.txt")
        self.system_prompt = path.read_text(encoding="utf-8") if path.exists() else "You are HassMind, a Home Assistant agent."
        info(
            logger,
            "agent_initialized",
            model=settings.openai_model,
            base_url=settings.openai_base_url,
            max_tool_rounds=settings.max_tool_rounds,
            history_messages=settings.agent_history_messages,
            zalo_history_messages=settings.zalo_history_messages,
            parallel_read_tools=settings.parallel_read_tools,
            system_prompt_chars=len(self.system_prompt),
        )

    async def _execute_tool_call(self, tc, round_index: int) -> dict[str, str]:
        args: dict = {}
        tool_started = perf_counter()
        try:
            args = json.loads(tc.function.arguments or "{}")
        except Exception as exc:
            add_tool_audit(tc.function.name, {}, error=f"{type(exc).__name__}: {exc}")
            exception(
                logger,
                "tool_arguments_invalid",
                message="Tool arguments are not valid JSON",
                tool=tc.function.name,
                tool_call_id=tc.id,
                raw_arguments=preview(tc.function.arguments or ""),
            )
            content = json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False)
            return {"role": "tool", "tool_call_id": tc.id, "content": content}

        info(
            logger,
            "tool_call_started",
            tool=tc.function.name,
            tool_call_id=tc.id,
            round=round_index,
            arguments=preview(args),
        )
        try:
            result = await self.runtime.call(tc.function.name, args)
            duration_ms = round((perf_counter() - tool_started) * 1000, 2)
            add_tool_audit(tc.function.name, args, result=result)
            info(
                logger,
                "tool_call_completed",
                tool=tc.function.name,
                tool_call_id=tc.id,
                duration_ms=duration_ms,
                result=preview(result),
            )
            content = json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:
            duration_ms = round((perf_counter() - tool_started) * 1000, 2)
            add_tool_audit(tc.function.name, args, error=f"{type(exc).__name__}: {exc}")
            exception(
                logger,
                "tool_call_failed",
                message="Tool call failed",
                tool=tc.function.name,
                tool_call_id=tc.id,
                duration_ms=duration_ms,
                arguments=preview(args),
                error_type=type(exc).__name__,
            )
            content = json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False)
        return {"role": "tool", "tool_call_id": tc.id, "content": content}

    async def chat(self, session_id: str, user_text: str, source: str = "web") -> str:
        started = perf_counter()
        with log_context(session_id=session_id, source=source, component="agent"):
            info(
                logger,
                "chat_started",
                message="Agent chat started",
                user_chars=len(user_text),
                user=preview(user_text),
            )
            try:
                add_message(session_id, "user", user_text, source)
                history_limit = settings.zalo_history_messages if source == "zalo" else settings.agent_history_messages
                history = get_messages(session_id, max(2, int(history_limit)))
                messages = [{"role": "system", "content": self.system_prompt}]
                if source == "zalo":
                    messages.append({"role": "system", "content": _ZALO_FORMAT_PROMPT})
                messages.extend(history)
                tool_schemas = schemas()
                info(
                    logger,
                    "chat_context_ready",
                    history_messages=len(history),
                    history_limit=history_limit,
                    outbound_messages=len(messages),
                    tools_available=len(tool_schemas),
                )

                for round_index in range(1, settings.max_tool_rounds + 1):
                    llm_started = perf_counter()
                    info(
                        logger,
                        "llm_request_started",
                        round=round_index,
                        model=settings.openai_model,
                        message_count=len(messages),
                        tool_count=len(tool_schemas),
                    )
                    try:
                        resp = await self.client.chat.completions.create(
                            model=settings.openai_model,
                            messages=messages,
                            tools=tool_schemas,
                            tool_choice="auto",
                        )
                    except Exception as exc:
                        exception(
                            logger,
                            "llm_request_failed",
                            message="LLM request failed",
                            round=round_index,
                            model=settings.openai_model,
                            base_url=settings.openai_base_url,
                            duration_ms=round((perf_counter() - llm_started) * 1000, 2),
                            error_type=type(exc).__name__,
                        )
                        raise

                    msg = resp.choices[0].message
                    finish_reason = resp.choices[0].finish_reason
                    usage = getattr(resp, "usage", None)
                    usage_data = None
                    if usage is not None:
                        usage_data = {
                            "prompt_tokens": getattr(usage, "prompt_tokens", None),
                            "completion_tokens": getattr(usage, "completion_tokens", None),
                            "total_tokens": getattr(usage, "total_tokens", None),
                        }
                    info(
                        logger,
                        "llm_request_completed",
                        round=round_index,
                        duration_ms=round((perf_counter() - llm_started) * 1000, 2),
                        finish_reason=finish_reason,
                        response_id=getattr(resp, "id", None),
                        tool_calls=len(msg.tool_calls or []),
                        assistant_chars=len(msg.content or ""),
                        usage=usage_data,
                    )

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
                        info(
                            logger,
                            "chat_completed",
                            duration_ms=round((perf_counter() - started) * 1000, 2),
                            rounds=round_index,
                            answer_chars=len(text),
                            answer=preview(text),
                        )
                        return text

                    calls = list(msg.tool_calls)
                    run_parallel = bool(
                        settings.parallel_read_tools
                        and len(calls) > 1
                        and all(_is_read_only_tool(tc.function.name) for tc in calls)
                    )
                    if run_parallel:
                        batch_started = perf_counter()
                        info(logger, "tool_batch_parallel_started", round=round_index, tool_count=len(calls))
                        tool_messages = await asyncio.gather(*(self._execute_tool_call(tc, round_index) for tc in calls))
                        info(
                            logger,
                            "tool_batch_parallel_completed",
                            round=round_index,
                            tool_count=len(calls),
                            duration_ms=round((perf_counter() - batch_started) * 1000, 2),
                        )
                        messages.extend(tool_messages)
                    else:
                        for tc in calls:
                            messages.append(await self._execute_tool_call(tc, round_index))

                text = "Đã đạt giới hạn số vòng gọi công cụ; HassMind dừng để tránh vòng lặp ngoài ý muốn."
                add_message(session_id, "assistant", text, source)
                warning(
                    logger,
                    "chat_max_tool_rounds",
                    message="Chat stopped because max tool rounds was reached",
                    duration_ms=round((perf_counter() - started) * 1000, 2),
                    max_tool_rounds=settings.max_tool_rounds,
                )
                return text
            except Exception:
                exception(
                    logger,
                    "chat_failed",
                    message="Agent chat failed",
                    duration_ms=round((perf_counter() - started) * 1000, 2),
                )
                raise
