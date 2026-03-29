import { ImageResponse } from 'next/og';

export const runtime = 'edge';
export const alt = 'Foxhound — Stop Applying. Start Interviewing.';
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

export default async function Image() {
  const [spaceGrotesk, inter] = await Promise.all([
    fetch('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@700&display=swap')
      .then(() => fetch('https://cdn.jsdelivr.net/fontsource/fonts/space-grotesk@latest/latin-700-normal.woff'))
      .then((res) => res.arrayBuffer()),
    fetch('https://cdn.jsdelivr.net/fontsource/fonts/inter@latest/latin-400-normal.woff')
      .then((res) => res.arrayBuffer()),
  ]);

  return new ImageResponse(
    (
      <div
        style={{
          background: '#080808',
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          padding: '80px',
          position: 'relative',
        }}
      >
        {/* Violet glow */}
        <div
          style={{
            position: 'absolute',
            top: '-100px',
            right: '-100px',
            width: '500px',
            height: '500px',
            borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(139,92,246,0.15) 0%, transparent 60%)',
          }}
        />

        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '40px' }}>
          <div
            style={{
              width: '14px',
              height: '14px',
              borderRadius: '50%',
              background: '#8B5CF6',
              boxShadow: '0 0 20px rgba(139,92,246,0.5)',
            }}
          />
          <span
            style={{
              fontSize: '20px',
              fontFamily: 'Space Grotesk',
              fontWeight: 700,
              color: '#F0F0F0',
              letterSpacing: '0.12em',
              textTransform: 'uppercase' as const,
            }}
          >
            FOXHOUND
          </span>
        </div>

        {/* Headline */}
        <h1
          style={{
            fontFamily: 'Space Grotesk',
            fontSize: '72px',
            fontWeight: 700,
            color: '#F0F0F0',
            letterSpacing: '-0.04em',
            lineHeight: 1.05,
            margin: 0,
            textTransform: 'uppercase' as const,
          }}
        >
          STOP APPLYING.
        </h1>
        <h1
          style={{
            fontFamily: 'Space Grotesk',
            fontSize: '72px',
            fontWeight: 700,
            color: '#A78BFA',
            letterSpacing: '-0.04em',
            lineHeight: 1.05,
            margin: 0,
            textTransform: 'uppercase' as const,
          }}
        >
          START INTERVIEWING.
        </h1>

        {/* Subtitle */}
        <p
          style={{
            fontFamily: 'Inter',
            fontSize: '22px',
            color: 'rgba(240,240,240,0.6)',
            marginTop: '28px',
            lineHeight: 1.5,
            maxWidth: '700px',
          }}
        >
          Your personal career agent. Upload your resume, find matching jobs, and let Foxhound apply for you.
        </p>

        {/* URL */}
        <p
          style={{
            fontFamily: 'Space Grotesk',
            fontSize: '16px',
            color: 'rgba(240,240,240,0.4)',
            marginTop: '40px',
            letterSpacing: '0.08em',
            textTransform: 'uppercase' as const,
          }}
        >
          usefoxhound.com
        </p>
      </div>
    ),
    {
      ...size,
      fonts: [
        {
          name: 'Space Grotesk',
          data: spaceGrotesk,
          weight: 700,
          style: 'normal',
        },
        {
          name: 'Inter',
          data: inter,
          weight: 400,
          style: 'normal',
        },
      ],
    }
  );
}
