'use client';

const ITEMS = [
  { type: 'green', text: 'Applied — Senior Backend Engineer (47s)' },
  { type: 'violet', text: '94% match: ML Engineer role found' },
  { type: 'dim', text: 'Scanning... 3 new roles found' },
  { type: 'green', text: 'Application submitted: 8 fields, 42s' },
  { type: 'dim', text: 'Follow-up drafted — Day 7' },
  { type: 'violet', text: 'New match: Full Stack Engineer — 89%' },
  { type: 'green', text: 'Screenshot receipt → Slack' },
  { type: 'dim', text: 'Resume attached to application' },
  { type: 'violet', text: 'Answer bank: saved salary expectation' },
  { type: 'green', text: '3 custom Qs drafted automatically' },
];

function ItemSpan({ item }: { item: typeof ITEMS[0] }) {
  const color = item.type === 'green' ? 'var(--g)' : item.type === 'violet' ? 'var(--vl)' : 'var(--t3)';
  const dotColor = item.type === 'green' ? 'var(--g)' : item.type === 'violet' ? 'var(--v)' : undefined;

  return (
    <span style={{ padding: '0 20px', display: 'flex', alignItems: 'center', gap: 6, color }}>
      {dotColor && (
        <span style={{
          width: 4, height: 4, borderRadius: '50%',
          background: dotColor, boxShadow: `0 0 4px ${dotColor}`,
          display: 'inline-block',
        }} />
      )}
      {item.text}
    </span>
  );
}

export default function Ticker() {
  // Duplicate items for seamless loop
  const allItems = [...ITEMS, ...ITEMS];

  return (
    <div className="ticker">
      <div className="ticker-track">
        {allItems.map((item, i) => (
          <span key={i}>
            <ItemSpan item={item} />
            {i < allItems.length - 1 && (
              <span style={{ color: 'rgba(255,255,255,0.04)', padding: '0 6px' }}>|</span>
            )}
          </span>
        ))}
      </div>
    </div>
  );
}
