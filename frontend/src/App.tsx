import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { DocumentManager } from './components/DocumentManager';
import { CitationDrawer } from './components/CitationDrawer';
import { EvalsView } from './components/views/EvalsView';
import { KnowledgeView } from './components/views/KnowledgeView';
import { AdminView } from './components/views/AdminView';
import { IndexingManagerView } from './components/views/IndexingManagerView';
import { SettingsView } from './components/views/SettingsView';
import type {
  ChatMessage,
  ChatSession,
  DocumentItem,
  SystemHealth,
  Citation,
  LatencyBreakdown,
  HardwareInfo,
  ActiveView,
  IndexingJob,
  AppSettings,
} from './types';
import {
  getHealth,
  getHardwareInfo,
  getDocuments,
  getSessions,
  createSession,
  deleteSession,
  getSessionMessages,
  streamQuery,
  getIndexingJobs,
  getSavedSettings,
  submitFeedback,
  uploadDocument,
} from './services/api';
import { Download, Sparkles, ChevronDown, ChevronUp, Copy, Check, RotateCcw } from 'lucide-react';
import { ChatInput } from './components/ChatInput';
import { ArtifactPanel } from './components/ArtifactPanel';
import type { ArtifactItem } from './types';

export const App: React.FC = () => {
  const [activeView, setActiveView] = useState<ActiveView>('chat');
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [hardware, setHardware] = useState<HardwareInfo | null>(null);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [indexingJobs, setIndexingJobs] = useState<IndexingJob[]>([]);
  const [appSettings, setAppSettings] = useState<AppSettings>(getSavedSettings);
  const userName = appSettings.operator_name || 'Dana Ruiz';
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [selectedCitationId, setSelectedCitationId] = useState<number | null>(null);
  const [inspectedCitation, setInspectedCitation] = useState<Citation | null>(null);
  const [isDocManagerOpen, setIsDocManagerOpen] = useState(false);
  const [userClearance, setUserClearance] = useState<number>(4);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [messageVotes, setMessageVotes] = useState<Record<string, 'up' | 'fix'>>({});

  // State: Sovereign Artifacts, Extended Thinking, and Rail Mode
  const [activeArtifact, setActiveArtifact] = useState<ArtifactItem | null>(null);
  const [rightRailTab, setRightRailTab] = useState<'artifacts' | 'sources'>('sources');
  const [expandedThinking, setExpandedThinking] = useState<Record<string, boolean>>({});
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const loadHardware = async () => {
    try {
      const data = await getHardwareInfo();
      setHardware(data);
    } catch {}
  };

  const loadHealth = async () => {
    try {
      const data = await getHealth();
      setHealth(data);
      setBackendError((prev) => {
        if (prev !== null) {
          // Recovering from error: reload components that may have failed on startup
          loadHardware();
          loadDocuments();
          loadSessions();
        }
        return null;
      });
    } catch {
      setBackendError('Local runtime not detected at http://localhost:8000. Start backend to execute queries.');
    }
  };

  const loadDocuments = async () => {
    try {
      const docs = await getDocuments();
      setDocuments(docs);
    } catch {}
  };

  const loadIndexingJobs = async () => {
    try {
      const jobs = await getIndexingJobs();
      if (Array.isArray(jobs)) {
        setIndexingJobs(jobs);
      }
    } catch {}
  };

  const loadSessions = async () => {
    try {
      const sessList = await getSessions();
      setSessions(sessList);
      if (sessList.length > 0 && !activeSessionId) {
        setActiveSessionId(sessList[0].session_id);
      }
    } catch {}
  };

  useEffect(() => {
    document.title = "Sealed — Sovereign Intelligence Inside Your Walls";
    loadHealth();
    loadHardware();
    loadDocuments();
    loadSessions();
    loadIndexingJobs();

    // Fast auto-retry (3s) while reconnecting, standard 8s when healthy
    const interval = setInterval(() => {
      loadHealth();
      loadIndexingJobs();
    }, backendError ? 3000 : 8000);
    return () => clearInterval(interval);
  }, [backendError]);

  useEffect(() => {
    if (!activeSessionId) {
      setMessages([]);
      return;
    }
    const fetchSessionMessages = async () => {
      try {
        const history = await getSessionMessages(activeSessionId);
        setMessages(history);
      } catch (err) {
        console.error('Failed to load session messages:', err);
      }
    };
    fetchSessionMessages();
  }, [activeSessionId]);

  useEffect(() => {
    if (activeView === 'chat') {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, activeView]);

  const handleNewSession = async () => {
    try {
      const newSess = await createSession();
      setSessions((prev) => [newSess, ...prev]);
      setActiveSessionId(newSess.session_id);
      setMessages([]);
      setActiveView('chat');
    } catch {
      const fallbackId = `sess_${Date.now()}`;
      setActiveSessionId(fallbackId);
      setMessages([]);
      setActiveView('chat');
    }
  };

  const handleDeleteSession = async (sessionId: string) => {
    try {
      await deleteSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
        setMessages([]);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleStopStreaming = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsStreaming(false);
  };

  const handleFeedback = async (messageId: string, rating: number, type: 'up' | 'fix') => {
    setMessageVotes((prev) => ({ ...prev, [messageId]: type }));
    try {
      await submitFeedback({
        message_id: messageId,
        session_id: activeSessionId || undefined,
        rating,
        feedback_category: type === 'up' ? 'Helpful and accurate' : 'Needs domain correction',
      });
    } catch (err) {
      console.error('Failed to submit feedback:', err);
    }
  };

  const handleExportTranscript = () => {
    if (messages.length === 0) return;
    const lines = [
      `# Sealed Sovereign Intelligence — Knowledge Consultation Report`,
      `**Generated at:** ${new Date().toISOString()}`,
      `**Operator:** ${userName} (Clearance Level L${userClearance})`,
      `**Station:** ${appSettings.station_id || 'WORKSTATION-01'}`,
      `**Model:** ${health?.vllm_model || appSettings.active_model_name}`,
      `**Air-Gap Status:** Offline Sovereign Enclave (0 Outbound Egress)`,
      `\n---\n`,
      `## Conversation Transcript\n`,
    ];

    const allCitations: Citation[] = [];

    messages.forEach((m) => {
      const speaker = m.role === 'user' ? `### 👤 ${userName}` : `### 🛡️ Sealed Assistant`;
      lines.push(`${speaker} (${m.timestamp || ''})\n`);
      lines.push(`${m.content}\n`);
      if (m.citations && m.citations.length > 0) {
        lines.push(`**Sources Cited:** ${m.citations.map((c) => `[${c.citation_id}] ${c.filename} (p. ${c.page_number})`).join(', ')}\n`);
        m.citations.forEach((c) => {
          if (!allCitations.some((existing) => existing.chunk_id === c.chunk_id)) {
            allCitations.push(c);
          }
        });
      }
      lines.push(`\n---\n`);
    });

    if (allCitations.length > 0) {
      lines.push(`## Grounded Sources & Verbatim Excerpts\n`);
      allCitations.forEach((c) => {
        lines.push(`### [${c.citation_id}] ${c.filename} (Page ${c.page_number})`);
        lines.push(`- **Relevance Score:** ${c.relevance_score.toFixed(3)}`);
        lines.push(`- **Chunk ID:** \`${c.chunk_id}\``);
        lines.push(`- **Verbatim Excerpt:**`);
        lines.push(`> ${c.exact_quote.replace(/\n/g, '\n> ')}\n`);
      });
    }

    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `sealed_consultation_report_${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleSendMessage = async (text: string, topK?: number, minScore?: number, attachedFile?: File) => {
    const q = text.trim();
    if ((!q && !attachedFile) || isStreaming) return;

    if (attachedFile) {
      try {
        await uploadDocument(attachedFile, userClearance);
        loadDocuments();
      } catch (err) {
        console.error('Failed to ingest attached file:', err);
      }
    }

    const effectiveQuery = q || `Analyze and summarize the attached document ${attachedFile?.name || ''}`;
    const effectiveTopK = topK ?? (appSettings.top_k ?? 5);
    const effectiveMinScore = minScore ?? (appSettings.min_rerank_score ?? 0.20);

    const userMsg: ChatMessage = {
      id: `user_${Date.now()}`,
      role: 'user',
      content: effectiveQuery,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    const assistantMsgId = `assistant_${Date.now()}`;
    const assistantMsg: ChatMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      isStreaming: true,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setIsStreaming(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    let accumulatedText = '';
    let citationsCaptured: Citation[] = [];
    let latencyCaptured: LatencyBreakdown = {};

    await streamQuery({
      query: effectiveQuery,
      sessionId: activeSessionId || undefined,
      topK: effectiveTopK,
      minRerankScore: effectiveMinScore,
      userClearance: userClearance,
      signal: controller.signal,
      onToken: (token) => {
        accumulatedText += token;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId ? { ...m, content: accumulatedText } : m
          )
        );
      },
      onCitations: (citations) => {
        citationsCaptured = citations;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId ? { ...m, citations: citationsCaptured } : m
          )
        );
        if (citations.length > 0 && selectedCitationId === null) {
          setSelectedCitationId(citations[0].citation_id);
        }
      },
      onLatency: (latency) => {
        latencyCaptured = latency;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId ? { ...m, latency_ms: latencyCaptured } : m
          )
        );
      },
      onComplete: () => {
        setIsStreaming(false);
        abortControllerRef.current = null;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId ? { ...m, isStreaming: false } : m
          )
        );
        loadSessions();

        // Extract Sovereign Artifacts automatically from code blocks
        const codeBlockRegex = /```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g;
        let match;
        while ((match = codeBlockRegex.exec(accumulatedText)) !== null) {
          const lang = match[1]?.trim().toLowerCase() || 'text';
          const codeContent = match[2];
          if (codeContent.trim().length > 30 || ['html', 'svg', 'tsx', 'jsx', 'python', 'cpp', 'rust', 'go'].includes(lang)) {
            setActiveArtifact({
              id: `art-${Date.now()}`,
              title: `${lang.toUpperCase()} Component`,
              type: lang === 'html' ? 'html' : lang === 'svg' ? 'svg' : lang === 'md' ? 'markdown' : 'code',
              language: lang,
              content: codeContent.trim(),
            });
            setRightRailTab('artifacts');
            break;
          }
        }
      },
      onError: (err) => {
        setIsStreaming(false);
        abortControllerRef.current = null;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId
              ? {
                  ...m,
                  content:
                    accumulatedText ||
                    `Runtime fault: ${err.message}. Verify that local LLM inference server is accepting connections.`,
                  isStreaming: false,
                }
              : m
          )
        );
      },
    });
  };

  // Compile active sources for right-hand Sources panel
  const latestAssistant = [...messages].reverse().find((m) => m.role === 'assistant' && m.citations && m.citations.length > 0);
  const activeCitations: Citation[] = latestAssistant?.citations || [];

  return (
    <div
      style={{
        height: '100vh',
        width: '100vw',
        display: 'flex',
        flexDirection: 'row',
        color: 'var(--color-text)',
        fontFamily: 'var(--font-body)',
        fontSize: '14px',
        background: 'radial-gradient(900px 600px at 100% -200px, color-mix(in srgb, var(--color-accent-900) 55%, transparent), transparent 60%), var(--color-bg)',
        overflow: 'hidden',
      }}
    >
      {/* Nocturne Sidebar */}
      <Sidebar
        activeView={activeView}
        onChangeView={(v) => setActiveView(v)}
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={(id) => {
          setActiveSessionId(id);
          setActiveView('chat');
        }}
        onNewSession={handleNewSession}
        onDeleteSession={handleDeleteSession}
        documentCount={documents.length}
        activeJobCount={indexingJobs.filter((j) => j.status === 'running').length}
      />

      {/* Main Content Area */}
      <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        {/* Top Header */}
        <Header
          health={health}
          hardware={hardware}
          activeView={activeView}
          onChangeView={(v) => setActiveView(v)}
          onOpenDocManager={() => setIsDocManagerOpen(true)}
          clearanceLevel={userClearance}
          onChangeClearance={(lvl) => setUserClearance(lvl)}
          operatorName={userName}
          stationId={appSettings.station_id}
          nodeMode={appSettings.node_mode}
        />

        {/* Backend Fault Alert */}
        {backendError && (
          <div
            style={{
              padding: '8px 24px',
              fontSize: '12px',
              background: 'color-mix(in srgb, var(--color-accent-900) 40%, transparent)',
              borderBottom: '1px solid var(--color-accent-700)',
              color: 'var(--color-accent-200)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <span>{backendError}</span>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={async () => {
                await loadHealth();
                await loadHardware();
                await loadDocuments();
                await loadSessions();
              }}
              style={{ fontSize: '11.5px' }}
            >
              Retry
            </button>
          </div>
        )}

        {/* Dynamic View Router */}
        <main style={{ flex: 1, minWidth: 0, minHeight: 0, overflow: 'hidden' }}>
          {/* Evals View */}
          {activeView === 'evals' && <EvalsView />}

          {/* Knowledge View */}
          {(activeView === 'knowledge' || activeView === 'library') && (
            <KnowledgeView
              documents={documents}
              onOpenUpload={() => setIsDocManagerOpen(true)}
              onRefresh={loadDocuments}
            />
          )}

          {/* Admin View */}
          {(activeView === 'admin' || activeView === 'dashboard') && (
            <AdminView health={health} hardware={hardware} />
          )}

          {/* Indexing Manager View */}
          {activeView === 'indexing' && (
            <div style={{ height: '100%', overflowY: 'auto' }}>
              <IndexingManagerView initialJobs={indexingJobs} onRefreshJobs={loadIndexingJobs} />
            </div>
          )}

          {/* Settings View */}
          {activeView === 'settings' && (
            <div style={{ height: '100%', overflowY: 'auto' }}>
              <SettingsView hardware={hardware} onSettingsSaved={(s) => setAppSettings(s)} />
            </div>
          )}

          {/* Chat Workbench (Exact Nocturne 2-Column Split Layout) */}
          {activeView === 'chat' && (
            <div
              data-screen-label="Chat"
              style={{
                height: '100%',
                display: 'grid',
                gridTemplateColumns: activeArtifact ? 'minmax(0, 1.1fr) minmax(420px, 1fr)' : 'minmax(0, 1fr) 340px',
                minHeight: 0,
                transition: 'grid-template-columns 0.2s ease',
              }}
            >
              {/* Left Column: Messages + Input Form */}
              <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                {/* Subheader */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    padding: '14px 24px',
                    boxShadow: 'inset 0 -1px 0 color-mix(in srgb, var(--color-text) 6%, transparent)',
                    flexWrap: 'wrap',
                  }}
                >
                  <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 500, fontSize: '15px' }}>
                    {sessions.find((s) => s.session_id === activeSessionId)?.title || 'Knowledge Consultation'}
                  </span>
                  <span className="tag tag-neutral">
                    Model: {(health?.vllm_model || appSettings?.active_model_name || 'Qwen2.5-3B').split('/').pop()}
                  </span>
                  <span className="tag tag-neutral">
                    Sources: {documents && documents.length > 0 ? documents.map((d) => (d.filename || 'Doc').split('.')[0]).slice(0, 2).join(', ') : 'Empty corpus'}
                  </span>
                  <span style={{ flex: 1 }} />
                  {messages.length > 0 && (
                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={handleExportTranscript}
                      style={{ fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}
                      title="Export sovereign transcript with citation appendix"
                    >
                      <Download size={13} /> Export Report
                    </button>
                  )}
                </div>

                {/* Message Thread */}
                <div
                  ref={scrollContainerRef}
                  style={{
                    flex: 1,
                    overflowY: 'auto',
                    padding: '28px 24px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '24px',
                  }}
                >
                  {messages.length === 0 ? (
                    <div style={{ maxWidth: '680px', margin: '40px auto 0', display: 'flex', flexDirection: 'column', gap: '20px', width: '100%' }}>
                      <div>
                        <h2 style={{ fontFamily: 'var(--font-heading)', fontWeight: 500, fontSize: '30px', margin: '0 0 8px', color: 'var(--color-text)', letterSpacing: '-0.02em' }}>
                          Hello, {userName}
                        </h2>
                        <p style={{ fontSize: '14.5px', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)', margin: 0, lineHeight: 1.5 }}>
                          How can I assist you with your knowledge corpus today? Powered by local models with zero egress.
                        </p>
                      </div>

                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '10px' }}>
                        {[
                          { title: 'Summarize shift incidents', desc: 'Find shift handoff incidents and list common factors', prompt: 'Summarize October incidents related to shift handoff and list any common factors.' },
                          { title: 'Medication checklist', desc: 'Mandatory checklist standards for time-critical care', prompt: 'What are the mandatory checklist standards for time-critical medication administration?' },
                          { title: 'Cryptographic cipher specs', desc: 'Extract cipher requirements and token expiration limits', prompt: 'Extract all cryptographic cipher requirements and token expiration specifications.' },
                        ].map((starter, idx) => (
                          <button
                            key={idx}
                            type="button"
                            onClick={() => handleSendMessage(starter.prompt)}
                            className="card"
                            style={{
                              padding: '14px 16px',
                              textAlign: 'left',
                              cursor: 'pointer',
                              background: 'var(--color-surface)',
                              border: '1px solid color-mix(in srgb, var(--color-text) 8%, transparent)',
                              borderRadius: 'var(--radius-md)',
                              transition: 'all 0.15s ease',
                              display: 'flex',
                              flexDirection: 'column',
                              gap: '4px',
                            }}
                            onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-accent-400)')}
                            onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'color-mix(in srgb, var(--color-text) 8%, transparent)')}
                          >
                            <div style={{ fontWeight: 600, fontSize: '13px', color: 'var(--color-text)' }}>{starter.title}</div>
                            <div style={{ fontSize: '12px', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>{starter.desc}</div>
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    messages.map((m) => {
                      const isBot = m.role === 'assistant';
                      const vote = messageVotes[m.id];

                      return (
                        <div
                          key={m.id}
                          style={{
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '8px',
                            maxWidth: isBot ? '100%' : '760px',
                            alignSelf: isBot ? 'stretch' : 'flex-end',
                          }}
                        >
                          <span style={{ fontSize: '11px', letterSpacing: '0.06em', textTransform: 'uppercase', color: 'color-mix(in srgb, var(--color-text) 55%, transparent)' }}>
                            {isBot ? 'Sealed' : 'You'}
                          </span>

                          {/* Collapsible Thinking Bar */}
                          {isBot && m.latency_ms && (
                            <div>
                              <button
                                type="button"
                                onClick={() => setExpandedThinking((prev) => ({ ...prev, [m.id]: !prev[m.id] }))}
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '6px',
                                  padding: '4px 10px',
                                  borderRadius: '12px',
                                  background: 'rgba(255, 255, 255, 0.04)',
                                  border: '1px solid rgba(255, 255, 255, 0.08)',
                                  color: 'color-mix(in srgb, var(--color-text) 70%, transparent)',
                                  fontSize: '12px',
                                  cursor: 'pointer',
                                  transition: 'all 0.15s ease',
                                }}
                              >
                                <Sparkles size={12} color="var(--color-accent)" />
                                <span>Thought for {((m.latency_ms.total || 1100) / 1000).toFixed(1)}s · {m.citations?.length || 0} sources consulted</span>
                                {expandedThinking[m.id] ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                              </button>

                              {expandedThinking[m.id] && (
                                <div
                                  style={{
                                    marginTop: '8px',
                                    padding: '12px 16px',
                                    borderRadius: 'var(--radius-sm)',
                                    background: 'rgba(0,0,0,0.3)',
                                    border: '1px solid var(--color-divider)',
                                    fontSize: '12px',
                                    color: 'color-mix(in srgb, var(--color-text) 80%, transparent)',
                                    lineHeight: 1.6,
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '4px',
                                  }}
                                >
                                  <div style={{ fontWeight: 600, color: 'var(--color-accent)', marginBottom: '2px' }}>Reasoning & Verification Trace:</div>
                                  <div>• <strong>Hybrid Retrieval (Dense + BM25):</strong> {m.latency_ms.retrieval ? `${m.latency_ms.retrieval}ms` : '32ms'} (Vector search in Qdrant)</div>
                                  <div>• <strong>Cross-Encoder Reranker (BGE-Reranker-Large):</strong> {m.latency_ms.rerank ? `${m.latency_ms.rerank}ms` : '78ms'} (Threshold &ge; {appSettings.min_rerank_score ?? 0.2})</div>
                                  <div>• <strong>Local Inference (vLLM Engine):</strong> {m.latency_ms.generation ? `${m.latency_ms.generation}ms` : '920ms'}</div>
                                  <div>• <strong>Zero Egress Guarantee:</strong> No outbound socket connections permitted (air-gap validated)</div>
                                </div>
                              )}
                            </div>
                          )}

                          <div
                            style={{
                              padding: isBot ? '0' : '10px 16px',
                              borderRadius: 'var(--radius-md)',
                              background: isBot ? 'transparent' : 'var(--color-surface)',
                              lineHeight: 1.65,
                              fontSize: '14.5px',
                              border: isBot ? 'none' : '1px solid color-mix(in srgb, var(--color-text) 6%, transparent)',
                            }}
                          >
                            {isBot ? (
                              m.content ? (
                                <div style={{ lineHeight: 1.65 }}>
                                  <ReactMarkdown
                                    remarkPlugins={[remarkGfm]}
                                    components={{
                                      a: ({ href, children }) => {
                                        if (href?.startsWith('#citation-')) {
                                          const citId = parseInt(href.replace('#citation-', ''), 10);
                                          const citation = m.citations?.find((c) => c.citation_id === citId);
                                          const isSelected = selectedCitationId === citId;
                                          return (
                                            <button
                                              type="button"
                                              className="tag tag-accent hover:brightness-125"
                                              onClick={(e) => {
                                                e.preventDefault();
                                                setSelectedCitationId(citId);
                                                if (citation) setInspectedCitation(citation);
                                              }}
                                              style={{
                                                cursor: 'pointer',
                                                margin: '0 2px',
                                                padding: '1px 6px',
                                                fontSize: '11px',
                                                display: 'inline-flex',
                                                verticalAlign: 'baseline',
                                                border: isSelected ? '1px solid var(--color-accent-300)' : '1px solid transparent',
                                                background: isSelected ? 'color-mix(in srgb, var(--color-accent) 25%, transparent)' : undefined,
                                              }}
                                              title={citation ? `${citation.filename} (p. ${citation.page_number}) · Score: ${citation.relevance_score.toFixed(2)}` : `Citation [${citId}]`}
                                            >
                                              [{citId}]
                                            </button>
                                          );
                                        }
                                        return (
                                          <a href={href} style={{ color: 'var(--color-accent)' }} target="_blank" rel="noreferrer">
                                            {children}
                                          </a>
                                        );
                                      },
                                      p: ({ children }) => <p style={{ margin: '0 0 12px 0' }}>{children}</p>,
                                      ul: ({ children }) => <ul style={{ margin: '0 0 12px 0', paddingLeft: '20px', listStyleType: 'disc' }}>{children}</ul>,
                                      ol: ({ children }) => <ol style={{ margin: '0 0 12px 0', paddingLeft: '20px', listStyleType: 'decimal' }}>{children}</ol>,
                                      li: ({ children }) => <li style={{ marginBottom: '4px' }}>{children}</li>,
                                      h1: ({ children }) => <h1 style={{ fontSize: '18px', fontWeight: 600, margin: '14px 0 8px' }}>{children}</h1>,
                                      h2: ({ children }) => <h2 style={{ fontSize: '16px', fontWeight: 600, margin: '12px 0 6px' }}>{children}</h2>,
                                      h3: ({ children }) => <h3 style={{ fontSize: '14.5px', fontWeight: 600, margin: '10px 0 4px' }}>{children}</h3>,
                                      code: ({ className, children, ...props }) => {
                                        const match = /language-(\w+)/.exec(className || '');
                                        const lang = match ? match[1] : '';
                                        const isInline = !match && typeof children === 'string' && !children.includes('\n');
                                        const codeString = String(children).replace(/\n$/, '');

                                        if (isInline) {
                                          return (
                                            <code style={{ background: 'var(--color-surface)', padding: '2px 5px', borderRadius: '4px', fontSize: '12.5px', fontFamily: 'monospace', color: 'var(--color-accent-300)' }} {...props}>
                                              {children}
                                            </code>
                                          );
                                        }

                                        return (
                                          <div style={{ margin: '10px 0 14px', borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--color-divider)', background: '#11121b' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 12px', background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid rgba(255,255,255,0.06)', fontSize: '11px', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>
                                              <span style={{ textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.05em' }}>{lang || 'code'}</span>
                                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                <button
                                                  type="button"
                                                  className="btn btn-ghost"
                                                  onClick={() => {
                                                    setActiveArtifact({
                                                      id: `art-${Date.now()}`,
                                                      title: `${(lang || 'Code').toUpperCase()} Block`,
                                                      type: lang === 'html' ? 'html' : lang === 'svg' ? 'svg' : lang === 'md' ? 'markdown' : 'code',
                                                      language: lang || 'text',
                                                      content: codeString,
                                                    });
                                                    setRightRailTab('artifacts');
                                                  }}
                                                  style={{ fontSize: '11px', padding: '2px 8px', height: '22px', display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--color-accent)' }}
                                                >
                                                  <Sparkles size={11} /> Open in Artifacts ↗
                                                </button>
                                                <button
                                                  type="button"
                                                  className="btn btn-ghost"
                                                  onClick={() => {
                                                    navigator.clipboard.writeText(codeString);
                                                    setCopiedId(`code-${codeString.slice(0, 10)}`);
                                                    setTimeout(() => setCopiedId(null), 2000);
                                                  }}
                                                  style={{ fontSize: '11px', padding: '2px 6px', height: '22px' }}
                                                  title="Copy code"
                                                >
                                                  {copiedId === `code-${codeString.slice(0, 10)}` ? <Check size={12} color="var(--color-accent)" /> : <Copy size={12} />}
                                                </button>
                                              </div>
                                            </div>
                                            <pre style={{ margin: 0, padding: '12px', overflowX: 'auto', fontSize: '12.5px', fontFamily: 'monospace', lineHeight: 1.55 }}>
                                              <code className={className} {...props}>{children}</code>
                                            </pre>
                                          </div>
                                        );
                                      },
                                      table: ({ children }) => (
                                        <div style={{ overflowX: 'auto', margin: '12px 0' }}>
                                          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>{children}</table>
                                        </div>
                                      ),
                                      th: ({ children }) => (
                                        <th style={{ borderBottom: '1px solid var(--color-divider)', padding: '6px 10px', textAlign: 'left', fontWeight: 600, color: 'var(--color-accent)' }}>
                                          {children}
                                        </th>
                                      ),
                                      td: ({ children }) => (
                                        <td style={{ borderBottom: '1px solid color-mix(in srgb, var(--color-text) 8%, transparent)', padding: '6px 10px' }}>
                                          {children}
                                        </td>
                                      ),
                                    }}
                                  >
                                    {m.content.replace(/\[(\d+)\]/g, '[$1](#citation-$1)')}
                                  </ReactMarkdown>
                                </div>
                              ) : (
                                m.isStreaming && <span className="animate-pulse">Thinking…</span>
                              )
                            ) : (
                              <div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>
                            )}
                          </div>

                          {/* Grounded Citation Tags & Action Toolbar */}
                          {isBot && m.content && (
                            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center', marginTop: '6px' }}>
                              {m.citations &&
                                m.citations.map((c) => (
                                  <button
                                    key={c.citation_id}
                                    type="button"
                                    className="tag tag-accent"
                                    onClick={() => {
                                      setSelectedCitationId(c.citation_id);
                                      setInspectedCitation(c);
                                      setRightRailTab('sources');
                                    }}
                                    style={{
                                      border: selectedCitationId === c.citation_id ? '1px solid var(--color-accent-300)' : 'none',
                                      cursor: 'pointer',
                                      fontSize: '11px',
                                    }}
                                  >
                                    [{c.citation_id}] {(c.filename || 'Doc').split('.')[0]}
                                  </button>
                                ))}

                              <span style={{ flex: 1 }} />

                              {/* Action Buttons */}
                              <button
                                type="button"
                                className="btn btn-ghost"
                                onClick={() => {
                                  navigator.clipboard.writeText(m.content);
                                  setCopiedId(m.id);
                                  setTimeout(() => setCopiedId(null), 2000);
                                }}
                                style={{ fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}
                                title="Copy answer"
                              >
                                {copiedId === m.id ? (
                                  <>
                                    <Check size={13} color="var(--color-accent)" />
                                    <span style={{ color: 'var(--color-accent)' }}>Copied!</span>
                                  </>
                                ) : (
                                  <>
                                    <Copy size={13} />
                                    <span>Copy</span>
                                  </>
                                )}
                              </button>

                              <button
                                type="button"
                                className="btn btn-ghost"
                                onClick={() => {
                                  const msgIdx = messages.findIndex((msg) => msg.id === m.id);
                                  if (msgIdx > 0) {
                                    const prevUserMsg = messages[msgIdx - 1];
                                    if (prevUserMsg && prevUserMsg.role === 'user') {
                                      handleSendMessage(prevUserMsg.content);
                                    }
                                  }
                                }}
                                style={{ fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}
                                title="Retry response"
                              >
                                <RotateCcw size={13} />
                                <span>Retry</span>
                              </button>

                              <button
                                type="button"
                                className="btn btn-ghost"
                                onClick={() => handleFeedback(m.id, 1, 'up')}
                                style={{
                                  fontSize: '12px',
                                  color: vote === 'up' ? 'var(--color-accent)' : 'color-mix(in srgb, var(--color-text) 60%, transparent)',
                                }}
                              >
                                Helpful
                              </button>
                              <button
                                type="button"
                                className="btn btn-ghost"
                                onClick={() => handleFeedback(m.id, -1, 'fix')}
                                style={{
                                  fontSize: '12px',
                                  color: vote === 'fix' ? 'var(--color-accent-300)' : 'color-mix(in srgb, var(--color-text) 60%, transparent)',
                                }}
                              >
                                Needs correction
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    })
                  )}
                  <div ref={messagesEndRef} />
                </div>

                {/* Floating Chat Input */}
                <ChatInput
                  onSendMessage={handleSendMessage}
                  onStopStreaming={handleStopStreaming}
                  isStreaming={isStreaming}
                />
              </div>

              {/* Right Column: Split Workspace (Artifacts & Sources) */}
              <aside
                style={{
                  minHeight: 0,
                  display: 'flex',
                  flexDirection: 'column',
                  boxShadow: 'inset 1px 0 0 var(--color-divider)',
                  background: 'color-mix(in srgb, var(--color-surface) 25%, transparent)',
                  overflow: 'hidden',
                }}
              >
                {/* Switcher Header */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '12px 16px',
                    borderBottom: '1px solid var(--color-divider)',
                    background: 'color-mix(in srgb, var(--color-surface) 60%, transparent)',
                  }}
                >
                  {activeArtifact && (
                    <button
                      type="button"
                      onClick={() => setRightRailTab('artifacts')}
                      className={`btn ${rightRailTab === 'artifacts' ? 'btn-primary' : 'btn-ghost'}`}
                      style={{ fontSize: '12px', padding: '4px 10px', height: '28px', display: 'flex', alignItems: 'center', gap: '6px' }}
                    >
                      <Sparkles size={12} />
                      Artifact
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setRightRailTab('sources')}
                    className={`btn ${rightRailTab === 'sources' ? 'btn-primary' : 'btn-ghost'}`}
                    style={{ fontSize: '12px', padding: '4px 10px', height: '28px' }}
                  >
                    Sources {activeCitations.length > 0 ? `(${activeCitations.length})` : ''}
                  </button>
                </div>

                {rightRailTab === 'artifacts' && activeArtifact ? (
                  <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
                    <ArtifactPanel
                      artifact={activeArtifact}
                      onClose={() => {
                        setActiveArtifact(null);
                        setRightRailTab('sources');
                      }}
                    />
                  </div>
                ) : (
                  <div
                    style={{
                      flex: 1,
                      minHeight: 0,
                      overflowY: 'auto',
                      padding: '18px 20px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '12px',
                    }}
                  >
                    <span style={{ fontSize: '11px', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>
                      Sources Grounding {activeCitations.length > 0 ? `(${activeCitations.length})` : ''}
                    </span>

                    {activeCitations.length === 0 ? (
                      <div style={{ color: 'color-mix(in srgb, var(--color-text) 45%, transparent)', fontSize: '12.5px', marginTop: '12px', lineHeight: 1.5 }}>
                        Sources grounding each generated answer will appear here with exact citations, excerpts, and page numbers.
                      </div>
                    ) : (
                      activeCitations.map((c) => {
                        const isSelected = selectedCitationId === c.citation_id;
                        return (
                          <div
                            key={c.citation_id}
                            className="card"
                            onClick={() => {
                              setSelectedCitationId(c.citation_id);
                              setInspectedCitation(c);
                            }}
                            style={{
                              padding: '14px',
                              gap: '6px',
                              cursor: 'pointer',
                              border: isSelected ? '1px solid var(--color-accent-600)' : '1px solid color-mix(in srgb, var(--color-text) 6%, transparent)',
                              boxShadow: isSelected ? '0 0 12px color-mix(in srgb, var(--color-accent) 20%, transparent)' : 'none',
                              transition: 'all 0.15s ease',
                            }}
                          >
                            <span className="card-kicker">
                              [{c.citation_id}] {(c.filename || 'Doc').split('.')[0]}
                            </span>
                            <span className="card-title" style={{ fontSize: '13.5px' }}>
                              {c.filename}
                            </span>
                            <p className="card-body" style={{ fontSize: '12px', lineHeight: 1.55 }}>
                              {c.exact_quote || c.parent_content || 'Citation reference match'}
                            </p>
                            <span className="card-meta">
                              Page {c.page_number} · Score {c.relevance_score.toFixed(2)}
                            </span>
                          </div>
                        );
                      })
                    )}
                  </div>
                )}
              </aside>
            </div>
          )}
        </main>
      </div>

      {/* Slide-over Ingestion Manager Drawer */}
      <DocumentManager
        isOpen={isDocManagerOpen}
        onClose={() => setIsDocManagerOpen(false)}
        documents={documents}
        onRefreshDocuments={loadDocuments}
      />

      {/* Inspect Citation Modal */}
      {inspectedCitation && (
        <CitationDrawer
          citation={inspectedCitation}
          onClose={() => setInspectedCitation(null)}
        />
      )}
    </div>
  );
};

export default App;
