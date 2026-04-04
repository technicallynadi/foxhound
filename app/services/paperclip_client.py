from __future__ import annotations
import logging, os
from typing import Any
import httpx

logger = logging.getLogger(__name__)
_TIMEOUT = 15.0

class PaperclipClient:
    def __init__(self, api_url, api_key, company_id, agent_id=None, run_id=None):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.company_id = company_id
        self.agent_id = agent_id
        self.run_id = run_id

    @classmethod
    def from_env(cls):
        url = os.environ.get("PAPERCLIP_API_URL", "")
        if not url: raise RuntimeError("PAPERCLIP_API_URL must be set")
        return cls(url, os.environ.get("PAPERCLIP_API_KEY",""), os.environ.get("PAPERCLIP_COMPANY_ID",""), os.environ.get("PAPERCLIP_AGENT_ID"), os.environ.get("PAPERCLIP_RUN_ID"))

    @classmethod
    def from_settings(cls):
        from app.core.config import settings
        url = getattr(settings, "PAPERCLIP_API_URL", None)
        if not url: return None
        return cls(url, getattr(settings,"PAPERCLIP_API_KEY",""), getattr(settings,"PAPERCLIP_COMPANY_ID",""), getattr(settings,"PAPERCLIP_AGENT_ID",None), getattr(settings,"PAPERCLIP_RUN_ID",None))

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.api_key: h["Authorization"] = f"Bearer {self.api_key}"
        if self.run_id: h["X-Paperclip-Run-Id"] = self.run_id
        return h

    async def _post(self, path, body):
        async with httpx.AsyncClient(timeout=_TIMEOUT) as h:
            r = await h.post(f"{self.api_url}{path}", json=body, headers=self._headers())
        r.raise_for_status(); return r.json()

    async def _patch(self, path, body):
        async with httpx.AsyncClient(timeout=_TIMEOUT) as h:
            r = await h.patch(f"{self.api_url}{path}", json=body, headers=self._headers())
        r.raise_for_status(); return r.json()

    async def _get(self, path, params=None):
        async with httpx.AsyncClient(timeout=_TIMEOUT) as h:
            r = await h.get(f"{self.api_url}{path}", params=params, headers=self._headers())
        r.raise_for_status(); return r.json()

    async def _put(self, path, body):
        async with httpx.AsyncClient(timeout=_TIMEOUT) as h:
            r = await h.put(f"{self.api_url}{path}", json=body, headers=self._headers())
        r.raise_for_status(); return r.json()

    async def create_issue(self, title, description="", status="todo", priority="medium", assignee_agent_id=None, parent_id=None, goal_id=None, metadata=None):
        body = {"title": title, "description": description, "status": status, "priority": priority}
        if assignee_agent_id: body["assigneeAgentId"] = assignee_agent_id
        if parent_id: body["parentId"] = parent_id
        if goal_id: body["goalId"] = goal_id
        if metadata: body["metadata"] = metadata
        result = await self._post(f"/api/companies/{self.company_id}/issues", body)
        logger.info("Created issue %s: %s", result.get("identifier"), title)
        return result

    async def create_subtask(self, parent_id, title, description="", assignee_agent_id=None, goal_id=None):
        body = {"title": title, "description": description, "status": "todo", "parentId": parent_id}
        if assignee_agent_id: body["assigneeAgentId"] = assignee_agent_id
        if goal_id: body["goalId"] = goal_id
        result = await self._post(f"/api/companies/{self.company_id}/issues", body)
        logger.info("Created subtask %s under %s: %s", result.get("identifier"), parent_id[:8], title)
        return result

    async def update_issue(self, issue_id, status=None, comment=None, **kwargs):
        body = {k: v for k, v in kwargs.items() if v is not None}
        if status: body["status"] = status
        if comment: body["comment"] = comment
        return await self._patch(f"/api/issues/{issue_id}", body)

    async def comment(self, issue_id, text):
        return await self._post(f"/api/issues/{issue_id}/comments", {"body": text})

    async def get_issue(self, issue_id):
        return await self._get(f"/api/issues/{issue_id}")

    async def attach_document(self, issue_id, key, title, body_text, base_revision_id=None):
        return await self._put(f"/api/issues/{issue_id}/documents/{key}", {"title": title, "format": "markdown", "body": body_text, "baseRevisionId": base_revision_id})

    async def search_issues(self, query, status=None, assignee_agent_id=None):
        params = {"q": query}
        if status: params["status"] = status
        if assignee_agent_id: params["assigneeAgentId"] = assignee_agent_id
        return await self._get(f"/api/companies/{self.company_id}/issues", params)
