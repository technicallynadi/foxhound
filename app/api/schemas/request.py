from pydantic import BaseModel, Field


class SearchFilters(BaseModel):
    sources: list[str] = Field(default=["reddit", "github"])
    min_opportunity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    limit: int = Field(default=5, ge=1, le=20)


class DiscoveryConfig(BaseModel):
    enabled: bool = Field(default=False)
    max_seeds: int = Field(default=3, ge=1, le=10)
    max_discovered_urls: int = Field(default=10, ge=1, le=30)
    max_extractions: int = Field(default=5, ge=1, le=15)
    budget_limit: int = Field(default=10, ge=1, le=20)
    enable_web_search: bool = Field(default=True)


class OpportunitySearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    review_urls: list[str] = Field(default_factory=list)
    discussion_urls: list[str] = Field(default_factory=list)
    debug: bool = Field(default=False)
    premium: bool = Field(default=False)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)


class RunNotificationConfig(BaseModel):
    discord: bool = Field(default=False)
    slack: bool = Field(default=False)
    sms: bool = Field(default=False)


class NotificationDestinationsConfig(BaseModel):
    discord_webhook_url: str = Field(default="", max_length=500)
    slack_webhook_url: str = Field(default="", max_length=500)
    sms_phone_number: str = Field(default="", max_length=50)
    discord_audience_type: str = Field(default="human", pattern="^(human|agent|hybrid)$")
    slack_audience_type: str = Field(default="human", pattern="^(human|agent|hybrid)$")
    sms_audience_type: str = Field(default="human", pattern="^(human|agent|hybrid)$")
    discord_event_types: list[str] = Field(default_factory=list)
    slack_event_types: list[str] = Field(default_factory=list)
    sms_event_types: list[str] = Field(default_factory=list)


class RunCreateRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    mode: str = Field(default="pipeline_run", pattern="^(pipeline_run|discovery_only|quick_scan)$")
    premium: bool = Field(default=False)
    origin: str = Field(default="interactive")
    priority: int = Field(default=50, ge=0, le=100)
    notify: RunNotificationConfig = Field(default_factory=RunNotificationConfig)
    notification_destination_ids: list[str] = Field(default_factory=list)
    notification_destinations: NotificationDestinationsConfig = Field(default_factory=NotificationDestinationsConfig)
    discovery: DiscoveryConfig = Field(default_factory=lambda: DiscoveryConfig(enabled=True))


class SavedSearchSubscriptionCreateRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=120)
    mode: str = Field(default="pipeline_run", pattern="^(pipeline_run|discovery_only|quick_scan)$")
    notify: RunNotificationConfig = Field(default_factory=RunNotificationConfig)
    notification_destination_ids: list[str] = Field(default_factory=list)
    notification_destinations: NotificationDestinationsConfig = Field(default_factory=NotificationDestinationsConfig)
    active: bool = Field(default=True)
