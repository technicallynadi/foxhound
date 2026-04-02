'use client';

/**
 * PageSkeleton — animated placeholder blocks shown while page data loads.
 * Variants match the layout of each authenticated page so the transition
 * from skeleton to real content is seamless (no flash, no background change).
 *
 * Uses only CSS animation — no extra dependencies.
 */

type Variant = 'dashboard' | 'list' | 'settings' | 'profile' | 'research';

function Block({ w, h, r = 6, mt = 0 }: { w?: string | number; h: number; r?: number; mt?: number }) {
  return (
    <div
      className="skel-block"
      style={{
        width: w ?? '100%',
        height: h,
        borderRadius: r,
        marginTop: mt,
        background: 'var(--sf)',
        position: 'relative',
        overflow: 'hidden',
      }}
    />
  );
}

function Row({ gap = 12, mt = 0, children }: { gap?: number; mt?: number; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', gap, marginTop: mt }}>
      {children}
    </div>
  );
}

function Card({ h = 120, mt = 16, children }: { h?: number; mt?: number; children?: React.ReactNode }) {
  return (
    <div style={{
      background: 'var(--sf)', border: '1px solid var(--b)',
      borderRadius: 12, padding: 24, marginTop: mt,
      minHeight: h,
    }}>
      {children}
    </div>
  );
}

/* --- Variant renderers --- */

function DashboardSkeleton() {
  return (
    <>
      {/* Section label + heading */}
      <Block w={80} h={10} />
      <Block w={260} h={28} mt={12} />
      <Block w={220} h={14} mt={8} />

      {/* Stats row (4 columns) */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 1,
        marginTop: 32, background: 'var(--b)', border: '1px solid var(--b)',
      }}>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} style={{ background: 'var(--bg)', padding: 24 }}>
            <Block w={60} h={10} />
            <Block w={48} h={28} mt={10} />
            <Block w={80} h={10} mt={6} />
          </div>
        ))}
      </div>

      {/* Resume bar */}
      <Card h={56} mt={16}>
        <Row>
          <div style={{ flex: 1 }}>
            <Block w={60} h={10} />
            <Block w={140} h={12} mt={6} />
          </div>
          <Block w={100} h={32} r={6} />
        </Row>
      </Card>

      {/* Recent applications card */}
      <Card mt={32}>
        <Row>
          <Block w={140} h={10} />
          <div style={{ marginLeft: 'auto' }}><Block w={60} h={10} /></div>
        </Row>
        {[0, 1, 2].map((i) => (
          <div key={i} style={{ padding: '14px 0', borderBottom: '1px solid var(--b)' }}>
            <Row>
              <div style={{ flex: 1 }}>
                <Block w="70%" h={14} />
                <Block w={80} h={10} mt={6} />
              </div>
              <Block w={72} h={22} r={4} />
            </Row>
          </div>
        ))}
      </Card>

      {/* Top matches card */}
      <Card mt={16}>
        <Block w={100} h={10} />
        {[0, 1, 2].map((i) => (
          <div key={i} style={{ padding: '14px 0', borderBottom: '1px solid var(--b)' }}>
            <Row>
              <div style={{ flex: 1 }}>
                <Block w="65%" h={14} />
                <Block w={120} h={10} mt={6} />
              </div>
              <Block w={40} h={18} r={4} />
            </Row>
          </div>
        ))}
      </Card>
    </>
  );
}

