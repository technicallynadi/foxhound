"""Scout Inbox view — browse and act on discovered opportunities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DataTable, Input

from foxhound.tui.widgets.detail_panel import DetailPanel

if TYPE_CHECKING:
    from foxhound.tui.data import TUIData


# URL patterns that indicate a cloneable repository
_REPO_URL_HINTS = ("github.com/", "gitlab.com/", "bitbucket.org/")


def _is_repo_url(url: str | None) -> bool:
    """Check if a URL points to a git repository."""
    if not url:
        return False
    return any(hint in url for hint in _REPO_URL_HINTS)


ButtonRow = list[tuple[str, str, str]]

# Row 1: primary actions | Row 2: link actions
_DEFAULT_ROWS: list[ButtonRow] = [
    [
        ("Approve", "approve", "success"),
        ("Reject", "reject", "error"),
        ("Delete", "delete", "warning"),
        ("Fetch New", "fetch", "primary"),
    ],
    [
        ("Open Link", "open_link", "primary"),
        ("Copy URL", "copy_link", "purple"),
    ],
]

# Repo variant adds Clone Repo on row 2
_REPO_ROWS: list[ButtonRow] = [
    [
        ("Approve", "approve", "success"),
        ("Reject", "reject", "error"),
        ("Delete", "delete", "warning"),
        ("Fetch New", "fetch", "primary"),
    ],
    [
        ("Clone Repo", "clone", "primary"),
        ("Open Link", "open_link", "primary"),
        ("Copy URL", "copy_link", "purple"),
    ],
]


class ScoutInboxTable(DataTable[str]):
    """Scout inbox table with inline action keybindings."""

    BINDINGS = [
        Binding("a", "approve", "Approve", show=True),
        Binding("r", "reject", "Reject", show=True),
        Binding("c", "clone", "Clone", show=True),
        Binding("o", "open_link", "Open", show=True),
        Binding("y", "copy_link", "Copy URL", show=True),
        Binding("delete", "delete", "Delete", show=True),
        Binding("f", "fetch", "Fetch New", show=True),
        Binding("f5", "refresh", "Refresh", show=True),
        Binding("q", "quit_app", "Quit", show=True),
    ]

    class ActionRequested(Message):
        """Emitted when user presses an action key."""

        def __init__(self, action: str) -> None:
            super().__init__()
            self.action = action

    def action_approve(self) -> None:
        self.post_message(self.ActionRequested("approve"))

    def action_reject(self) -> None:
        self.post_message(self.ActionRequested("reject"))

    def action_clone(self) -> None:
        self.post_message(self.ActionRequested("clone"))

    def action_delete(self) -> None:
        self.post_message(self.ActionRequested("delete"))

    def action_open_link(self) -> None:
        self.post_message(self.ActionRequested("open_link"))

    def action_copy_link(self) -> None:
        self.post_message(self.ActionRequested("copy_link"))

    def action_refresh(self) -> None:
        self.post_message(self.ActionRequested("refresh"))

    def action_fetch(self) -> None:
        self.post_message(self.ActionRequested("fetch"))

    def action_quit_app(self) -> None:
        self.app.exit()

    def watch_cursor_coordinate(self, old: object, new: object) -> None:
        super().watch_cursor_coordinate(old, new)
        self.post_message(self.ActionRequested(f"cursor:{self.cursor_row}"))


class ScoutInboxView(Vertical):
    """Interactive inbox for reviewing scout opportunities."""

    def __init__(self, data: TUIData, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._data = data
        self._opportunity_ids: list[str] = []
        self._query: str = ""
        self._current_button_mode: str = "default"
        self._summarizing_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Input(
            placeholder="Search opportunities... (Enter to filter, Esc to clear)",
            id="scout-search",
        )
        yield ScoutInboxTable(id="scout-table")
        yield DetailPanel(button_rows=_DEFAULT_ROWS, id="scout-detail")

    def on_mount(self) -> None:
        table = self.query_one("#scout-table", ScoutInboxTable)
        table.add_columns("Tier", "Score", "Source", "Title", "Topic")
        table.cursor_type = "row"
        table.zebra_stripes = True
        self.call_after_refresh(self._load_data)

    def on_show(self) -> None:
        self.call_after_refresh(self._load_data)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        self._query = event.value.strip()
        await self._load_data()
        table = self.query_one("#scout-table", ScoutInboxTable)
        table.focus()

    async def on_input_changed(self, event: Input.Changed) -> None:
        if not event.value.strip() and self._query:
            self._query = ""
            await self._load_data()

    async def on_detail_panel_button_pressed(
        self, message: DetailPanel.ButtonPressed
    ) -> None:
        if message.action == "confirm_clone":
            await self._do_confirm_clone()
            return
        if message.action == "cancel_clone":
            await self._cancel_clone_review()
            return

        actions = {
            "approve": self._do_approve,
            "reject": self._do_reject,
            "clone": self._do_clone,
            "open_link": self._do_open_link,
            "copy_link": self._do_copy_link,
            "delete": self._do_delete,
            "fetch": self._do_fetch,
        }
        handler = actions.get(message.action)
        if handler:
            await handler()

    async def on_scout_inbox_table_action_requested(
        self, message: ScoutInboxTable.ActionRequested
    ) -> None:
        if message.action.startswith("cursor:"):
            row = int(message.action.split(":")[1])
            await self._show_detail(row)
            return

        actions = {
            "approve": self._do_approve,
            "reject": self._do_reject,
            "clone": self._do_clone,
            "open_link": self._do_open_link,
            "copy_link": self._do_copy_link,
            "delete": self._do_delete,
            "refresh": self._do_refresh,
            "fetch": self._do_fetch,
        }
        handler = actions.get(message.action)
        if handler:
            await handler()

    async def _do_approve(self) -> None:
        opp_id = self._get_selected_id()
        if opp_id is None:
            return

        is_repo = await self._data.check_clone_eligible(opp_id)
        if is_repo:
            self.app.notify(
                "This opportunity links to a repo. "
                "Use [bold]c[/bold] (Clone) to review and clone it.",
                severity="warning",
            )

        await self._data.approve_opportunity(opp_id)
        self.app.notify("Approved")
        await self._load_data()

    async def _do_reject(self) -> None:
        opp_id = self._get_selected_id()
        if opp_id is None:
            return
        await self._data.reject_opportunity(opp_id)
        self.app.notify("Rejected")
        await self._load_data()

    async def _do_delete(self) -> None:
        opp_id = self._get_selected_id()
        if opp_id is None:
            return
        await self._data.delete_opportunity(opp_id)
        self.app.notify("Deleted")
        await self._load_data()

    async def _do_open_link(self) -> None:
        opp_id = self._get_selected_id()
        if opp_id is None:
            return
        item = await self._data.get_opportunity(opp_id)
        if item is None or not item.source_url:
            self.app.notify("No URL available", severity="warning")
            return

        url = item.source_url
        if not url.startswith(("http://", "https://")):
            self.app.notify("Cannot open non-HTTP URL", severity="warning")
            return

        import webbrowser

        webbrowser.open(url)
        self.app.notify(f"Opened {url}")

    async def _do_copy_link(self) -> None:
        opp_id = self._get_selected_id()
        if opp_id is None:
            return
        item = await self._data.get_opportunity(opp_id)
        if item is None or not item.source_url:
            self.app.notify("No URL available", severity="warning")
            return

        try:
            import subprocess

            subprocess.run(
                ["pbcopy"], input=item.source_url.encode(),
                check=True, timeout=5,
            )
            self.app.notify("URL copied to clipboard")
        except Exception:
            self.app.notify(f"URL: {item.source_url}", severity="information")

    async def _do_clone(self) -> None:
        opp_id = self._get_selected_id()
        if opp_id is None:
            return

        is_repo = await self._data.check_clone_eligible(opp_id)
        if not is_repo:
            self.app.notify(
                "This opportunity does not link to a cloneable repository.",
                severity="warning",
            )
            return

        request = await self._data.prepare_clone(opp_id)
        if request is None:
            self.app.notify("Could not prepare clone request.", severity="error")
            return

        review = await self._data.get_clone_review(request)

        self._pending_clone = request

        detail = self.query_one("#scout-detail", DetailPanel)

        lines = [
            "[bold red]SAFETY REVIEW — External Repository Clone[/bold red]",
            "",
        ]
        for disclaimer in review.get("disclaimers", []):
            lines.append(f"  [yellow]![/yellow] {disclaimer}")

        lines.append("")
        lines.append(f"[bold]Repository:[/bold] {review.get('source_url', '')}")
        lines.append(f"[bold]Clone to:[/bold] {review.get('clone_path', '')}")
        lines.append(
            f"[bold]Shallow clone:[/bold] {'Yes' if review.get('shallow_clone') else 'No'}"
        )

        if review.get("warnings"):
            lines.append("")
            lines.append("[bold red]Pre-clone warnings:[/bold red]")
            for warning in review["warnings"]:
                lines.append(f"  [red]![/red] {warning}")

        if review.get("error"):
            lines.append("")
            lines.append(f"[bold red]Error:[/bold red] {review['error']}")
            self._pending_clone = None
        else:
            lines.append("")
            lines.append(
                "[bold]Press Confirm to clone, or Cancel to abort.[/bold]"
            )

        detail.detail_text = "\n".join(lines)

        self._current_button_mode = "clone_review"
        await detail.set_button_rows([
            [("Confirm Clone", "confirm_clone", "warning"),
             ("Cancel", "cancel_clone", "error")],
        ])

    async def _do_confirm_clone(self) -> None:
        from foxhound.scout.clone import CloneStatus

        request = getattr(self, "_pending_clone", None)
        if request is None:
            self.app.notify("No pending clone request.", severity="error")
            return

        request.status = CloneStatus.APPROVED
        result = await self._data.execute_clone(request)
        self._pending_clone = None

        detail = self.query_one("#scout-detail", DetailPanel)

        if result.status == CloneStatus.CLONED:
            # Register the cloned repo so it appears in the repos view
            try:
                await self._data.register_repo(str(result.clone_path))
            except Exception:
                pass

            lines = [
                "[bold green]Repository cloned successfully.[/bold green]",
                "",
                f"[bold]Path:[/bold] {result.clone_path}",
            ]
            if result.warnings:
                lines.append("")
                lines.append("[bold yellow]Post-clone warnings:[/bold yellow]")
                for warning in result.warnings:
                    lines.append(f"  [yellow]![/yellow] {warning}")
                lines.append("")
                lines.append(
                    "[dim]Review the code before running any scripts, "
                    "installs, or build commands from this repository.[/dim]"
                )
            self.app.notify("Cloned successfully")
        else:
            lines = [
                "[bold red]Clone failed.[/bold red]",
                "",
                f"[bold]Error:[/bold] {result.error or 'Unknown error'}",
            ]
            self.app.notify("Clone failed", severity="error")

        detail.detail_text = "\n".join(lines)
        await self._restore_default_buttons()

    async def _cancel_clone_review(self) -> None:
        self._pending_clone = None
        detail = self.query_one("#scout-detail", DetailPanel)
        detail.detail_text = "Clone cancelled."
        await self._restore_default_buttons()
        self.app.notify("Clone cancelled")

    async def _restore_default_buttons(self) -> None:
        """Restore the appropriate default buttons based on selected item."""
        detail = self.query_one("#scout-detail", DetailPanel)
        opp_id = self._get_selected_id()
        needed = "default"
        if opp_id:
            item = await self._data.get_opportunity(opp_id)
            if item and _is_repo_url(item.source_url):
                needed = "repo"
        self._current_button_mode = needed
        rows = _REPO_ROWS if needed == "repo" else _DEFAULT_ROWS
        await detail.set_button_rows(rows)

    async def _do_refresh(self) -> None:
        await self._load_data()
        self.app.notify("Refreshed")

    async def _do_fetch(self) -> None:
        query = self._query or None
        if query:
            self.app.notify(f"Fetching '{query}' from all sources...")
        else:
            self.app.notify("Fetching from all sources...")

        detail = self.query_one("#scout-detail", DetailPanel)
        detail.detail_text = f"Fetching{' ' + repr(query) if query else ''} from all sources..."

        counts = await self._data.run_scout_fetch(query=query, limit=20)

        parts = []
        for source, count in counts.items():
            if count < 0:
                parts.append(f"{source}: error")
            else:
                parts.append(f"{source}: {count} new")
        summary = ", ".join(parts)

        await self._load_data()
        self.app.notify(f"Fetched: {summary}")

    async def _load_data(self) -> None:
        from foxhound.core.models import OpportunityState

        table = self.query_one("#scout-table", DataTable)
        table.clear()
        self._opportunity_ids.clear()

        all_items = await self._data.list_opportunities(
            state=OpportunityState.SUGGESTED, limit=200
        )

        if self._query:
            q = self._query.lower()
            items = [
                item for item in all_items
                if q in item.title.lower()
                or q in (item.description or "").lower()
                or q in item.source_type.lower()
                or q in (item.matched_topic or "").lower()
                or (item.signal_tier and q in item.signal_tier.value)
                or any(q in tag.lower() for tag in (item.tags or []))
            ]
        else:
            items = all_items

        items.sort(key=lambda x: x.opportunity_score, reverse=True)

        for item in items:
            tier_text = item.signal_tier.value if item.signal_tier else "—"
            score_text = (
                f"{item.opportunity_score:.0f}/35"
                if item.opportunity_score > 0
                else "pending"
            )
            source = item.source_type
            if len(source) > 12:
                source = source[:11] + "…"
            title = item.title[:50]
            topic = item.matched_topic[:20] if item.matched_topic else ""

            table.add_row(tier_text, score_text, source, title, topic)
            self._opportunity_ids.append(item.opportunity_id)

        if not items:
            detail = self.query_one("#scout-detail", DetailPanel)
            detail.detail_text = (
                "No opportunities to review.\n"
                "Press [bold]f[/bold] to fetch new opportunities."
            )

    def _build_detail_lines(self, item: Any) -> list[str]:
        """Build the detail text lines for an opportunity."""
        evidence = item.evidence or {}
        llm_scored = evidence.get("llm_scored", False)
        score_label = "LLM" if llm_scored else "Heuristic"

        url = item.source_url or ""
        desc = item.description[:200] if item.description else ""

        # Signal tier badge
        tier_display = item.signal_tier.value.upper() if item.signal_tier else "UNCLASSIFIED"
        tier_colors = {
            "PAIN": "bold red", "WORKAROUND": "bold yellow",
            "REPEATED_QUESTION": "bold cyan", "FEATURE_GAP": "blue", "TREND": "dim",
        }
        tier_style = tier_colors.get(tier_display, "dim")

        # Confidence badge
        conf = item.confidence_level.value if hasattr(item, "confidence_level") else "low"
        conf_colors = {"high": "bold green", "medium": "bold yellow", "low": "dim"}
        conf_style = conf_colors.get(conf, "dim")

        lines = [
            f"[bold]{item.title}[/bold]",
            f"Source: {item.source_type}  {url}",
            "",
            f"[{tier_style}]■ {tier_display}[/{tier_style}]  "
            f"Score: [bold]{item.opportunity_score:.0f}/35[/bold]  "
            f"Confidence: [{conf_style}]{conf.upper()}[/{conf_style}]  "
            f"[dim]({score_label})[/dim]",
        ]

        # 6-dimension scores
        if item.opportunity_score > 0:
            lines.append(
                f"  Pain: {item.problem_intensity:.0f}  "
                f"Freq: {item.frequency:.0f}  "
                f"Workaround: {item.workaround_presence:.0f}  "
                f"Market: {item.market_potential:.0f}  "
                f"Feasibility: {item.build_feasibility:.0f}  "
                f"Topic: {item.topic_relevance:.0f}"
            )

        # AI exposure
        if item.ai_exposure_angle:
            angle = item.ai_exposure_angle.value
            angle_style = "bold magenta" if angle == "disruption" else "bold green"
            lines.append(
                f"  AI Exposure: {item.ai_exposure_score:.0f}/10 "
                f"[{angle_style}]{angle.upper()}[/{angle_style}]"
            )

        # Matched topic
        if item.matched_topic:
            lines.append(f"  Matched Topic: [bold]{item.matched_topic}[/bold]")

        if desc:
            lines.append("")
            lines.append(desc)

        # Metadata
        lang = evidence.get("language", "")
        license_t = evidence.get("license_type", "")
        meta_parts = []
        if lang:
            meta_parts.append(f"Language: {lang}")
        if license_t:
            meta_parts.append(f"License: {license_t}")
        if meta_parts:
            lines.append(f"[dim]{' | '.join(meta_parts)}[/dim]")

        return lines

    async def _show_detail(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self._opportunity_ids):
            return

        opp_id = self._opportunity_ids[row_index]
        item = await self._data.get_opportunity(opp_id)
        if item is None:
            return

        detail = self.query_one("#scout-detail", DetailPanel)
        lines = self._build_detail_lines(item)
        evidence = item.evidence or {}

        # Show cached summary (generated during foxhound scout)
        cached_summary = evidence.get("llm_summary")
        if cached_summary:
            lines.append("")
            lines.append(f"[bold]Summary:[/bold] {cached_summary}")
        detail.detail_text = "\n".join(lines)

        # Show Clone button only for repo URLs — skip if already correct
        needed = "repo" if _is_repo_url(item.source_url) else "default"
        if needed != self._current_button_mode:
            self._current_button_mode = needed
            rows = _REPO_ROWS if needed == "repo" else _DEFAULT_ROWS
            await detail.set_button_rows(rows)

    def _run_summary_worker(self, opp_id: str) -> None:
        """Run summary generation in a Textual worker thread."""
        import threading

        def _worker() -> None:
            summary = self._data._do_summarize(opp_id)
            self._summarizing_id = None
            self.app.call_from_thread(self._apply_summary, opp_id, summary)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _apply_summary(self, opp_id: str, summary: str | None) -> None:
        """Apply summary result back to the detail panel (called from main thread)."""
        current_id = self._get_selected_id()
        if current_id != opp_id:
            return

        detail = self.query_one("#scout-detail", DetailPanel)
        # Re-fetch item to get current state
        import asyncio
        from foxhound.scout.opportunity import OpportunityManager
        mgr = OpportunityManager(self._data.db)
        item = mgr.get(opp_id)
        if item is None:
            return

        lines = self._build_detail_lines(item)
        if summary:
            lines.append("")
            lines.append(f"[bold]Summary:[/bold] {summary}")
        detail.detail_text = "\n".join(lines)

    def _get_selected_id(self) -> str | None:
        table = self.query_one("#scout-table", DataTable)
        if table.cursor_row is not None and table.cursor_row < len(
            self._opportunity_ids
        ):
            return self._opportunity_ids[table.cursor_row]
        return None
