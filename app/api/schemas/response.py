from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    type: str
    text: str


class MarketplaceEvidenceItem(BaseModel):
    type: str = ""
    evidence_class: str | None = None
    text: str = ""
    excerpt: str | None = None
    source_title: str | None = None
    source_url: str | None = None
    source_domain: str | None = None
    source_type: str | None = None
    observed_at: str | None = None


class OpportunityNarrative(BaseModel):
    summary: str = ""
    problem_statement: str = ""
    what_it_does: str = ""
    current_behavior: str = ""
    why_now: str = ""
    why_this_wins: str = ""


class OpportunityScoring(BaseModel):
    opportunity_score: float = 0.0
    evidence_strength: float = 0.0
    demand_strength: float = 0.0
    confidence_score: float = 0.0
    freshness_score: float = 0.0
    build_readiness_score: float = 0.0
    quality_score: float = 0.0
    source_diversity_score: float = 0.0
    source_diversity_count: int = 0


class OpportunityLabels(BaseModel):
    evidence_strength_label: str = ""
    demand_strength_label: str = ""
    confidence_label: str = ""
    freshness_label: str = ""
    build_readiness_label: str = ""


class AgentGuidance(BaseModel):
    first_task: str = ""
    priority_order: list[str] = []
    safe_shortcuts: list[str] = []
    danger_zones: list[str] = []


class HumanGuidance(BaseModel):
    effort_estimate: str = ""
    core_skills_needed: list[str] = []
    best_starting_point: str = ""


class ImplementationGuidance(BaseModel):
    why_this_is_buildable: str = ""
    recommended_build_order: list[str] = []
    technical_risks: list[str] = []
    product_risks: list[str] = []
    stub_first: list[str] = []
    mvp_boundary: list[str] = []
    definition_of_done: list[str] = []
    agent_guidance: AgentGuidance = AgentGuidance()
    human_guidance: HumanGuidance = HumanGuidance()


class OpportunityResult(BaseModel):
    title: str
    opportunity_score: float
    confidence: str
    workflow: str
    breakpoint: str | None = None
    summary: str | None = None
    persona: list[str]
    pain_types: list[str]
    current_solutions: list[str]
    gap: str
    build_wedge: str
    mvp_plan: list[str]
    evidence: list[EvidenceItem]
    opportunity_evidence: dict = {}
    execution_evidence: dict = {}
    implementation_guidance: ImplementationGuidance | None = None


class OpportunitySearchResponse(BaseModel):
    query: str
    generated_at: str
    results: list[OpportunityResult]
    debug: dict | None = None


class MarketplaceOpportunityResponse(BaseModel):
    opportunity_id: str
    title: str
    vertical: str | None = None
    workflow: str
    broken_step: str | None = None
    personas: list[str] = []
    wedge: str
    summary: str | None = None
    confidence: str
    opportunity_score: float
    freshness_score: float
    execution_ready_score: float
    evidence_count: int
    source_diversity_count: int
    evidence_summary: dict = {}
    opportunity_evidence: dict = {}
    execution_evidence: dict = {}
    current_solutions: list[str] = []
    listing_status: str
    curation_status: str
    execution_artifact_id: str | None = None
    listed_at: str | None = None
    last_validated_at: str | None = None
    narrative: OpportunityNarrative = Field(default_factory=OpportunityNarrative)
    evidence_items: list[MarketplaceEvidenceItem] = Field(default_factory=list)
    scoring: OpportunityScoring = Field(default_factory=OpportunityScoring)
    labels: OpportunityLabels = Field(default_factory=OpportunityLabels)
    payload: dict = {}
    # V2 pipeline fields
    effort_tier: str | None = None
    form_factor: str | None = None
    one_liner: str | None = None
    who_feels_this: str | None = None
    signal_strength: str | None = None
    evidence_headline: str | None = None
    what_teams_do_today: str | None = None
    why_now: str | None = None
    primary_tool: str | None = None
    breakpoint_theme: str | None = None
    source_diversity: list[str] = []
    pipeline_version: str | None = None


class MarketplaceListResponse(BaseModel):
    opportunities: list[MarketplaceOpportunityResponse]


class MarketplaceStatsResponse(BaseModel):
    total: int
    by_listing_status: dict = {}
    by_vertical: dict = {}


class HealthResponse(BaseModel):
    status: str
    version: str
    queue: dict | None = None


