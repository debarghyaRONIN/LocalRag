import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Copy, Check, ThumbsUp, ThumbsDown, ArrowUpRight, Edit3 } from 'lucide-react';
import type { ChatMessage, Citation } from '../types';
import { LatencyBreakdownBadge } from './LatencyBreakdown';
import { submitFeedback } from '../services/api';

interface MessageItemProps {
  message: ChatMessage;
  onSelectCitation: (citation: Citation) => void;
}

export const MessageItem: React.FC<MessageItemProps> = ({ message, onSelectCitation }) => {
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(null);
  const [showCorrection, setShowCorrection] = useState(false);
  const [correctionText, setCorrectionText] = useState('');
  const [correctionSaved, setCorrectionSaved] = useState(false);

  const isAssistant = message.role === 'assistant';

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleFeedback = async (rating: number) => {
    const nextFeedback = feedback === (rating === 1 ? 'up' : 'down') ? null : (rating === 1 ? 'up' : 'down');
    setFeedback(nextFeedback);
    if (nextFeedback) {
      try {
        await submitFeedback({
          message_id: message.id,
          rating,
          feedback_category: rating === 1 ? 'grounded' : 'ungrounded',
        });
      } catch (err) {
        console.error('Failed to submit rating feedback:', err);
      }
    }
  };

  const handleSaveCorrection = async () => {
    if (!correctionText.trim()) return;
    try {
      await submitFeedback({
        message_id: message.id,
        rating: 1,
        expert_correction: correctionText.trim(),
        is_expert_verified: true,
        feedback_category: 'expert_correction',
      });
      setCorrectionSaved(true);
      setFeedback('up');
      setTimeout(() => {
        setShowCorrection(false);
        setCorrectionSaved(false);
      }, 1500);
    } catch (err) {
      console.error('Failed to submit expert correction:', err);
    }
  };

  return (
    <article className={`py-6 px-6 border-b border-surface-border/40 ${isAssistant ? 'bg-surface-panel/30' : 'bg-transparent'}`}>
      <div className="max-w-3xl mx-auto space-y-3">
        {/* Origin & Metadata Header */}
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <span className={`font-mono text-[10px] font-bold tracking-wider uppercase ${
              isAssistant ? 'text-signal-green' : 'text-ink-secondary'
            }`}>
              {isAssistant ? 'LOCAL ENGINE' : 'USER'}
            </span>
            <span className="text-ink-muted text-[10px] font-mono">•</span>
            <span className="text-[10px] font-mono text-ink-muted tabular-nums">
              {message.timestamp}
            </span>
          </div>

          {/* Quick Actions */}
          {isAssistant && !message.isStreaming && message.content && (
            <div className="flex items-center gap-1 text-ink-muted">
              <button
                onClick={handleCopy}
                className="p-1 hover:text-ink-primary transition-colors cursor-pointer rounded"
                title="Copy message"
              >
                {copied ? <Check className="h-3 w-3 text-signal-green" /> : <Copy className="h-3 w-3" />}
              </button>
              <button
                onClick={() => handleFeedback(1)}
                className={`p-1 transition-colors cursor-pointer rounded ${
                  feedback === 'up' ? 'text-signal-green' : 'hover:text-ink-primary'
                }`}
                title="Mark as grounded (thumbs up)"
              >
                <ThumbsUp className="h-3 w-3" />
              </button>
              <button
                onClick={() => handleFeedback(-1)}
                className={`p-1 transition-colors cursor-pointer rounded ${
                  feedback === 'down' ? 'text-signal-rose' : 'hover:text-ink-primary'
                }`}
                title="Report ungrounded (thumbs down)"
              >
                <ThumbsDown className="h-3 w-3" />
              </button>
              <button
                onClick={() => setShowCorrection(!showCorrection)}
                className={`p-1 transition-colors cursor-pointer rounded ${
                  showCorrection ? 'text-signal-amber' : 'hover:text-ink-primary'
                }`}
                title="Submit expert correction for LoRA training"
              >
                <Edit3 className="h-3 w-3" />
              </button>
            </div>
          )}
        </div>

        {/* Inline Expert Correction Panel */}
        {showCorrection && (
          <div className="p-3 bg-surface-base border border-signal-amber/30 rounded space-y-2 text-xs">
            <div className="flex items-center justify-between text-[11px] font-mono text-signal-amber">
              <span>EXPERT GROUND-TRUTH ANNOTATION (SOVEREIGN FLYWHEEL)</span>
              {correctionSaved && <span className="text-signal-green">Saved to Training Ledger ✓</span>}
            </div>
            <textarea
              value={correctionText}
              onChange={(e) => setCorrectionText(e.target.value)}
              placeholder="Enter verified correct response to train local LoRA adapter..."
              rows={3}
              className="w-full bg-surface-panel border border-surface-border rounded p-2 text-xs font-mono text-ink-primary placeholder-ink-muted focus:outline-none focus:border-signal-amber"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowCorrection(false)}
                className="px-2.5 py-1 text-[11px] text-ink-muted hover:text-ink-primary cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveCorrection}
                className="px-3 py-1 bg-signal-amber text-surface-base font-semibold rounded text-[11px] hover:bg-amber-400 cursor-pointer"
              >
                Save Correction
              </button>
            </div>
          </div>
        )}

        {/* Message Prose / Markdown */}
        <div className="prose prose-invert prose-sm max-w-none text-ink-primary leading-relaxed font-sans">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({ children }) => <p className="mb-3 leading-7 text-[13.5px] text-ink-primary">{children}</p>,
              h1: ({ children }) => <h1 className="text-base font-bold text-ink-primary mt-4 mb-2 tracking-tight">{children}</h1>,
              h2: ({ children }) => <h2 className="text-sm font-bold text-ink-primary mt-3 mb-2 tracking-tight">{children}</h2>,
              h3: ({ children }) => <h3 className="text-xs font-bold text-ink-secondary mt-2 mb-1 tracking-tight">{children}</h3>,
              ul: ({ children }) => <ul className="list-disc pl-4 space-y-1 my-2 text-ink-primary text-[13.5px]">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal pl-4 space-y-1 my-2 text-ink-primary text-[13.5px]">{children}</ol>,
              li: ({ children }) => <li className="leading-6">{children}</li>,
              code({ inline, className, children, ...props }: any) {
                return inline ? (
                  <code className="bg-surface-raised border border-surface-border text-ink-primary px-1.5 py-0.5 rounded text-[11px] font-mono" {...props}>
                    {children}
                  </code>
                ) : (
                  <div className="my-3 border border-surface-border rounded bg-surface-base overflow-hidden">
                    <pre className="p-3 overflow-x-auto text-xs font-mono text-ink-primary leading-relaxed">
                      <code {...props}>{children}</code>
                    </pre>
                  </div>
                );
              },
            }}
          >
            {message.content}
          </ReactMarkdown>

          {message.isStreaming && (
            <span className="inline-block w-1.5 h-3.5 ml-1 bg-signal-green animate-pulse align-middle" />
          )}
        </div>

        {/* Verified Citations Footnotes */}
        {message.citations && message.citations.length > 0 && (
          <div className="pt-3 border-t border-surface-border/60 space-y-1.5">
            <div className="font-mono text-[10px] text-ink-muted uppercase tracking-wider">
              Grounded Sources ({message.citations.length})
            </div>
            <div className="flex flex-wrap gap-1.5">
              {message.citations.map((c) => (
                <button
                  key={c.citation_id}
                  onClick={() => onSelectCitation(c)}
                  className="inline-flex items-center gap-1.5 bg-surface-raised hover:bg-surface-hover border border-surface-border hover:border-ink-faint px-2 py-1 rounded text-[11px] font-mono transition-colors cursor-pointer group text-left"
                >
                  <span className="text-signal-green font-bold">[{c.citation_id}]</span>
                  <span className="text-ink-secondary group-hover:text-ink-primary truncate max-w-[150px]">
                    {c.filename}
                  </span>
                  <span className="text-ink-muted">p.{c.page_number}</span>
                  <ArrowUpRight className="h-3 w-3 text-ink-muted group-hover:text-ink-primary shrink-0" />
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Latency & Telemetry */}
        {isAssistant && message.latency_ms && (
          <LatencyBreakdownBadge latency={message.latency_ms} />
        )}
      </div>
    </article>
  );
};
