'use client';

import { useEffect, useRef, useState, type ChangeEvent, type ReactNode } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import AuthGuard from '@/components/AuthGuard';
import { bootstrapProfile, uploadResume, updatePreferences } from '@/lib/api';

type Stage =
  | 'roles'
  | 'location'
  | 'work'
  | 'seniority'
  | 'industries'
  | 'salary'
  | 'resume'
  | 'processing'
  | 'done';

type QuestionStage = Exclude<Stage, 'resume' | 'processing' | 'done'>;

type ChatMessage = {
  id: string;
  role: 'assistant' | 'user';
  content: string;
};

type ParseStage = 'uploading' | 'parsing' | 'extracting' | 'building' | 'done';

type Answers = {
  roles: string[];
  location: string;
  remotePreference: string;
  seniority: string;
  industries: string[];
  salaryFloor: string;
};

type ParsedSummary = {
  name: string;
  email: string | null;
  skills: string[];
  experience_count: number;
  inferred_titles: string[];
  seniority: string | null;
};

type QuestionConfig = {
  label: string;
  prompt: string;
  placeholder: string;
  required: boolean;
  quickReplies: string[];
};

const QUESTION_SEQUENCE: QuestionStage[] = [
  'roles',
  'location',
  'work',
  'seniority',
  'industries',
  'salary',
];

const REQUIRED_QUESTION_SEQUENCE: QuestionStage[] = ['roles', 'location', 'work', 'seniority'];

const QUESTION_CONFIG: Record<QuestionStage, QuestionConfig> = {
  roles: {
    label: 'Target Roles',
    prompt:
      'What roles should I hunt first? Give me one or more role titles (for example: backend engineer, ML engineer).',
    placeholder: 'Backend engineer, ML engineer...',
    required: true,
    quickReplies: ['Backend engineer', 'ML engineer', 'Frontend engineer', 'Product engineer'],
  },
  location: {
    label: 'Location',
    prompt:
      'Where should I search? Add a city/region or say "Remote in US".',
    placeholder: 'Remote in US or New York',
    required: true,
    quickReplies: ['Remote in US', 'New York', 'San Francisco', 'London'],
  },
  work: {
    label: 'Work Style',
    prompt:
      'What work setup should I prefer: remote, hybrid, on-site, or no preference?',
    placeholder: 'Remote / Hybrid / On-site / No preference',
    required: true,
    quickReplies: ['Remote', 'Hybrid', 'On-site', 'No preference'],
  },
  seniority: {
    label: 'Seniority',
    prompt:
      'What level should I prioritize?',
    placeholder: 'Senior, Staff, Principal...',
    required: true,
    quickReplies: ['Mid-level', 'Senior', 'Staff', 'Principal'],
  },
  industries: {
    label: 'Industry Focus',
    prompt:
      'Any industry preferences? You can list a few or say "skip".',
    placeholder: 'AI, developer tools, fintech... or skip',
    required: false,
    quickReplies: ['AI', 'Developer tools', 'Fintech', 'Skip'],
  },
  salary: {
    label: 'Salary Floor',
    prompt:
      'Any salary floor I should enforce? Example: 180k. You can also say "skip for now".',
    placeholder: '$180k or skip for now',
    required: false,
    quickReplies: ['$140k+', '$180k+', '$220k+', 'Skip for now'],
  },
};

const PARSE_STAGES: { key: ParseStage; label: string; duration: number }[] = [
  { key: 'uploading', label: 'Uploading resume...', duration: 450 },
  { key: 'parsing', label: 'Reading your experience...', duration: 950 },
  { key: 'extracting', label: 'Mapping skills to role families...', duration: 800 },
  { key: 'building', label: 'Calibrating your search profile...', duration: 700 },
];

const INITIAL_ANSWERS: Answers = {
  roles: [],
  location: '',
  remotePreference: '',
  seniority: '',
  industries: [],
  salaryFloor: '',
};

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user';
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isUser ? 'flex-end' : 'flex-start',
        padding: '4px 0',
      }}
    >
      <div
        style={{
          maxWidth: '88%',
          padding: '11px 15px',
          borderRadius: 10,
          fontSize: 13,
          lineHeight: 1.55,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          ...(isUser
            ? {
                background: 'linear-gradient(135deg, var(--v), var(--vd))',
                color: 'white',
                fontWeight: 500,
              }
            : {
                background: 'var(--el)',
                border: '1px solid var(--b)',
                color: 'var(--t2)',
              }),
        }}
      >
        {message.content}
      </div>
    </div>
  );
}

