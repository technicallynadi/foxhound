"use client";

import { useState } from "react";
import {
  Cpu,
  ScanSearch,
  Bell,
  KeyRound,
  Shield,
  BookOpen,
  ChevronDown,
  EyeOff,
  Smartphone,
  Compass,
  X,
  Globe,
  Plus,
  Link as LinkIcon,
} from "lucide-react";
import TopBar from "@/components/top-bar";
import GlassCard from "@/components/ui/glass-card";
import GlassButton from "@/components/ui/glass-button";
import { useSettings } from "@/lib/use-settings";

type Section =
  | "model-tiers"
  | "topics-sources"
  | "notifications"
  | "api-keys"
  | "policies"
  | "recipes";

const NAV_ITEMS: { key: Section; label: string; icon: React.ReactNode }[] = [
  { key: "model-tiers", label: "Model Tiers", icon: <Cpu className="w-4 h-4" /> },
  { key: "topics-sources", label: "Topics & Sources", icon: <Compass className="w-4 h-4" /> },
  { key: "notifications", label: "Notifications", icon: <Bell className="w-4 h-4" /> },
  { key: "api-keys", label: "API Keys", icon: <KeyRound className="w-4 h-4" /> },
  { key: "policies", label: "Policies", icon: <Shield className="w-4 h-4" /> },
  { key: "recipes", label: "Recipes", icon: <BookOpen className="w-4 h-4" /> },
];

const MODEL_OPTIONS = [
  "claude-opus-4-6",
  "claude-sonnet-4-6",
  "claude-haiku-4-5",
];

const TIER_COLORS: Record<string, string> = {
  reasoning: "bg-accent-red",
  balanced: "bg-accent-purple",
  fast: "bg-accent-green",
};

