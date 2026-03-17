"use client";

import { Link as LinkIcon, MapPin, Cpu, ArrowRight } from "lucide-react";
import Link from "next/link";
import type { Opportunity } from "@/lib/api";
import { getTierConfig } from "@/lib/shared";

interface OpportunityCardProps {
  opportunity: Opportunity;
  onApprove?: () => void;
  onDismiss?: () => void;
  compact?: boolean;
}

export default function OpportunityCard({
  opportunity,
  onApprove,
  onDismiss,
  compact = false,
}: OpportunityCardProps) {
  const tier = getTierConfig(opportunity.signal_tier);

  return (
    <div
      className={`animate-fade-in-up glass-panel backdrop-blur-xl border border-glass-border rounded-xl overflow-hidden flex flex-col transition-transform duration-200 hover:scale-[1.01] ${
        compact ? "p-4" : "p-5"
      }`}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={`px-2.5 py-0.5 rounded text-xs font-medium ${tier.color} ${tier.bg}`}>
            {tier.label}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-xs text-text-muted">Confidence:</span>
          <span className="text-lg font-bold text-accent-purple">
            {Math.round(opportunity.opportunity_score)}
          </span>
          <span className="text-sm text-text-muted">/35</span>
        </div>
      </div>

      <Link href={`/inbox/${opportunity.opportunity_id}`}>
        <h3 className={`font-semibold text-text-primary hover:text-accent-purple transition-colors line-clamp-2 ${
          compact ? "text-base mb-1.5" : "text-lg mb-2"
        }`}>
          {opportunity.title}
        </h3>
      </Link>

      <p className={`text-text-secondary leading-relaxed ${
        compact ? "text-xs line-clamp-2 mb-3" : "text-sm line-clamp-3 mb-3"
      }`}>
        {opportunity.enrichment_summary || opportunity.description}
      </p>

      {!compact && (
        <div className="flex flex-wrap items-center gap-3 text-xs text-text-muted mb-4">
          {opportunity.source_url && (
            <a
              href={opportunity.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-accent-purple hover:underline"
            >
              <LinkIcon className="w-3 h-3" />
              {opportunity.source_type}
            </a>
          )}
          <span className="flex items-center gap-1">
            <MapPin className="w-3 h-3" />
            {opportunity.matched_topic}
          </span>
          {opportunity.ai_exposure_score > 0 && (
            <span className="flex items-center gap-1">
              <Cpu className="w-3 h-3" />
              AI: {Math.round(opportunity.ai_exposure_score)}/10
            </span>
          )}
        </div>
      )}

      {(onApprove || onDismiss) && (
        <>
          <div className="border-t border-glass-border mb-3" />
          <div className="flex items-center justify-between">
            {onDismiss ? (
              <button
                onClick={onDismiss}
                className="px-4 py-2 text-sm text-text-muted border border-glass-border rounded-lg hover:border-glass-border-strong transition-colors"
              >
                Reject
              </button>
            ) : (
              <div />
            )}
            {onApprove && (
              <button
                onClick={onApprove}
                className="flex items-center gap-1.5 px-5 py-2 bg-gradient-to-r from-accent-purple to-accent-purple-dim text-white font-medium text-sm rounded-lg hover:opacity-90 transition-opacity"
              >
                Approve
                <ArrowRight className="w-4 h-4" />
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
