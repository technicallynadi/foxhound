const state = {
  opportunities: [],
  selectedId: null,
  activeRunId: null,
  eventSource: null,
  subscriptions: [],
  destinations: [],
  notifications: [],
  dispatchJobs: [],
  selectedJobId: null,
};

function qs(id) {
  return document.getElementById(id);
}

function formatScore(value) {
  return typeof value === "number" ? value.toFixed(2) : "n/a";
}

function statusBadge(status) {
  const colors = {
    queued: 'background: #f3f4f6; color: #374151;',
    running: 'background: #dcfce7; color: #15803d;',
    awaiting_approval: 'background: #fef9c3; color: #854d0e;',
    completed: 'background: #dbeafe; color: #1d4ed8;',
    canceled: 'background: #f1f5f9; color: #475569;',
    failed: 'background: #fee2e2; color: #b91c1c;'
  };
  return `<span class="chip" style="${colors[status] || ''}">${status.replace('_', ' ')}</span>`;
}

function agentIcon(type) {
  const icons = {
    discovery: '🔍',
    recon: '🔭',
    apply: '📨',
    outreach: '📢',
    pathfinder: '🗺️',
    watchdog: '🐕'
  };
  return icons[type] || '🤖';
}

function renderStats(stats) {
  const root = qs("stats");
  const byStatus = stats.by_listing_status || {};
  root.innerHTML = `
    <div class="stat-grid">
      <div class="stat"><span>Total</span><strong>${stats.total ?? 0}</strong></div>
      <div class="stat"><span>Promoted</span><strong>${byStatus.promoted ?? 0}</strong></div>
      <div class="stat"><span>Listed</span><strong>${byStatus.listed ?? 0}</strong></div>
      <div class="stat"><span>Validated</span><strong>${byStatus.validated ?? 0}</strong></div>
    </div>
  `;
}

function detailMarkup(item) {
  if (!item) {
    return "Choose a marketplace opportunity to inspect the full payload and build context.";
  }
  const payload = item.payload || {};
  const evidence = item.evidence_summary?.top_items || [];
  const plans = payload.mvp_plan || [];
  const guidance = payload.implementation_guidance || {};
  return `
    <div class="detail-block">
      <h3>${item.title}</h3>
      <p>${item.summary || "No summary available."}</p>
      <div class="meta">
        <span class="chip">${item.vertical || "unresolved"}</span>
        <span class="chip">${item.confidence}</span>
        <span class="chip">Opp ${formatScore(item.opportunity_score)}</span>
        <span class="chip">Exec ${formatScore(item.execution_ready_score)}</span>
      </div>
    </div>
    <div class="detail-block">
      <h3>Workflow</h3>
      <p>${item.workflow}</p>
      <p><strong>Broken step:</strong> ${item.broken_step || "n/a"}</p>
      <p><strong>Wedge:</strong> ${item.wedge}</p>
    </div>
    <div class="detail-block">
      <h3>Current Solutions</h3>
      <ul>${(item.current_solutions || []).map((x) => `<li>${x}</li>`).join("") || "<li>None captured yet</li>"}</ul>
    </div>
    <div class="detail-block">
      <h3>MVP Plan</h3>
      <ul>${plans.map((x) => `<li>${x}</li>`).join("") || "<li>No structured plan yet</li>"}</ul>
    </div>
    <div class="detail-block">
      <h3>Implementation Guidance</h3>
      <ul>${(guidance.recommended_build_order || []).map((x) => `<li>${x}</li>`).join("") || "<li>No explicit build order yet</li>"}</ul>
    </div>
    <div class="detail-block">
      <h3>Evidence</h3>
      <ul>${evidence.map((e) => `<li><strong>${e.type || "signal"}:</strong> ${e.text || ""}</li>`).join("") || "<li>No evidence summary yet</li>"}</ul>
    </div>
  `;
}

function renderDetail(item) {
  qs("detail-status").textContent = item ? `${item.listing_status} • ${item.curation_status}` : "Select an opportunity";
  const view = qs("detail-view");
  view.classList.toggle("empty", !item);
  view.innerHTML = detailMarkup(item);
}