export default function SettingsPage() {
  const [activeSection, setActiveSection] = useState<Section>("model-tiers");
  const { settings, updateSettings } = useSettings();
  const [newTopic, setNewTopic] = useState("");
  const [newSource, setNewSource] = useState("");

  function addTopic() {
    if (!newTopic.trim()) return;
    updateSettings({ topics: [...settings.topics, newTopic.trim()] });
    setNewTopic("");
  }

  function removeTopic(index: number) {
    updateSettings({ topics: settings.topics.filter((_, i) => i !== index) });
  }

  function addSource() {
    if (!newSource.trim()) return;
    updateSettings({
      customSources: [
        ...settings.customSources,
        { url: newSource.trim(), status: "pending" },
      ],
    });
    setNewSource("");
  }

  return (
    <div className="min-h-screen">
      <TopBar activeTab="settings" />

      <div className="flex min-h-[calc(100vh-52px)]">
        <aside className="w-60 shrink-0 glass-panel backdrop-blur-xl border-r border-glass-border p-5">
          <p className="text-xs font-semibold text-text-muted tracking-wider mb-3">
            CONFIGURATION
          </p>
          <nav className="space-y-1">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.key}
                onClick={() => setActiveSection(item.key)}
                className={`flex items-center gap-2.5 w-full px-3 py-2.5 rounded-lg text-[13px] transition-colors ${
                  activeSection === item.key
                    ? "bg-accent-purple/[0.12] text-text-primary font-medium"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                <span
                  className={
                    activeSection === item.key
                      ? "text-accent-purple"
                      : "text-text-muted"
                  }
                >
                  {item.icon}
                </span>
                {item.label}
              </button>
            ))}
          </nav>
        </aside>

        <main className="flex-1 p-8 lg:p-10 max-w-4xl">
          {activeSection === "model-tiers" && (
            <div className="space-y-7">
              <div>
                <h1 className="text-[22px] font-bold text-text-primary">
                  Model Tiers
                </h1>
                <p className="text-sm text-text-secondary mt-1">
                  Map capability tiers to specific models. Foxhound uses tiers,
                  never model names directly.
                </p>
              </div>

              <GlassCard padding="p-6">
                <h3 className="text-sm font-semibold text-text-primary mb-4">
                  Provider
                </h3>
                <div className="flex items-center justify-between px-4 py-3 rounded-lg bg-[rgba(255,255,255,0.02)] border border-glass-border">
                  <span className="text-sm font-medium text-text-primary">
                    Anthropic
                  </span>
                  <ChevronDown className="w-4 h-4 text-text-muted" />
                </div>

                <div className="h-px bg-glass-border my-5" />

                <div className="space-y-3.5">
                  {(["reasoning", "balanced", "fast"] as const).map((tier) => (
                    <div
                      key={tier}
                      className="flex items-center gap-4"
                    >
                      <div className="flex items-center gap-2 w-36">
                        <div
                          className={`w-2 h-2 rounded-full ${TIER_COLORS[tier]}`}
                        />
                        <span className="font-mono text-[13px] font-medium text-text-primary">
                          {tier}
                        </span>
                      </div>
                      <div className="flex-1 flex items-center justify-between px-3.5 py-2.5 rounded-lg bg-[rgba(255,255,255,0.02)] border border-glass-border">
                        <span className="font-mono text-[13px] text-text-secondary">
                          {settings.modelTiers[tier]}
                        </span>
                        <ChevronDown className="w-3.5 h-3.5 text-text-muted" />
                      </div>
                    </div>
                  ))}
                </div>
              </GlassCard>

              <GlassCard padding="p-6">
                <h3 className="text-sm font-semibold text-text-primary mb-4">
                  API Key
                </h3>
                <div className="flex items-center gap-3 mb-4">
                  <span className="text-[13px] text-text-secondary">
                    Environment variable:
                  </span>
                  <span className="font-mono text-[13px] font-medium text-accent-purple">
                    {settings.apiKeyEnv}
                  </span>
                </div>
                <div className="flex items-center justify-between px-4 py-3 rounded-lg bg-[rgba(255,255,255,0.02)] border border-glass-border">
                  <span className="font-mono text-[13px] text-text-muted">
                    sk-ant-••••••••••••••••••••3kfQ
                  </span>
                  <EyeOff className="w-4 h-4 text-text-muted" />
                </div>
              </GlassCard>

              <GlassCard padding="p-6">
                <h3 className="text-sm font-semibold text-text-primary mb-2">
                  SMS Alerts
                </h3>
                <p className="text-[13px] text-text-muted mb-4">
                  Receive SMS for critical events: high-confidence opportunities
                  (score &gt;33/35) and critical build failures.
                </p>
                <div className="flex items-center gap-2.5 px-4 py-3 rounded-lg bg-[rgba(255,255,255,0.02)] border border-glass-border mb-4">
                  <Smartphone className="w-4 h-4 text-text-muted" />
                  <span className="text-sm text-text-primary">
                    {settings.notifications.phone}
                  </span>
                </div>
                <div className="flex items-center gap-2.5">
                  <button
                    onClick={() =>
                      updateSettings({
                        notifications: {
                          ...settings.notifications,
                          sms: !settings.notifications.sms,
                        },
                      })
                    }
                    className={`w-10 h-[22px] rounded-full relative transition-colors ${
                      settings.notifications.sms
                        ? "bg-accent-purple"
                        : "bg-border-subtle"
                    }`}
                  >
                    <div
                      className={`absolute top-0.5 w-[18px] h-[18px] rounded-full bg-white transition-transform ${
                        settings.notifications.sms
                          ? "translate-x-5"
                          : "translate-x-0.5"
                      }`}
                    />
                  </button>
                  <span className="text-[13px] text-text-secondary">
                    SMS alerts enabled
                  </span>
                </div>
              </GlassCard>

              <GlassCard padding="p-6">
                <h3 className="text-sm font-semibold text-text-primary mb-2">
                  Scout Confidence Threshold
                </h3>
                <p className="text-[13px] text-text-muted mb-4">
                  Minimum confidence score (out of 35) for opportunities to
                  appear as suggested.
                </p>
                <div className="flex items-center gap-4">
                  <div className="flex-1 h-2 rounded-full bg-[rgba(255,255,255,0.06)] overflow-hidden">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-accent-purple to-accent-blue"
                      style={{
                        width: `${(settings.scoutConfig.confidenceThreshold / 35) * 100}%`,
                      }}
                    />
                  </div>
                  <span className="font-mono text-base font-semibold text-accent-purple">
                    {settings.scoutConfig.confidenceThreshold}
                  </span>
                </div>
              </GlassCard>

              <GlassButton className="w-auto">Save Configuration</GlassButton>
            </div>
          )}

          {activeSection === "topics-sources" && (
            <div className="space-y-7">
              <div>
                <h1 className="text-[22px] font-bold text-text-primary">
                  Topics & Sources
                </h1>
                <p className="text-sm text-text-secondary mt-1">
                  Configure the topics Foxhound scouts for and add custom
                  sources to scan.
                </p>
              </div>

              <GlassCard padding="p-6">
                <h3 className="text-sm font-semibold text-text-primary mb-2">
                  Scout Topics
                </h3>
                <p className="text-[13px] text-text-muted mb-4">
                  Topics are matched against signals from all connectors.
                  Foxhound scores relevance as one of the 6 scoring dimensions.
                </p>
                <div className="flex flex-wrap gap-2 mb-4">
                  {settings.topics.map((topic, i) => (
                    <span
                      key={i}
                      className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-medium text-accent-purple bg-accent-purple/[0.12] border border-accent-purple/20"
                    >
                      {topic}
                      <button onClick={() => removeTopic(i)}>
                        <X className="w-3 h-3" />
                      </button>
                    </span>
                  ))}
                </div>
                <div className="flex items-center gap-2.5">
                  <div className="flex-1 flex items-center gap-2 px-3.5 py-2.5 rounded-lg bg-[rgba(255,255,255,0.02)] border border-glass-border">
                    <Plus className="w-4 h-4 text-text-muted" />
                    <input
                      type="text"
                      value={newTopic}
                      onChange={(e) => setNewTopic(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && addTopic()}
                      placeholder="Add a topic..."
                      className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-muted outline-none"
                    />
                  </div>
                  <GlassButton onClick={addTopic}>Add</GlassButton>
                </div>
              </GlassCard>

              <GlassCard padding="p-6">
                <h3 className="text-sm font-semibold text-text-primary mb-2">
                  Custom Sources to Scan
                </h3>
                <p className="text-[13px] text-text-muted mb-4">
                  Add URLs or subreddits for Foxhound to include in scout scans.
                  These are added as custom RSS or scraping targets.
                </p>
                <div className="space-y-3 mb-4">
                  {settings.customSources.map((src, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between"
                    >
                      <div className="flex items-center gap-2">
                        <Globe className="w-4 h-4 text-text-muted" />
                        <span className="font-mono text-[13px] text-text-secondary">
                          {src.url}
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`w-1.5 h-1.5 rounded-full ${
                            src.status === "active"
                              ? "bg-accent-green"
                              : "bg-tier-workaround"
                          }`}
                        />
                        <span
                          className={`text-xs font-medium ${
                            src.status === "active"
                              ? "text-accent-green"
                              : "text-tier-workaround"
                          }`}
                        >
                          {src.status === "active" ? "Active" : "Pending"}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="h-px bg-glass-border mb-4" />
                <div className="flex items-center gap-2.5">
                  <div className="flex-1 flex items-center gap-2 px-3.5 py-2.5 rounded-lg bg-[rgba(255,255,255,0.02)] border border-glass-border">
                    <LinkIcon className="w-4 h-4 text-text-muted" />
                    <input
                      type="text"
                      value={newSource}
                      onChange={(e) => setNewSource(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && addSource()}
                      placeholder="https://reddit.com/r/..."
                      className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-muted outline-none"
                    />
                  </div>
                  <GlassButton onClick={addSource}>Add Source</GlassButton>
                </div>
              </GlassCard>
            </div>
          )}

          {activeSection === "notifications" && (
            <div className="space-y-7">
              <div>
                <h1 className="text-[22px] font-bold text-text-primary">
                  Notifications
                </h1>
                <p className="text-sm text-text-secondary mt-1">
                  Configure how Foxhound notifies you about opportunities and
                  build events.
                </p>
              </div>
              <GlassCard padding="p-6">
                <p className="text-sm text-text-muted">
                  Configure notification channels via foxhound.yaml or the CLI:
                  Desktop, Slack, Discord, Email, SMS.
                </p>
              </GlassCard>
            </div>
          )}

          {(activeSection === "api-keys" ||
            activeSection === "policies" ||
            activeSection === "recipes") && (
            <div className="space-y-7">
              <div>
                <h1 className="text-[22px] font-bold text-text-primary capitalize">
                  {activeSection.replace("-", " ")}
                </h1>
                <p className="text-sm text-text-secondary mt-1">
                  Configure via .foxhound/{activeSection.replace("-", "")}/
                  directory or foxhound.yaml.
                </p>
              </div>
              <GlassCard padding="p-6">
                <p className="text-sm text-text-muted">
                  This section is managed through configuration files. Use{" "}
                  <code className="font-mono text-accent-purple">
                    foxhound doctor
                  </code>{" "}
                  to validate your setup.
                </p>
              </GlassCard>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
