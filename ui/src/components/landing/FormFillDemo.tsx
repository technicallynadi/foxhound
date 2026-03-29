'use client';

import { useEffect, useRef, useState } from 'react';

const FIELDS = [
  { id: 'fn', label: 'First Name', text: 'Sarah' },
  { id: 'ln', label: 'Last Name', text: 'Chen' },
  { id: 'em', label: 'Email', text: 'sarah@example.com' },
  { id: 'ph', label: 'Phone', text: '+1 (415) 555-0123' },
  { id: 'li', label: 'LinkedIn', text: 'linkedin.com/in/demo-user' },
  { id: 'loc', label: 'Location', text: 'San Francisco, CA' },
  { id: 'co', label: 'Current Company', text: 'Acme Corp' },
  { id: 'title', label: 'Current Title', text: 'Senior ML Engineer' },
  { id: 'yrs', label: 'Years of Experience', text: '5' },
  { id: 'visa', label: 'Work Authorization', text: 'US Citizen' },
];

const WHY_TEXT = "My work on distributed ML training at my previous company directly aligns with Acme AI's mission to build safe, reliable AI systems. I've spent 3 years scaling inference pipelines and I'm excited to contribute to your research direction.";

interface FieldState {
  text: string;
  filling: boolean;
  filled: boolean;
}

export default function FormFillDemo() {
  const [fields, setFields] = useState<Record<string, FieldState>>(
    Object.fromEntries(FIELDS.map((f) => [f.id, { text: '', filling: false, filled: false }]))
  );
  const [whyText, setWhyText] = useState('');
  const [whyFilling, setWhyFilling] = useState(false);
  const [whyFilled, setWhyFilled] = useState(false);
  const [resumeText, setResumeText] = useState('');
  const [status, setStatus] = useState('Waiting...');
  const [statusColor, setStatusColor] = useState('var(--vl)');
  const wrapRef = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  useEffect(() => {
    if (!wrapRef.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !started.current) {
          started.current = true;
          runFill();
        }
      },
      { threshold: 0.2 }
    );
    observer.observe(wrapRef.current);
    return () => observer.disconnect();
  }, []);

  async function runFill() {
    setStatus('Filling...');
    setStatusColor('var(--vl)');

    // Fill standard fields
    for (const field of FIELDS) {
      setFields((prev) => ({ ...prev, [field.id]: { ...prev[field.id], filling: true } }));
      await typeField(field.id, field.text);
      setFields((prev) => ({ ...prev, [field.id]: { text: field.text, filling: false, filled: true } }));
      await sleep(250);
    }

    // Fill "Why Acme AI"
    setWhyFilling(true);
    for (let i = 0; i <= WHY_TEXT.length; i++) {
      setWhyText(WHY_TEXT.substring(0, i));
      await sleep(14 + Math.random() * 8);
    }
    setWhyFilling(false);
    setWhyFilled(true);
    await sleep(300);

    // Resume
    setResumeText('📎 resume_sarah_chen.pdf — attached ✓');
    await sleep(500);

    // Done
    setStatus('Submitted ✓');
    setStatusColor('var(--g)');
  }

  async function typeField(id: string, text: string) {
    for (let i = 0; i <= text.length; i++) {
      setFields((prev) => ({ ...prev, [id]: { ...prev[id], text: text.substring(0, i) } }));
      await sleep(18 + Math.random() * 10);
    }
  }

  function sleep(ms: number) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  const fieldStyle = (filling: boolean, filled: boolean): React.CSSProperties => ({
    background: 'var(--bg)',
    border: `1px solid ${filling ? 'rgba(139,92,246,0.25)' : filled ? 'rgba(52,211,153,0.15)' : 'var(--b)'}`,
    borderRadius: 6,
    padding: '9px 13px',
    fontSize: 14,
    color: 'var(--t)',
    minHeight: 38,
    display: 'flex',
    alignItems: 'center',
    transition: 'border-color 0.3s, box-shadow 0.3s',
    boxShadow: filling ? '0 0 10px rgba(139,92,246,0.04)' : 'none',
  });

  return (
    <div ref={wrapRef} style={{ background: 'var(--sf)', border: '1px solid var(--b)', borderRadius: 12, overflow: 'hidden', height: '100%' }}>
      <div style={{
        padding: '11px 16px', borderBottom: '1px solid var(--b)',
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)',
        display: 'flex', justifyContent: 'space-between',
      }}>
        <span>Acme AI — Application Form</span>
        <span style={{ color: statusColor }}>{status}</span>
      </div>

      <div className="form-demo-grid" style={{ padding: 20, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        {FIELDS.map((f) => (
          <div key={f.id} style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            <label style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              {f.label}
            </label>
            <div style={fieldStyle(fields[f.id].filling, fields[f.id].filled)}>
              {fields[f.id].text}
              {fields[f.id].filling && (
                <span style={{ display: 'inline-block', width: 2, height: 15, background: 'var(--v)', animation: 'cursor-blink 0.7s infinite', marginLeft: 1 }} />
              )}
              {fields[f.id].filled && (
                <span style={{ color: 'var(--g)', fontSize: 11, marginLeft: 'auto' }}>✓</span>
              )}
            </div>
          </div>
        ))}

        {/* Why Acme AI */}
        <div style={{ gridColumn: 'span 2', display: 'flex', flexDirection: 'column', gap: 5 }}>
          <label style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            Why do you want to work at Acme AI?
          </label>
          <div style={{ ...fieldStyle(whyFilling, whyFilled), minHeight: 68, alignItems: 'flex-start', lineHeight: 1.5, fontSize: 13 }}>
            {whyText}
            {whyFilling && (
              <span style={{ display: 'inline-block', width: 2, height: 15, background: 'var(--v)', animation: 'cursor-blink 0.7s infinite', marginLeft: 1 }} />
            )}
          </div>
        </div>

        {/* Resume */}
        <div style={{ gridColumn: 'span 2' }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--t3)' }}>
            {resumeText}
          </span>
        </div>
      </div>
    </div>
  );
}