class RunStep(BaseModel):
    step: str
    status: str
    timestamp: str | None = None
    message: str | None = None


class WorkerState(BaseModel):
    worker: str
    status: str
    discovered_count: int = 0
    selected_count: int = 0
    message: str | None = None


class BuildPlanResponse(BaseModel):
    plan_id: str
    artifact_id: str | None = None
    opportunity_id: str | None = None
    plan_type: str = "wedge_mvp"
    title: str = ""
    opportunity_title: str | None = None
    form_factor: str = "web_app"
    wedge: str | None = None
    workflow: str | None = None
    target_personas: list[str] = []
    mvp_scope: list[str] = []
    build_order: list[str] = []
    risks: list[str] = []
    estimated_effort: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ExecutionArtifactResponse(BaseModel):
    artifact_id: str
    opportunity_id: str
    artifact_version: int = 1
    title: str
    workflow: str
    wedge: str
    broken_step: str | None = None
    form_factor: str = "web_app"
    wedge_mvp: dict = {}
    expanded_build: dict = {}
    product_definition: dict = {}
    system_design: dict = {}
    data_model: dict = {}
    api_contracts: dict = {}
    ui_flows: dict = {}
    implementation_guidance: dict = {}
    constraints: dict = {}
    execution_evidence: dict = {}
    created_at: str | None = None
    updated_at: str | None = None


class ReportSectionResponse(BaseModel):
    section_id: str
    title: str
    status: str
    content: dict = {}


class RunOutputResponse(BaseModel):
    query: str
    generated_at: str | None = None
    opportunities: list[OpportunityResult] = []
    build_plans: list[BuildPlanResponse] = []
    report_sections: list[ReportSectionResponse] = []


class RunEventResponse(BaseModel):
    event_id: str
    event_type: str
    timestamp: str
    run_id: str
    payload: dict = {}


class RunNotificationChannelResponse(BaseModel):
    enabled: bool = False
    status: str = "disabled"
    message: str | None = None
    http_status: int | None = None


class RunNotificationStateResponse(BaseModel):
    discord: RunNotificationChannelResponse = RunNotificationChannelResponse()
    slack: RunNotificationChannelResponse = RunNotificationChannelResponse()
    sms: RunNotificationChannelResponse = RunNotificationChannelResponse()


class RunStatusResponse(BaseModel):
    run_id: str
    query: str
    mode: str
    status: str
    progress_percent: int
    current_step: str
    steps: list[RunStep]
    workers: list[WorkerState]
    resource_counts: dict
    notify: dict = {}
    notification_destination_ids: list[str] = []
    notification_destinations: dict = {}
    notification_status: RunNotificationStateResponse = RunNotificationStateResponse()
    output: RunOutputResponse | None = None
    events: list[RunEventResponse] = []
    result: dict | None = None
    error_message: str | None = None


class ResourceCandidateResponse(BaseModel):
    resource_id: str
    url: str
    source_class: str
    evidence_class: str | None = None
    page_type: str
    discovered_by: str
    confidence: float
    priority: float
    status: str
    discovery_reason: str | None = None
    routing_tags: list[str] = []
    provenance: dict = {}


class RunResourcesResponse(BaseModel):
    run_id: str
    resources: list[ResourceCandidateResponse]


class RunEventsResponse(BaseModel):
    run_id: str
    events: list[RunEventResponse]


class JobStatusResponse(BaseModel):
    job_id: str
    run_id: str
    job_type: str
    origin: str
    priority: int
    status: str
    attempts: int
    max_attempts: int
    queued_duration_ms: float | None = None
    run_duration_ms: float | None = None
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    canceled_at: str | None = None


class JobListResponse(BaseModel):
    jobs: list[JobStatusResponse]


class QueueHealthResponse(BaseModel):
    total_jobs: int
    queued_jobs: int
    running_jobs: int
    completed_jobs: int
    failed_jobs: int
    stale_jobs: int
    average_queue_duration_ms: float | None = None
    average_run_duration_ms: float | None = None
    oldest_queued_at: str | None = None


class SavedSearchSubscriptionResponse(BaseModel):
    subscription_id: str
    label: str
    query: str
    mode: str
    active: bool
    notify: dict = {}
    notification_destination_ids: list[str] = []
    notification_destinations: dict = {}
    last_run_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class SavedSearchSubscriptionListResponse(BaseModel):
    subscriptions: list[SavedSearchSubscriptionResponse]
