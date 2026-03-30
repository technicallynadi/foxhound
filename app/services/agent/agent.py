"""FoxhoundAgent: the unified personal AI job agent.

One agent per user. Stateless per-request. Uses Claude tool_use to
dispatch actions to existing services. No shared state between users.

See .foxhound/AGENT_HARNESS_SPEC.md for full specification.
See .foxhound/rules/AGENT.md for building rules.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from uuid import uuid4

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.agent_session import AgentMessage, AgentSession
from app.services.agent.budget import RequestBudget
from app.services.agent.guards import ToolBlocked, ToolGuard
from app.services.agent.registry import (
    discover_tools,
    execute_tool,
    get_tool_definitions,
    get_tool_spec,
)
from app.services.agent.system_prompt import build_system_prompt

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 20
SESSION_REUSE_SECONDS = 7200  # 2 hours


class FoxhoundAgent:
    """Personal AI job agent. One instance per application, stateless per-request."""

    def __init__(self) -> None:
        self._client: anthropic.AsyncAnthropic | None = None
        self._guard = ToolGuard()
        self._tools_discovered = False

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    def _ensure_tools_discovered(self) -> None:
        if not self._tools_discovered:
            discover_tools()
            self._tools_discovered = True

    # ------------------------------------------------------------------
    # Main entry point (non-streaming)
    # ------------------------------------------------------------------

    async def respond(
        self,
        db: AsyncSession,
        user_id: str,
        message: str,
        session_id: str | None = None,
        channel: str = "web",
    ) -> dict:
        """Process a user message. Returns the agent's response.

        Everything is scoped to this user_id. No cross-user data access.
        """
        self._ensure_tools_discovered()
        budget = RequestBudget()

        # 1. Get or create session (scoped to this user)
        session = await self._get_or_create_session(db, user_id, session_id, channel)

        # 2. Persist user message
        user_msg = AgentMessage(
            id=str(uuid4()), session_id=session.id,
            role="user", content=message, channel=channel,
        )
        db.add(user_msg)
        session.last_message_at = datetime.now(timezone.utc)
        await db.flush()

        # 3. Load history + build system prompt
        history = await self._load_history(db, session.id)
        system = await build_system_prompt(db, user_id, channel)
        messages = self._history_to_messages(history)

        try:
            self._validate_messages(messages)
        except ValueError:
            logger.warning("Corrupt message history — dropping history for sync request")
            messages = [{"role": "user", "content": message}]

        # 4. Tool_use loop
        tool_calls_log: list[dict] = []
        tool_results_log: list[dict] = []

        while budget.can_continue():
            response = await self.client.messages.create(
                model=settings.agent_model,
                max_tokens=1024,
                system=system,
                tools=get_tool_definitions(),
                messages=messages,
            )

            budget.record_api_call(
                response.usage.input_tokens, response.usage.output_tokens
            )

            if response.stop_reason != "tool_use":
                # Text response — done
                text = "".join(b.text for b in response.content if hasattr(b, "text"))
                db.add(AgentMessage(
                    id=str(uuid4()), session_id=session.id,
                    role="assistant", content=text, channel=channel,
                ))
                await db.commit()
                logger.info("Agent respond: %s", budget.summary())
                return {
                    "response": text,
                    "session_id": session.id,
                    "tool_calls": tool_calls_log,
                    "tool_results": tool_results_log,
                    "budget": budget.summary(),
                }

            # Process tool calls
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})
            tool_results_content = []

            for block in assistant_content:
                if block.type != "tool_use":
                    continue

                t0 = time.monotonic()
                tool_name = block.name
                tool_input = block.input

                logger.info("Tool call: %s(%s)", tool_name, json.dumps(tool_input)[:200])
                tool_calls_log.append({"tool": tool_name, "input": tool_input})

                # Persist tool_use message
                db.add(AgentMessage(
                    id=str(uuid4()), session_id=session.id,
                    role="tool_use", content="", channel=channel,
                    tool_use_id=block.id, tool_name=tool_name,
                    tool_input_json=json.dumps(tool_input),
                ))

                # Pre-execution guard
                try:
                    await self._guard.check(db, user_id, tool_name, tool_input)
                except ToolBlocked as blocked:
                    result = blocked.to_dict()
                    logger.info("Tool blocked: %s — %s", tool_name, blocked.code)
                else:
                    # Execute tool (scoped to this user_id)
                    result = await execute_tool(db, user_id, tool_name, tool_input)

                duration_ms = int((time.monotonic() - t0) * 1000)
                budget.record_tool_call(tool_name, duration_ms)

                result_json = json.dumps(result)
                tool_results_log.append({"tool": tool_name, "result": result})

                # Persist tool_result
                db.add(AgentMessage(
                    id=str(uuid4()), session_id=session.id,
                    role="tool_result", content=result_json[:2000], channel=channel,
                    tool_use_id=block.id, tool_name=tool_name,
                    tool_result_json=result_json,
                ))

                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_json,
                })

            messages.append({"role": "user", "content": tool_results_content})
            await db.flush()

        # Budget exhausted
        fallback = "I've done as much as I can on this. Let me know what you'd like to do next."
        db.add(AgentMessage(
            id=str(uuid4()), session_id=session.id,
            role="assistant", content=fallback, channel=channel,
        ))
        await db.commit()
        logger.warning("Agent budget exhausted: %s", budget.summary())
        return {
            "response": fallback,
            "session_id": session.id,
            "tool_calls": tool_calls_log,
            "tool_results": tool_results_log,
            "budget": budget.summary(),
        }

    # ------------------------------------------------------------------
    # Streaming entry point (SSE)
    # ------------------------------------------------------------------

    async def respond_stream(
        self,
        db: AsyncSession,
        user_id: str,
        message: str,
        session_id: str | None = None,
        channel: str = "web",
    ) -> AsyncGenerator[str, None]:
        """Stream the agent's response as SSE events."""
        self._ensure_tools_discovered()
        budget = RequestBudget()

        session = await self._get_or_create_session(db, user_id, session_id, channel)
        db.add(AgentMessage(
            id=str(uuid4()), session_id=session.id,
            role="user", content=message, channel=channel,
        ))
        session.last_message_at = datetime.now(timezone.utc)
        await db.flush()

        history = await self._load_history(db, session.id)
        system = await build_system_prompt(db, user_id, channel)
        messages = self._history_to_messages(history)
        full_response = ""

        # If history is corrupt, just use the latest user message
        try:
            self._validate_messages(messages)
        except ValueError:
            logger.warning("Corrupt message history — dropping history for this request")
            messages = [{"role": "user", "content": message}]

        while budget.can_continue():
            async with self.client.messages.stream(
                model=settings.agent_model,
                max_tokens=1024,
                system=system,
                tools=get_tool_definitions(),
                messages=messages,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                        chunk = event.delta.text
                        full_response += chunk
                        yield f"event: text_delta\ndata: {json.dumps({'text': chunk})}\n\n"

                final_message = await stream.get_final_message()

            budget.record_api_call(
                final_message.usage.input_tokens, final_message.usage.output_tokens
            )

            if final_message.stop_reason != "tool_use":
                break

            # Tool calls
            assistant_content = final_message.content
            messages.append({"role": "assistant", "content": assistant_content})
            tool_results_content = []

            for block in assistant_content:
                if block.type != "tool_use":
                    continue

                logger.info("Stream tool call: %s(%s)", block.name, json.dumps(block.input)[:200])
                yield f"event: tool_call_start\ndata: {json.dumps({'tool_name': block.name, 'tool_input': block.input})}\n\n"

                db.add(AgentMessage(
                    id=str(uuid4()), session_id=session.id,
                    role="tool_use", content="", channel=channel,
                    tool_use_id=block.id, tool_name=block.name,
                    tool_input_json=json.dumps(block.input),
                ))

                try:
                    await self._guard.check(db, user_id, block.name, block.input)
                except ToolBlocked as blocked:
                    result = blocked.to_dict()
                else:
                    result = await execute_tool(db, user_id, block.name, block.input)

                logger.info("Stream tool result: %s → %s", block.name, json.dumps(result)[:200])
                budget.record_tool_call(block.name)
                result_json = json.dumps(result)

                yield f"event: tool_result\ndata: {json.dumps({'tool_name': block.name, 'data': result, 'message': result.get('message', '')})}\n\n"

                db.add(AgentMessage(
                    id=str(uuid4()), session_id=session.id,
                    role="tool_result", content=result_json[:2000], channel=channel,
                    tool_use_id=block.id, tool_name=block.name,
                    tool_result_json=result_json,
                ))

                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_json,
                })

            messages.append({"role": "user", "content": tool_results_content})
            await db.flush()
            full_response = ""  # Reset for next Claude turn

        # Persist final response
        if full_response:
            db.add(AgentMessage(
                id=str(uuid4()), session_id=session.id,
                role="assistant", content=full_response, channel=channel,
            ))

        await db.commit()
        yield f"event: done\ndata: {json.dumps({'session_id': session.id})}\n\n"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_or_create_session(
        self, db: AsyncSession, user_id: str,
        session_id: str | None, channel: str,
    ) -> AgentSession:
        """Get or create a session scoped to this user."""
        if session_id:
            session = await db.get(AgentSession, session_id)
            if session and session.user_id == user_id:
                return session

        # Find most recent session for this user
        result = await db.execute(
            select(AgentSession)
            .where(AgentSession.user_id == user_id)
            .order_by(AgentSession.last_message_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()

        if session:
            last_msg = session.last_message_at
            if last_msg.tzinfo is None:
                last_msg = last_msg.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - last_msg).total_seconds()
            if age < SESSION_REUSE_SECONDS:
                return session

        session = AgentSession(
            id=str(uuid4()), user_id=user_id, channel=channel,
        )
        db.add(session)
        await db.flush()
        return session

    def _validate_messages(self, messages: list[dict]) -> None:
        """Raise ValueError if messages have orphaned tool_use blocks."""
        tool_use_ids = set()
        tool_result_ids = set()
        for msg in messages:
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_use_ids.add(block.get("id"))
                        elif block.get("type") == "tool_result":
                            tool_result_ids.add(block.get("tool_use_id"))
                    elif hasattr(block, "type"):
                        if block.type == "tool_use":
                            tool_use_ids.add(block.id)
        orphaned = tool_use_ids - tool_result_ids
        if orphaned:
            raise ValueError(f"Orphaned tool_use IDs: {orphaned}")

    def _fix_tool_pairs(self, messages: list[dict]) -> list[dict]:
        """Ensure every tool_use block has a matching tool_result.

        If the last assistant message has tool_use blocks without corresponding
        tool_result responses, add synthetic error results so the conversation
        can continue without Anthropic rejecting the request.
        """
        if len(messages) < 2:
            return messages

        # Find all tool_use IDs in the last assistant message
        last_assistant = None
        last_assistant_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "assistant":
                last_assistant = messages[i]
                last_assistant_idx = i
                break

        if not last_assistant or not isinstance(last_assistant.get("content"), list):
            return messages

        tool_use_ids = set()
        for block in last_assistant["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_use_ids.add(block["id"])
            elif hasattr(block, "type") and block.type == "tool_use":
                tool_use_ids.add(block.id)

        if not tool_use_ids:
            return messages

        # Check if there's a user message after with matching tool_results
        tool_result_ids = set()
        for msg in messages[last_assistant_idx + 1:]:
            if msg.get("role") == "user":
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            tool_result_ids.add(block.get("tool_use_id"))

        missing = tool_use_ids - tool_result_ids
        if not missing:
            return messages

        # Add synthetic tool_result for missing IDs
        logger.warning("Fixing %d orphaned tool_use blocks in history", len(missing))
        synthetic_results = [
            {"type": "tool_result", "tool_use_id": tid, "content": "Error: previous request was interrupted. Please try again."}
            for tid in missing
        ]
        messages.append({"role": "user", "content": synthetic_results})
        return messages

    async def _load_history(self, db: AsyncSession, session_id: str) -> list[AgentMessage]:
        """Load the last N messages for this session."""
        result = await db.execute(
            select(AgentMessage)
            .where(AgentMessage.session_id == session_id)
            .order_by(AgentMessage.created_at.desc())
            .limit(MAX_HISTORY_MESSAGES)
        )
        messages = list(result.scalars().all())
        messages.reverse()
        return messages

    def _history_to_messages(self, history: list[AgentMessage]) -> list[dict]:
        """Convert DB messages to Claude API format."""
        messages: list[dict] = []
        i = 0

        while i < len(history):
            msg = history[i]

            if msg.role == "user":
                messages.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                messages.append({"role": "assistant", "content": msg.content})
            elif msg.role == "tool_use":
                tool_blocks = []
                tool_results = []

                while i < len(history) and history[i].role == "tool_use":
                    tu = history[i]
                    tool_blocks.append({
                        "type": "tool_use",
                        "id": tu.tool_use_id,
                        "name": tu.tool_name,
                        "input": json.loads(tu.tool_input_json or "{}"),
                    })
                    i += 1

                while i < len(history) and history[i].role == "tool_result":
                    tr = history[i]
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tr.tool_use_id,
                        "content": tr.tool_result_json or tr.content,
                    })
                    i += 1

                if tool_blocks:
                    messages.append({"role": "assistant", "content": tool_blocks})
                if tool_results:
                    messages.append({"role": "user", "content": tool_results})
                continue

            i += 1

        return messages