function renderMarketplace() {
  const root = qs("marketplace-list");
  qs("marketplace-count").textContent = `${state.opportunities.length} loaded`;
  if (!state.opportunities.length) {
    root.innerHTML = `<div class="detail-view empty">No marketplace opportunities yet. Run a fresh search to populate inventory.</div>`;
    renderDetail(null);
    return;
  }
  root.innerHTML = state.opportunities.map((item) => `
    <article class="card ${item.opportunity_id === state.selectedId ? "active" : ""}" data-id="${item.opportunity_id}">
      <h3>${item.title}</h3>
      <p>${item.summary || item.wedge}</p>
      <div class="meta">
        <span class="chip">${item.vertical || "unresolved"}</span>
        <span class="chip">${item.listing_status}</span>
        <span class="chip">${item.confidence}</span>
        <span class="chip">Fresh ${formatScore(item.freshness_score)}</span>
        <span class="chip">Exec ${formatScore(item.execution_ready_score)}</span>
      </div>
    </article>
  `).join("");

  root.querySelectorAll(".card").forEach((card) => {
    card.addEventListener("click", async () => {
      const id = card.dataset.id;
      state.selectedId = id;
      renderMarketplace();
      await loadOpportunityDetail(id);
    });
  });

  if (!state.selectedId) {
    state.selectedId = state.opportunities[0].opportunity_id;
    loadOpportunityDetail(state.selectedId);
  }
}

function renderJobRow(job) {
  const isSelected = state.selectedJobId === job.id;
  return `
    <div class="mini-card ${isSelected ? 'active' : ''}" data-job-id="${job.id}">
      <div class="section-header" style="margin-bottom: 8px">
        <h4>${agentIcon(job.agent_type)} ${job.job_type.toUpperCase()}</h4>
        ${statusBadge(job.status)}
      </div>
      <div class="meta">
        <span class="chip" style="background: none; border: 1px solid var(--line)">#${job.id.slice(0, 8)}</span>
        ${job.child_count > 0 ? `<button class="ghost btn-sm" data-action="tree">Tree (${job.child_count})</button>` : ''}
        ${['queued', 'running', 'awaiting_approval'].includes(job.status) ? `<button class="ghost btn-sm" data-action="cancel">Cancel</button>` : ''}
      </div>
    </div>
  `;
}

function renderApprovalCard(job) {
  return `
    <div class="mini-card" style="border-left: 4px solid #eab308">
      <div class="section-header" style="margin-bottom: 8px">
        <h4>${agentIcon(job.agent_type)} ${job.job_type.toUpperCase()}</h4>
        <span class="chip" style="background: #fef9c3; color: #854d0e">Needs Approval</span>
      </div>
      <p style="font-size: 0.85rem">Job #${job.id.slice(0, 8)} requires your sign-off to proceed.</p>
      <div class="actions">
        <button class="btn-sm" data-action="approve" style="background: #15803d">Approve</button>
        <button class="ghost btn-sm" data-action="deny" style="color: #b91c1c; border-color: rgba(185, 28, 28, 0.2)">Deny</button>
      </div>
    </div>
  `;
}

function renderDagNode(node) {
  return `
    <div class="dag-node">
      <div class="section-header" style="margin-bottom: 0">
        <span style="font-size: 0.9rem">${agentIcon(node.agent_type)} <strong>${node.job_type}</strong></span>
        ${statusBadge(node.status)}
      </div>
      ${node.children && node.children.length ? `
        <div class="dag-children">
          ${node.children.map(renderDagNode).join('')}
        </div>
      ` : ''}
    </div>
  `;
}

async function loadDispatch() {
  try {
    const data = await api("/api/v1/dispatch/jobs");
    state.dispatchJobs = data || [];

    const approvals = state.dispatchJobs.filter(j => j.status === 'awaiting_approval');
    const active = state.dispatchJobs.filter(j => j.status !== 'awaiting_approval');

    const approvalQueue = qs("approval-queue");
    const approvalList = qs("approval-list");
    if (approvals.length) {
      approvalQueue.classList.remove("hidden");
      approvalList.innerHTML = approvals.map(renderApprovalCard).join('');
    } else {
      approvalQueue.classList.add("hidden");
    }

    const jobList = qs("dispatch-jobs");
    jobList.innerHTML = active.map(renderJobRow).join('') || '<div class="muted" style="text-align: center; padding: 20px">No active jobs</div>';
    
    qs("dispatch-status").textContent = active.length ? `${active.length} active` : 'Idle';
  } catch (err) {
    console.error("Dispatch load failed", err);
    qs("dispatch-status").textContent = 'Error';
  }
}