function TypingBubble() {
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-start', padding: '4px 0' }}>
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '10px 14px',
          borderRadius: 10,
          background: 'var(--el)',
          border: '1px solid var(--b)',
        }}
      >
        <span style={typingDotStyle(0)} />
        <span style={typingDotStyle(120)} />
        <span style={typingDotStyle(240)} />
      </div>
    </div>
  );
}

function typingDotStyle(delayMs: number) {
  return {
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: 'var(--t3)',
    animation: `typingPulse 1s ease-in-out ${delayMs}ms infinite`,
  } as const;
}

function SectionCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div
      style={{
        background: 'var(--sf)',
        border: '1px solid var(--b)',
        borderRadius: 12,
        padding: 16,
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--vl)',
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          marginBottom: 10,
        }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}

function QuickReplyRow({
  options,
  onPick,
  disabled,
}: {
  options: string[];
  onPick: (value: string) => void;
  disabled: boolean;
}) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
      {options.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onPick(option)}
          disabled={disabled}
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: disabled ? 'var(--t3)' : 'var(--t2)',
            letterSpacing: '0.04em',
            padding: '8px 12px',
            borderRadius: 999,
            border: '1px solid var(--b)',
            background: disabled ? 'rgba(255,255,255,0.02)' : 'transparent',
            cursor: disabled ? 'default' : 'pointer',
            opacity: disabled ? 0.65 : 1,
          }}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

function ProgressCard({
  answers,
  parseStage,
  parsedSummary,
}: {
  answers: Answers;
  parseStage: ParseStage | null;
  parsedSummary: ParsedSummary | null;
}) {
  const goalsReady = answers.roles.length > 0;
  const preferencesReady = Boolean(answers.location || answers.remotePreference || answers.seniority);

  return (
    <SectionCard title="Profile Snapshot">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <ProgressRow
          label="Roles"
          value={goalsReady ? answers.roles.join(', ') : 'Pending'}
          tone={goalsReady ? 'var(--g)' : 'var(--t3)'}
        />
        <ProgressRow
          label="Preferences"
          value={
            preferencesReady
              ? [answers.location, answers.remotePreference, answers.seniority].filter(Boolean).join(' · ')
              : 'Pending'
          }
          tone={preferencesReady ? 'var(--g)' : 'var(--t3)'}
        />
        <ProgressRow
          label="Resume"
          value={
            parsedSummary
              ? `${parsedSummary.skills.length} skills extracted`
              : parseStage
                ? PARSE_STAGES.find((item) => item.key === parseStage)?.label || 'Processing...'
                : 'Not uploaded'
          }
          tone={parsedSummary || parseStage ? 'var(--vl)' : 'var(--t3)'}
        />
      </div>
    </SectionCard>
  );
}

function ProgressRow({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center' }}>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--t3)',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
        }}
      >
        {label}
      </span>
      <span style={{ fontSize: 12, color: tone, textAlign: 'right' }}>{value}</span>
    </div>
  );
}