function ListSkeleton() {
  return (
    <>
      {/* Header */}
      <Block w={100} h={10} />
      <Block w={200} h={28} mt={12} />

      {/* Filter chips */}
      <Row gap={8} mt={24}>
        <Block w={70} h={32} r={6} />
        <Block w={90} h={32} r={6} />
        <Block w={80} h={32} r={6} />
      </Row>

      {/* List card */}
      <div style={{
        background: 'var(--sf)', border: '1px solid var(--b)',
        borderRadius: 12, overflow: 'hidden', marginTop: 24,
      }}>
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div key={i} style={{
            display: 'grid', gridTemplateColumns: '3px 1fr auto',
            gap: '0 16px', padding: '16px 20px 16px 0',
            borderBottom: '1px solid var(--b)',
          }}>
            <div style={{ width: 3, borderRadius: 2, alignSelf: 'stretch', background: 'var(--b)' }} />
            <div>
              <Block w="75%" h={14} />
              <Row gap={12} mt={6}>
                <Block w={70} h={10} />
                <Block w={50} h={10} />
              </Row>
              <Row gap={4} mt={8}>
                {[0, 1, 2, 3].map((j) => (
                  <Block key={j} w={7} h={7} r={99} />
                ))}
              </Row>
            </div>
            <div style={{ alignSelf: 'center' }}>
              <Block w={72} h={22} r={4} />
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

function SettingsSkeleton() {
  return (
    <>
      {/* Header */}
      <Block w={80} h={10} />
      <Block w={160} h={28} mt={12} />

      {/* Settings cards */}
      {[0, 1, 2].map((i) => (
        <Card key={i} mt={i === 0 ? 32 : 16} h={180}>
          <Block w={140} h={10} />
          <div style={{ marginTop: 20, borderTop: '1px solid var(--b)', paddingTop: 16 }}>
            <Block w={80} h={10} />
            <Block w="100%" h={36} mt={8} r={8} />
          </div>
          <div style={{ marginTop: 16, borderTop: '1px solid var(--b)', paddingTop: 16 }}>
            <Block w={100} h={10} />
            <Block w="100%" h={36} mt={8} r={8} />
          </div>
          <div style={{ marginTop: 16, borderTop: '1px solid var(--b)', paddingTop: 16 }}>
            <Row gap={8}>
              <Block w={70} h={32} r={6} />
              <Block w={70} h={32} r={6} />
              <Block w={70} h={32} r={6} />
            </Row>
          </div>
        </Card>
      ))}
    </>
  );
}

function ProfileSkeleton() {
  return (
    <>
      {/* Header */}
      <Block w={60} h={10} />
      <Block w={200} h={32} mt={12} />
      <Block w={360} h={14} mt={8} />

      {/* Resume info bar */}
      <Block w="100%" h={40} r={8} mt={32} />

      {/* Personal info card */}
      <Card mt={24} h={240}>
        <Block w={140} h={10} />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px', marginTop: 20 }}>
          <div><Block w={60} h={10} /><Block w="100%" h={36} mt={6} r={8} /></div>
          <div><Block w={60} h={10} /><Block w="100%" h={36} mt={6} r={8} /></div>
        </div>
        <div style={{ marginTop: 16 }}><Block w={40} h={10} /><Block w="100%" h={36} mt={6} r={8} /></div>
        <div style={{ marginTop: 16 }}><Block w={40} h={10} /><Block w="100%" h={36} mt={6} r={8} /></div>
        <div style={{ marginTop: 16 }}><Block w={60} h={10} /><Block w="100%" h={36} mt={6} r={8} /></div>
      </Card>

      {/* Links card */}
      <Card mt={20} h={120}>
        <Block w={40} h={10} />
        <div style={{ marginTop: 16 }}><Block w={60} h={10} /><Block w="100%" h={36} mt={6} r={8} /></div>
        <div style={{ marginTop: 16 }}><Block w={80} h={10} /><Block w="100%" h={36} mt={6} r={8} /></div>
      </Card>

      {/* Summary card */}
      <Card mt={20} h={140}>
        <Block w={140} h={10} />
        <Block w="100%" h={80} mt={16} r={8} />
      </Card>

      {/* Skills card */}
      <Card mt={20} h={80}>
        <Block w={40} h={10} />
        <Row gap={6} mt={16}>
          <Block w={60} h={24} r={6} />
          <Block w={80} h={24} r={6} />
          <Block w={50} h={24} r={6} />
          <Block w={70} h={24} r={6} />
        </Row>
      </Card>
    </>
  );
}

function ResearchSkeleton() {
  return (
    <>
      {/* Kicker + heading */}
      <Block w={120} h={10} />
      <Block w={200} h={36} mt={12} />
      <Block w={400} h={14} mt={8} />

      {/* Info cards row */}
      <Row gap={10} mt={24}>
        <Card h={70} mt={0}><Block w={60} h={10} /><Block w="90%" h={12} mt={10} /></Card>
        <Card h={70} mt={0}><Block w={50} h={10} /><Block w="85%" h={12} mt={10} /></Card>
        <Card h={70} mt={0}><Block w={50} h={10} /><Block w="80%" h={12} mt={10} /></Card>
      </Row>

      {/* Tab bar */}
      <div style={{ marginTop: 28, borderBottom: '1px solid var(--b)', paddingBottom: 12, display: 'flex', gap: 8 }}>
        {[80, 70, 90, 85, 95, 80].map((w, i) => (
          <Block key={i} w={w} h={36} r={4} />
        ))}
      </div>

      {/* Tab content area */}
      <Card mt={24} h={300}>
        <Block w={180} h={16} />
        <Block w={320} h={12} mt={8} />
        <Block w="100%" h={44} mt={24} r={8} />
        <Block w={120} h={36} mt={16} r={6} />
      </Card>
    </>
  );
}

/* --- Main component --- */

export default function PageSkeleton({ variant }: { variant: Variant }) {
  const maxWidth = variant === 'dashboard' ? 1100 : variant === 'research' ? 1100 : variant === 'list' ? 900 : variant === 'profile' ? 720 : 600;

  return (
    <div style={{
      maxWidth, margin: '0 auto',
      padding: '80px 20px 140px',
      position: 'relative', zIndex: 1,
    }}>
      {variant === 'dashboard' && <DashboardSkeleton />}
      {variant === 'list' && <ListSkeleton />}
      {variant === 'settings' && <SettingsSkeleton />}
      {variant === 'profile' && <ProfileSkeleton />}
      {variant === 'research' && <ResearchSkeleton />}

      {/* Shimmer animation — single style tag, scoped to this tree */}
      <style>{`
        .skel-block::after {
          content: '';
          position: absolute;
          inset: 0;
          background: linear-gradient(
            90deg,
            transparent 0%,
            rgba(255,255,255,0.04) 40%,
            rgba(255,255,255,0.06) 50%,
            rgba(255,255,255,0.04) 60%,
            transparent 100%
          );
          animation: skel-shimmer 1.8s ease-in-out infinite;
        }
        @keyframes skel-shimmer {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(100%); }
        }
        @media (prefers-reduced-motion: reduce) {
          .skel-block::after {
            animation: none;
          }
        }
      `}</style>
    </div>
  );
}