async function openDag(jobId) {
  state.selectedJobId = jobId;
  qs("dispatch-dag").classList.remove("hidden");
  qs("dag-tree").innerHTML = '<div class="muted">Loading tree...</div>';
  try {
    const dag = await api(`/api/v1/dispatch/dag/${jobId}`);
    qs("dag-title").textContent = `Tree #${jobId.slice(0, 8)}`;
    qs("dag-tree").innerHTML = renderDagNode(dag);
  } catch (err) {
    qs("dag-tree").innerHTML = `<div class="chip failed">Failed to load DAG: ${err.message}</div>`;
  }
}

async function dispatchAction(id, action) {
  try {
    const response = await fetch(`/api/v1/dispatch/jobs/${id}/${action}`, { method: 'POST' });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(error.detail || 'Action failed');
    }
    await loadDispatch();
    if (action === 'cancel' && state.selectedJobId === id) {
      qs("dispatch-dag").classList.add("hidden");
    }
  } catch (err) {
    alert(`Action ${action} failed: ${err.message}`);
  }
}

function initDispatch() {
  const panel = qs("dispatch-panel");
  panel.addEventListener("click", async (e) => {
    const btn = e.target.closest("button");
    const card = e.target.closest(".mini-card");
    const jobId = card?.dataset.jobId;

    if (btn) {
      const action = btn.dataset.action;
      if (action === 'refresh') await loadDispatch();
      if (action === 'tree' && jobId) await openDag(jobId);
      if (['approve', 'deny', 'cancel'].includes(action) && jobId) await dispatchAction(jobId, action);
      return;
    }

    if (jobId && !e.target.closest("button")) {
      await openDag(jobId);
    }
  });

  qs("dag-close").addEventListener("click", () => {
    qs("dispatch-dag").classList.add("hidden");
    state.selectedJobId = null;
    loadDispatch();
  });

  setInterval(loadDispatch, 5000);
  loadDispatch();
}