export default function OnboardPage() {
  const router = useRouter();
  const [stage, setStage] = useState<Stage>('roles');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [answers, setAnswers] = useState<Answers>(INITIAL_ANSWERS);
  const [error, setError] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [parseStage, setParseStage] = useState<ParseStage | null>(null);
  const [parsedSummary, setParsedSummary] = useState<ParsedSummary | null>(null);
  const [saving, setSaving] = useState(false);
  const [assistantTyping, setAssistantTyping] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const draftInputRef = useRef<HTMLTextAreaElement>(null);
  const pendingTimeoutsRef = useRef<number[]>([]);

  const isQuestionStage = QUESTION_SEQUENCE.includes(stage as QuestionStage);
  const currentQuestionIndex = isQuestionStage ? QUESTION_SEQUENCE.indexOf(stage as QuestionStage) : -1;
  const currentQuestion = isQuestionStage ? QUESTION_CONFIG[stage as QuestionStage] : null;
  const stageReplies = currentQuestion?.quickReplies || [];

  useEffect(() => {
    setMessages([
      {
        id: crypto.randomUUID(),
        role: 'assistant',
        content:
          "I’m Foxhound, your onboarding agent.\n\nI’ll ask six setup questions, start your search immediately, then keep running in the background.",
      },
      {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: QUESTION_CONFIG.roles.prompt,
      },
    ]);
  }, []);

  useEffect(() => {
    // Scroll the chat container to bottom — NOT the entire page
    const el = bottomRef.current?.parentElement;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, assistantTyping, parseStage, error, stage]);

  useEffect(() => {
    if (isQuestionStage) {
      draftInputRef.current?.focus();
    }
  }, [isQuestionStage, stage]);

  useEffect(() => {
    return () => {
      for (const timeout of pendingTimeoutsRef.current) {
        window.clearTimeout(timeout);
      }
    };
  }, []);

  function appendAssistant(content: string) {
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'assistant', content }]);
  }

  function appendUser(content: string) {
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: 'user', content }]);
  }

  function queueAssistant(content: string, delayMs = 350) {
    setAssistantTyping(true);
    const timeout = window.setTimeout(() => {
      setAssistantTyping(false);
      appendAssistant(content);
      pendingTimeoutsRef.current = pendingTimeoutsRef.current.filter((id) => id !== timeout);
    }, delayMs);
    pendingTimeoutsRef.current.push(timeout);
  }

  function normalizeList(text: string) {
    return text
      .split(/[,\n]/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function validateAnswer(stageName: QuestionStage, rawValue: string) {
    const trimmed = rawValue.trim();
    if (!trimmed) {
      return { error: `${QUESTION_CONFIG[stageName].label} is required before I can continue.` };
    }

    if (stageName === 'roles') {
      const roles = normalizeList(trimmed);
      if (roles.length === 0) {
        return { error: 'Please add at least one role title so I know what to hunt for.' };
      }
      return { normalized: roles };
    }

    if (stageName === 'industries') {
      const industries = trimmed.toLowerCase().includes('skip') ? [] : normalizeList(trimmed);
      return { normalized: industries };
    }

    if (stageName === 'salary') {
      const salaryFloor = trimmed.toLowerCase().includes('skip') ? '' : trimmed;
      return { normalized: salaryFloor };
    }

    return { normalized: trimmed };
  }

  function setAnswer(stageName: QuestionStage, value: string | string[]) {
    setAnswers((prev) => {
      if (stageName === 'roles') return { ...prev, roles: value as string[] };
      if (stageName === 'location') return { ...prev, location: value as string };
      if (stageName === 'work') return { ...prev, remotePreference: (value as string).toLowerCase() };
      if (stageName === 'seniority') return { ...prev, seniority: value as string };
      if (stageName === 'industries') return { ...prev, industries: value as string[] };
      return { ...prev, salaryFloor: value as string };
    });
  }

  function transitionCopy(stageName: QuestionStage) {
    if (stageName === 'roles') return 'Good. Role targets locked.';
    if (stageName === 'location') return 'Location preference captured.';
    if (stageName === 'work') return 'Work style saved.';
    if (stageName === 'seniority') return 'Seniority target set.';
    if (stageName === 'industries') return 'Industry focus updated.';
    return 'Salary preference recorded.';
  }

  function handleAnswer(value: string) {
    if (!isQuestionStage || assistantTyping || saving || parseStage) return;
    const stageName = stage as QuestionStage;
    const raw = value.trim();
    if (!raw) return;

    const validated = validateAnswer(stageName, raw);
    if (validated.error) {
      setError(validated.error);
      queueAssistant(validated.error, 220);
      return;
    }

    appendUser(raw);
    setError('');
    setDraft('');
    setAnswer(stageName, validated.normalized as string | string[]);

    const nextIndex = QUESTION_SEQUENCE.indexOf(stageName) + 1;
    const nextStage = nextIndex < QUESTION_SEQUENCE.length ? QUESTION_SEQUENCE[nextIndex] : 'resume';
    setStage(nextStage);

    if (nextStage === 'resume') {
      queueAssistant(
        `${transitionCopy(stageName)}\n\nI can start search now. Upload your resume if you want tighter matching and autonomous applications.\n\nYou can also skip for now, and I’ll still find jobs plus tell you what to improve.`,
      );
      return;
    }

    const nextPrompt = QUESTION_CONFIG[nextStage].prompt;
    queueAssistant(`${transitionCopy(stageName)}\n\n${nextPrompt}`);
  }

  async function runResumeUpload(file: File) {
    setSelectedFile(file);
    setError('');
    let result: { parsed: ParsedSummary } | null = null;
    for (const item of PARSE_STAGES) {
      setParseStage(item.key);
      await new Promise((resolve) => setTimeout(resolve, item.duration));
      if (item.key === 'uploading') {
        result = await uploadResume(file);
      }
    }
    setParseStage('done');
    if (result?.parsed) {
      setParsedSummary(result.parsed);
      appendUser(`Uploaded ${file.name}`);
      queueAssistant(
        `Resume processed. I extracted ${result.parsed.skills.length} skills and inferred ${result.parsed.inferred_titles.slice(0, 3).join(', ') || 'your target titles'}.`,
      );
    }
  }

  async function finalizeOnboarding(skipResume: boolean, resumeAlreadyProcessed = false) {
    setStage('processing');
    setSaving(true);
    setError('');
    try {
      await bootstrapProfile({
        target_titles: answers.roles,
        target_locations: answers.location ? [answers.location] : [],
        remote_preference: answers.remotePreference || 'any',
        salary_floor: parseSalaryFloor(answers.salaryFloor),
        industries: answers.industries,
        seniority_level: answers.seniority || undefined,
        location: answers.location || undefined,
      });
      await updatePreferences({
        target_titles: answers.roles,
        target_locations: answers.location ? [answers.location] : [],
        remote_preference: answers.remotePreference || 'any',
        salary_floor: parseSalaryFloor(answers.salaryFloor),
        industries: answers.industries,
        seniority_level: answers.seniority || undefined,
      });

      if (skipResume) {
        appendUser('Skip resume for now');
        queueAssistant(
          'Search is now active from your preferences. I can discover and score jobs immediately.\n\nI still need a resume before I can apply on your behalf.',
          260,
        );
      } else if (!resumeAlreadyProcessed && selectedFile && !parsedSummary) {
        await runResumeUpload(selectedFile);
      }

      queueAssistant('Onboarding complete. Building your dashboard and first action queue now.', 380);
      setStage('done');
      window.setTimeout(() => {
        router.push('/dashboard');
      }, 1400);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong. Please try again.');
      setStage('resume');
      queueAssistant('I hit a save error. Fix it above and I’ll continue from this point.', 220);
    } finally {
      setSaving(false);
    }
  }

  async function onFilePicked(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('We only accept PDF resumes right now.');
      return;
    }
    await runResumeUpload(file);
    await finalizeOnboarding(false, true);
  }

  const completedRequired = REQUIRED_QUESTION_SEQUENCE.reduce((count, key) => {
    if (key === 'roles') return answers.roles.length > 0 ? count + 1 : count;
    if (key === 'location') return answers.location ? count + 1 : count;
    if (key === 'work') return answers.remotePreference ? count + 1 : count;
    return answers.seniority ? count + 1 : count;
  }, 0);

  return (
    <AuthGuard>
      <main
        style={{
          minHeight: '100dvh',
          padding: '28px 20px 44px',
          background:
            'radial-gradient(circle at top, rgba(139,92,246,0.09) 0%, rgba(8,8,8,0) 44%)',
        }}
      >
        <div style={{ maxWidth: 1120, margin: '0 auto' }}>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 16,
              gap: 12,
              flexWrap: 'wrap',
            }}
          >
            <Link
              href="/"
              style={{
                fontFamily: 'var(--font-display)',
                fontWeight: 700,
                fontSize: 15,
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: 'var(--v)',
                  boxShadow: '0 0 10px var(--v)',
                }}
              />
              Foxhound
            </Link>
            <Link
              href="/dashboard"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: 'var(--t3)',
                textTransform: 'uppercase',
              }}
            >
              Skip to dashboard
            </Link>
          </div>

          <div className="onboard-grid">
            <section
              className="onboard-chat-shell"
              style={{
                background: 'rgba(14, 14, 14, 0.9)',
                backdropFilter: 'blur(24px)',
                border: '1px solid var(--bv)',
                borderRadius: 16,
                height: 'min(78vh, 760px)',
                minHeight: 620,
                display: 'flex',
                flexDirection: 'column',
                overflow: 'hidden',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 16px', borderBottom: '1px solid var(--b)' }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--v)', boxShadow: '0 0 6px var(--v)' }} />
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--t3)' }}>FOXHOUND ONBOARDING AGENT</span>
                <span
                  style={{
                    marginLeft: 'auto',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 10,
                    color: saving || parseStage || assistantTyping ? 'var(--vl)' : 'var(--g)',
                    letterSpacing: '0.06em',
                    textTransform: 'uppercase',
                  }}
                >
                  {saving || parseStage || assistantTyping ? 'WORKING...' : 'ACTIVE'}
                </span>
              </div>

              <div
                style={{
                  borderBottom: '1px solid var(--b)',
                  padding: '10px 16px',
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 10,
                }}
              >
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--t3)', textTransform: 'uppercase' }}>
                  Required Setup {completedRequired}/{REQUIRED_QUESTION_SEQUENCE.length}
                </div>
                {isQuestionStage && (
                  <div style={{ fontSize: 12, color: 'var(--t2)' }}>
                    Step {currentQuestionIndex + 1}/{QUESTION_SEQUENCE.length}: {currentQuestion?.label}
                  </div>
                )}
                {stage === 'resume' && (
                  <div style={{ fontSize: 12, color: 'var(--t2)' }}>
                    Final step: add resume for autonomous apply
                  </div>
                )}
              </div>

              <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 6 }}>
                {messages.map((message) => (
                  <Bubble key={message.id} message={message} />
                ))}

                {assistantTyping && <TypingBubble />}

                {parseStage && stage !== 'done' && (
                  <div style={{ alignSelf: 'flex-start', maxWidth: '88%' }}>
                    <SectionCard title="Resume Analysis">
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        {PARSE_STAGES.map((item) => {
                          const currentIndex = PARSE_STAGES.findIndex((s) => s.key === parseStage);
                          const itemIndex = PARSE_STAGES.findIndex((s) => s.key === item.key);
                          const isDone = parseStage === 'done' || currentIndex > itemIndex;
                          const isCurrent = parseStage === item.key;
                          return (
                            <div key={item.key} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                              <span
                                style={{
                                  width: 8,
                                  height: 8,
                                  borderRadius: '50%',
                                  background: isDone ? 'var(--g)' : isCurrent ? 'var(--vl)' : 'var(--b)',
                                }}
                              />
                              <span style={{ fontSize: 13, color: isDone ? 'var(--t)' : isCurrent ? 'var(--vl)' : 'var(--t3)' }}>
                                {item.label}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    </SectionCard>
                  </div>
                )}

                {error && (
                  <div style={{ alignSelf: 'flex-start', fontSize: 13, color: 'var(--error)' }}>
                    {error}
                  </div>
                )}

                <div ref={bottomRef} />
              </div>

              <div style={{ padding: '12px 14px', borderTop: '1px solid var(--b)' }}>
                {isQuestionStage ? (
                  <>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <textarea
                        ref={draftInputRef}
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault();
                            handleAnswer(draft);
                          }
                        }}
                        rows={1}
                        placeholder={currentQuestion?.placeholder || 'Type your answer'}
                        className="input"
                        style={{
                          flex: 1,
                          minHeight: 42,
                          maxHeight: 120,
                          resize: 'none',
                          padding: '10px 12px',
                          fontSize: 13,
                        }}
                      />
                      <button
                        type="button"
                        onClick={() => handleAnswer(draft)}
                        disabled={!draft.trim() || assistantTyping || saving || Boolean(parseStage)}
                        style={{
                          width: 42,
                          height: 42,
                          borderRadius: 8,
                          border: 'none',
                          background:
                            draft.trim() && !assistantTyping && !saving && !parseStage
                              ? 'var(--v)'
                              : 'rgba(255,255,255,0.04)',
                          color:
                            draft.trim() && !assistantTyping && !saving && !parseStage
                              ? 'white'
                              : 'var(--t3)',
                          cursor:
                            draft.trim() && !assistantTyping && !saving && !parseStage
                              ? 'pointer'
                              : 'default',
                        }}
                      >
                        ↑
                      </button>
                    </div>
                    {stageReplies.length > 0 && (
                      <QuickReplyRow
                        options={stageReplies}
                        onPick={handleAnswer}
                        disabled={assistantTyping || saving || Boolean(parseStage)}
                      />
                    )}
                  </>
                ) : stage === 'resume' ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                      <button type="button" className="btn-violet" onClick={() => fileInputRef.current?.click()}>
                        Upload Resume
                      </button>
                      <button
                        type="button"
                        onClick={() => finalizeOnboarding(true)}
                        disabled={saving}
                        style={{
                          borderRadius: 10,
                          padding: '12px 16px',
                          border: '1px solid var(--b)',
                          background: 'transparent',
                          color: 'var(--t3)',
                          fontFamily: 'var(--font-mono)',
                          fontSize: 11,
                          letterSpacing: '0.06em',
                          textTransform: 'uppercase',
                          cursor: saving ? 'default' : 'pointer',
                          opacity: saving ? 0.6 : 1,
                        }}
                      >
                        Skip For Now
                      </button>
                    </div>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="application/pdf"
                      style={{ display: 'none' }}
                      onChange={onFilePicked}
                    />
                    <div style={{ fontSize: 12, color: 'var(--t3)', lineHeight: 1.6 }}>
                      Resume is optional for job discovery, but required for autonomous applications.
                    </div>
                  </div>
                ) : (
                  <div
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 11,
                      color: 'var(--t3)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.06em',
                    }}
                  >
                    {stage === 'done' ? 'Redirecting to dashboard...' : 'Setting things up...'}
                  </div>
                )}
              </div>
            </section>

            <section
              className="onboard-side-shell"
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 12,
                height: 'min(78vh, 760px)',
                minHeight: 620,
                overflowY: 'auto',
                paddingRight: 2,
              }}
            >
              <SectionCard title="Required Checkpoints">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {REQUIRED_QUESTION_SEQUENCE.map((key) => {
                    const complete =
                      key === 'roles'
                        ? answers.roles.length > 0
                        : key === 'location'
                          ? Boolean(answers.location)
                          : key === 'work'
                            ? Boolean(answers.remotePreference)
                            : Boolean(answers.seniority);
                    return (
                      <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span
                          style={{
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            background: complete ? 'var(--g)' : 'var(--b)',
                          }}
                        />
                        <span style={{ fontSize: 12, color: complete ? 'var(--t)' : 'var(--t3)' }}>
                          {QUESTION_CONFIG[key].label}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </SectionCard>

              <ProgressCard answers={answers} parseStage={parseStage} parsedSummary={parsedSummary} />

              <SectionCard title="Autonomous Rules">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 12, color: 'var(--t2)', lineHeight: 1.65 }}>
                  <div>Foxhound can discover and score jobs without a resume.</div>
                  <div>Foxhound cannot apply until a resume is uploaded.</div>
                  <div>After onboarding, your dashboard becomes a live activity feed of agent actions.</div>
                </div>
              </SectionCard>

              {parsedSummary && (
                <SectionCard title="Resume Signals">
                  <div style={{ fontSize: 12, color: 'var(--t2)', lineHeight: 1.65 }}>
                    <div style={{ marginBottom: 6 }}>
                      <strong style={{ color: 'var(--t)' }}>{parsedSummary.name}</strong>
                      {parsedSummary.email ? ` · ${parsedSummary.email}` : ''}
                    </div>
                    <div style={{ marginBottom: 6 }}>{parsedSummary.experience_count} roles detected.</div>
                    <div>{parsedSummary.skills.slice(0, 8).join(', ')}</div>
                  </div>
                </SectionCard>
              )}
            </section>
          </div>

          <style jsx>{`
            @keyframes typingPulse {
              0%,
              80%,
              100% {
                transform: scale(0.75);
                opacity: 0.4;
              }
              40% {
                transform: scale(1);
                opacity: 1;
              }
            }

            .onboard-grid {
              display: grid;
              grid-template-columns: 1.15fr 0.85fr;
              gap: 16px;
            }

            @media (max-width: 960px) {
              .onboard-grid {
                grid-template-columns: 1fr;
              }

              .onboard-chat-shell,
              .onboard-side-shell {
                height: auto !important;
                min-height: unset !important;
                max-height: unset !important;
              }

              .onboard-side-shell {
                overflow: visible !important;
              }
            }
          `}</style>
        </div>
      </main>
    </AuthGuard>
  );
}

function parseSalaryFloor(raw: string): number | undefined {
  if (!raw) return undefined;
  const parsed = parseInt(raw.replace(/[^0-9]/g, ''), 10);
  return Number.isFinite(parsed) ? parsed : undefined;
}
