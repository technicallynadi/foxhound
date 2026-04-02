"use client";

const ITEMS = [
  { type: "green", text: "Application submitted — Senior Backend Engineer" },
  { type: "violet", text: "94% match: ML Engineer role found" },
  { type: "dim", text: "Ghost check: posting verified active" },
  { type: "violet", text: "Intelligence report ready — 3 min build" },
  { type: "green", text: "New match: Full Stack Engineer — 89%" },
  { type: "dim", text: "Interview prep: 14 questions compiled" },
  { type: "violet", text: "Network map: 4 connections found at Stripe" },
  { type: "dim", text: "Career trajectory: Staff Engineer is your next move" },
];

function ItemSpan({ item }: { item: (typeof ITEMS)[0] }) {
  const color =
    item.type === "green"
      ? "var(--g)"
      : item.type === "violet"
        ? "var(--vl)"
        : "var(--t3)";
  const dotColor =
    item.type === "green"
      ? "var(--g)"
      : item.type === "violet"
        ? "var(--v)"
        : undefined;

  return (
    <span
      style={{
        padding: "0 20px",
        display: "flex",
        alignItems: "center",
        gap: 6,
        color,
      }}
    >
      {dotColor && (
        <span
          style={{
            width: 4,
            height: 4,
            borderRadius: "50%",
            background: dotColor,
            boxShadow: `0 0 4px ${dotColor}`,
            display: "inline-block",
          }}
        />
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
              <span
                style={{ color: "rgba(255,255,255,0.04)", padding: "0 6px" }}
              >
                |
              </span>
            )}
          </span>
        ))}
      </div>
    </div>
  );
}