async function api(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

async function loadMarketplace() {
  const params = new URLSearchParams();
  const vertical = qs("filter-vertical").value.trim();
  const confidence = qs("filter-confidence").value;
  const execution = qs("filter-execution").value;
  const listing = qs("filter-listing").value;
  if (vertical) params.set("vertical", vertical);
  if (confidence) params.set("confidence", confidence);
  if (execution) params.set("min_execution_ready_score", execution);
  if (listing) params.set("listing_status", listing);
  const data = await api(`/v1/marketplace/opportunities${params.toString() ? `?${params}` : ""}`);
  state.opportunities = data.opportunities || [];
  if (!state.opportunities.find((x) => x.opportunity_id === state.selectedId)) {
    state.selectedId = state.opportunities[0]?.opportunity_id || null;
  }
  renderMarketplace();
}

async function loadStats() {
  const stats = await api("/v1/marketplace/stats");
  renderStats(stats);
}

async function loadOpportunityDetail(id) {
  if (!id) return;
  const item = await api(`/v1/marketplace/opportunities/${id}`);
  renderDetail(item);
}

function renderSubscriptions() {
  const root = qs("subscription-list");
  qs("subscription-count").textContent = `${state.subscriptions.length} saved`;
  if (!state.subscriptions.length) {
    root.innerHTML = `<div class="detail-view empty">No saved searches yet.</div>`;
    return;
  }
  root.innerHTML = state.subscriptions.map((item) => `
    <div class="mini-card">
      <h4>${item.label}</h4>
      <p>${item.query}</p>
      <div class="meta">
        <span class="chip">${item.mode}</span>
        <span class="chip">${item.active ? "active" : "paused"}</span>
        <span class="chip">${item.notification_destinations?.discord_configured ? `discord:${item.notification_destinations.discord_audience_type || "human"}` : "no discord"}</span>
        <span class="chip">${item.notification_destinations?.slack_configured ? `slack:${item.notification_destinations.slack_audience_type || "human"}` : "no slack"}</span>
        <span class="chip">${item.notification_destinations?.sms_phone_number ? `${item.notification_destinations.sms_phone_number} (${item.notification_destinations.sms_audience_type || "human"})` : "no sms"}</span>
        <span class="chip">${(item.notification_destinations?.slack_event_types || item.notification_destinations?.discord_event_types || item.notification_destinations?.sms_event_types || []).length ? "filtered events" : "all events"}</span>
      </div>
      <div class="actions">
        <button data-sub-run="${item.subscription_id}">Run</button>
      </div>
    </div>
  `).join("");

  root.querySelectorAll("[data-sub-run]").forEach((button) => {
    button.addEventListener("click", async () => {
      const subscriptionId = button.dataset.subRun;
      const run = await fetch(`/v1/subscriptions/${subscriptionId}/run`, { method: "POST" }).then((res) => res.json());
      state.activeRunId = run.run_id;
      qs("run-status").textContent = `${run.status} • ${run.run_id}`;
      connectRunStream(run.run_id);
    });
  });
}

async function loadSubscriptions() {
  const data = await api("/v1/subscriptions");
  state.subscriptions = data.subscriptions || [];
  renderSubscriptions();
}

function selectedDestinationIds() {
  return [
    qs("discord-destination-select").value,
    qs("slack-destination-select").value,
    qs("sms-destination-select").value,
  ].filter(Boolean);
}

function fillDestinationSelect(selectId, channel) {
  const select = qs(selectId);
  const current = select.value;
  const options = state.destinations
    .filter((item) => item.channel === channel)
    .map((item) => `<option value="${item.destination_id}">${item.label}</option>`)
    .join("");
  select.innerHTML = `<option value="">None</option>${options}`;
  if ([...select.options].some((opt) => opt.value === current)) {
    select.value = current;
  }
}

function renderDestinations() {
  qs("destination-count").textContent = `${state.destinations.length} saved`;
  fillDestinationSelect("discord-destination-select", "discord");
  fillDestinationSelect("slack-destination-select", "slack");
  fillDestinationSelect("sms-destination-select", "sms");

  const root = qs("destination-list");
  if (!state.destinations.length) {
    root.innerHTML = `<div class="detail-view empty">No reusable destinations yet.</div>`;
    return;
  }
  root.innerHTML = state.destinations.map((item) => `
    <div class="mini-card">
      <h4>${item.label}</h4>
      <p>${item.channel}</p>
      <div class="meta">
        <span class="chip">${item.active ? "active" : "paused"}</span>
        <span class="chip">${item.audience_type || "human"}</span>
        <span class="chip">${(item.event_types || []).length ? item.event_types.join(", ") : "all events"}</span>
        ${item.details?.configured ? '<span class="chip">configured</span>' : ''}
        ${item.details?.phone_number ? `<span class="chip">${item.details.phone_number}</span>` : ''}
      </div>
      <div class="actions">
        <button data-dest-use="${item.destination_id}" data-dest-channel="${item.channel}">Use</button>
      </div>
    </div>
  `).join("");

  root.querySelectorAll("[data-dest-use]").forEach((button) => {
    button.addEventListener("click", () => {
      const destinationId = button.dataset.destUse;
      const channel = button.dataset.destChannel;
      const selectId = {
        discord: "discord-destination-select",
        slack: "slack-destination-select",
        sms: "sms-destination-select",
      }[channel];
      if (selectId) {
        qs(selectId).value = destinationId;
        renderNotificationCenter();
      }
    });
  });
}

async function loadDestinations() {
  const data = await api("/v1/notification-destinations");
  state.destinations = data.destinations || [];
  renderDestinations();
  renderNotificationCenter();
}

function destinationForSelected(channel) {
  const selectId = {
    discord: "discord-destination-select",
    slack: "slack-destination-select",
    sms: "sms-destination-select",
  }[channel];
  const destinationId = selectId ? qs(selectId).value : "";
  return state.destinations.find((item) => item.destination_id === destinationId) || null;
}

function notificationPreviewText() {
  const query = qs("search-query").value.trim() || "your current query";
  const enabled = [
    qs("notify-discord").checked ? "Discord" : null,
    qs("notify-slack").checked ? "Slack" : null,
    qs("notify-sms").checked ? "SMS" : null,
  ].filter(Boolean);
  if (!enabled.length) {
    return "Notifications are currently off. Enable one or more channels to preview delivery.";
  }
  const lines = [
    `Foxhound is working on your request for “${query}.”`,
    "",
    "We’re gathering and ranking the strongest opportunities now.",
    "",
    `Enabled channels: ${enabled.join(", ")}`,
  ];
  const selected = selectedDestinationIds();
  if (selected.length) {
    lines.push(`Saved destinations attached: ${selected.length}`);
  }
  return lines.join("\n");
}

function renderDestinationPreview() {
  const root = qs("destination-preview");
  const cards = ["discord", "slack", "sms"].map((channel) => {
    const destination = destinationForSelected(channel);
    const enabled = qs(`notify-${channel}`).checked;
    const direct = {
      discord: qs("discord-webhook-url").value.trim(),
      slack: qs("slack-webhook-url").value.trim(),
      sms: qs("sms-phone-number").value.trim(),
    }[channel];
    const audience = {
      discord: qs("discord-audience-type").value,
      slack: qs("slack-audience-type").value,
      sms: qs("sms-audience-type").value,
    }[channel];
    const label = destination ? destination.label : (direct ? "Direct destination" : "No destination selected");
    const eventText = destination && destination.event_types?.length ? destination.event_types.join(", ") : "all events";
    return `
      <div class="mini-card">
        <h4>${channel}</h4>
        <div class="meta">
          <span class="chip">${enabled ? "enabled" : "disabled"}</span>
          <span class="chip">${destination?.audience_type || audience}</span>
          <span class="chip">${eventText}</span>
        </div>
        <p>${label}</p>
      </div>
    `;
  });
  root.innerHTML = cards.join("");
}

function renderNotificationHistory() {
  const root = qs("notification-history");
  qs("notification-history-count").textContent = `${state.notifications.length} recent`;
  if (!state.notifications.length) {
    root.innerHTML = `<div class="detail-view empty">No notification deliveries recorded yet.</div>`;
    return;
  }
  root.innerHTML = state.notifications.map((item) => `
    <div class="mini-card history-line">
      <div class="meta">
        <span class="chip ${item.status}">${item.status}</span>
        <span class="chip">${item.channel}</span>
        <span class="chip">${item.source_event}</span>
        <span class="chip">Attempt ${item.attempt_number || 1}</span>
      </div>
      <div>${item.message || "No message"}</div>
      <time>${item.created_at || ""}</time>
    </div>
  `).join("");
}

function renderNotificationCenter() {
  const preview = qs("notification-preview");
  preview.classList.toggle("empty", false);
  preview.textContent = notificationPreviewText();
  renderDestinationPreview();
  renderNotificationHistory();
}

async function loadNotifications() {
  const data = await api("/v1/notifications");
  state.notifications = data.deliveries || [];
  renderNotificationHistory();
}

function appendStream(text) {
  const root = qs("run-stream");
  root.classList.remove("empty");
  root.textContent += `${text}\n`;
  root.scrollTop = root.scrollHeight;
}

function closeStream() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
}

