'use client';

interface SummaryBarProps {
  totalMatches: number;
  totalApplications: number;
  autopilotEnabled: boolean;
  autopilotThreshold: number;
  applicationsThisMonth?: number;
  monthlyLimit?: number;
}

export default function SummaryBar({
  totalMatches,
  totalApplications,
  autopilotEnabled,
  autopilotThreshold,
  applicationsThisMonth,
  monthlyLimit,
}: SummaryBarProps) {
  return (
    <div style={{
      fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--t2)',
      display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap',
    }}>
      <span style={{ fontWeight: 600 }}>{totalMatches}</span> matches
      <span style={{ color: 'var(--t3)' }}>&middot;</span>
      <span style={{ fontWeight: 600 }}>{totalApplications}</span> applications
      <span style={{ color: 'var(--t3)' }}>&middot;</span>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        {autopilotEnabled && (
          <span style={{
            width: 6, height: 6, borderRadius: '50%',
            background: 'var(--g)', display: 'inline-block',
          }} />
        )}
        Autopilot: {autopilotEnabled ? `On (${autopilotThreshold}%+)` : 'Off'}
      </span>
      {typeof applicationsThisMonth === 'number' && typeof monthlyLimit === 'number' && monthlyLimit > 0 && (
        <>
          <span style={{ color: 'var(--t3)' }}>&middot;</span>
          <span>
            <span style={{ fontWeight: 600 }}>{applicationsThisMonth}</span> / {monthlyLimit} this month
          </span>
        </>
      )}
    </div>
  );
}