function connectRunStream(runId) {
  closeStream();
  const source = new EventSource(`/v1/runs/${runId}/stream`);
  state.eventSource = source;
  [
    "run.created",
    "run.started",
    "run.routing.completed",
    "worker.started",
    "worker.completed",
    "worker.failed",
    "resources.discovered",
    "resources.selected",
    "extraction.completed",
    "opportunity.created",
    "build_plan.created",
    "report.section.completed",
    "notification.sent",
    "notification.failed",
    "notification.skipped",
    "run.completed",
    "run.failed",
    "run.canceled",
  ].forEach((name) => {
    source.addEventListener(name, (event) => appendStream(`${name} ${event.data}`));
  });
  source.addEventListener("run.completed", async (event) => {
    appendStream(event.data);
    qs("run-status").textContent = `completed • ${runId}`;
    closeStream();
    await loadDispatch();
    await loadMarketplace();
    await loadStats();
    await loadSubscriptions();
    await loadNotifications();
  });
  source.addEventListener("run.failed", (event) => {
    appendStream(event.data);
    qs("run-status").textContent = `failed • ${runId}`;
    closeStream();
  });
  source.onerror = () => {
    appendStream("stream.error");
  };
}

function currentNotificationDestinations() {
  return {
    discord_webhook_url: qs("discord-webhook-url").value.trim(),
    slack_webhook_url: qs("slack-webhook-url").value.trim(),
    sms_phone_number: qs("sms-phone-number").value.trim(),
    discord_audience_type: qs("discord-audience-type").value,
    slack_audience_type: qs("slack-audience-type").value,
    sms_audience_type: qs("sms-audience-type").value,
  };
}

async function startRun() {
  const query = qs("search-query").value.trim();
  if (!query) return;
  closeStream();
  qs("run-stream").textContent = "";
  qs("run-status").textContent = "Creating run...";

  const response = await fetch("/v1/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      mode: qs("search-mode").value,
      origin: "interactive",
      priority: 95,
      notify: {
        discord: qs("notify-discord").checked,
        slack: qs("notify-slack").checked,
        sms: qs("notify-sms").checked,
      },
      notification_destination_ids: selectedDestinationIds(),
      notification_destinations: currentNotificationDestinations(),
    }),
  });
  const run = await response.json();
  state.activeRunId = run.run_id;
  qs("run-status").textContent = `${run.status} • ${run.run_id}`;
  appendStream(`run.created ${run.run_id}`);
  connectRunStream(run.run_id);
}

async function saveSearch() {
  const query = qs("search-query").value.trim();
  if (!query) return;
  await fetch("/v1/subscriptions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      label: query,
      mode: qs("search-mode").value,
      notify: {
        discord: qs("notify-discord").checked,
        slack: qs("notify-slack").checked,
        sms: qs("notify-sms").checked,
      },
      notification_destination_ids: selectedDestinationIds(),
      notification_destinations: currentNotificationDestinations(),
      active: true,
    }),
  });
  await loadSubscriptions();
}

async function saveDestination() {
  const label = qs("destination-label").value.trim();
  const value = qs("destination-value").value.trim();
  if (!label || !value) return;
  const eventTypes = qs("destination-event-types").value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  await fetch("/v1/notification-destinations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      label,
      channel: qs("destination-channel").value,
      audience_type: qs("destination-audience-type").value,
      event_types: eventTypes,
      value,
      active: true,
    }),
  });
  qs("destination-label").value = "";
  qs("destination-value").value = "";
  qs("destination-event-types").value = "";
  await loadDestinations();
  renderNotificationCenter();
}

function bindControls() {
  qs("apply-filters").addEventListener("click", loadMarketplace);
  qs("reset-filters").addEventListener("click", async () => {
    qs("filter-vertical").value = "";
    qs("filter-confidence").value = "";
    qs("filter-execution").value = "";
    qs("filter-listing").value = "";
    await loadMarketplace();
  });
  qs("start-run").addEventListener("click", startRun);
  qs("save-search").addEventListener("click", saveSearch);
  qs("save-destination").addEventListener("click", saveDestination);
  [
    "search-query",
    "notify-discord",
    "notify-slack",
    "notify-sms",
    "discord-destination-select",
    "slack-destination-select",
    "sms-destination-select",
    "discord-webhook-url",
    "slack-webhook-url",
    "sms-phone-number",
    "discord-audience-type",
    "slack-audience-type",
    "sms-audience-type",
  ].forEach((id) => {
    qs(id).addEventListener("input", renderNotificationCenter);
    qs(id).addEventListener("change", renderNotificationCenter);
  });
}

async function init() {
  bindControls();
  initDispatch();
  await loadStats();
  await loadMarketplace();
  await loadSubscriptions();
  await loadDestinations();
  await loadNotifications();
  renderNotificationCenter();
}

init().catch((error) => {
  console.error(error);
  qs("marketplace-list").innerHTML = `<div class="detail-view empty">Failed to load UI data: ${error.message}</div>`;
});
