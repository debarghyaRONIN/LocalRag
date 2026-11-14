import React, { useState } from 'react';
import { X, Copy, Check } from 'lucide-react';
import type { Citation } from '../types';

interface CitationDrawerProps {
  citation: Citation | null;
  onClose: () => void;
}

export const CitationDrawer: React.FC<CitationDrawerProps> = ({ citation, onClose }) => {
  const [copiedQuote, setCopiedQuote] = useState(false);
  const [copiedParent, setCopiedParent] = useState(false);

  if (!citation) return null;

  const scorePct = Math.min(100, Math.round(citation.relevance_score * 100));

  const handleCopyQuote = () => {
    navigator.clipboard.writeText(citation.exact_quote);
    setCopiedQuote(true);
    setTimeout(() => setCopiedQuote(false), 2000);
  };

  const handleCopyParent = () => {
    if (citation.parent_content) {
      navigator.clipboard.writeText(citation.parent_content);
      setCopiedParent(true);
      setTimeout(() => setCopiedParent(false), 2000);
    }
  };

  return (
    <div className="fixed inset-y-0 right-0 w-[460px] max-w-full bg-surface-panel border-l border-surface-border shadow-2xl z-50 flex flex-col animate-in slide-in-from-right duration-200">
      {/* Dossier Header */}
      <div className="h-14 px-5 border-b border-surface-border flex items-center justify-between bg-surface-base select-none">
        <div className="flex items-center gap-2.5">
          <span className="font-mono text-xs font-bold text-signal-green">
            REF [{citation.citation_id}]
          </span>
          <span className="text-ink-muted text-xs font-mono">•</span>
          <span className="text-xs font-medium text-ink-primary truncate max-w-[240px]">
            {citation.filename}
          </span>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded text-ink-muted hover:text-ink-primary hover:bg-surface-raised transition-colors cursor-pointer"
          title="Close inspector (Esc)"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Dossier Meta Table */}
      <div className="border-b border-surface-border bg-surface-base/50 p-4 font-mono text-[11px] space-y-2 select-text">
        <div className="flex justify-between items-center text-ink-muted">
          <span>SOURCE FILE</span>
          <span className="text-ink-primary truncate max-w-[220px]" title={citation.filename}>
            {citation.filename}
          </span>
        </div>
        <div className="flex justify-between items-center text-ink-muted">
          <span>COORDINATE</span>
          <span className="text-ink-primary">Page {citation.page_number}</span>
        </div>
        <div className="flex justify-between items-center text-ink-muted">
          <span>RERANK CONFIDENCE</span>
          <span className="text-signal-green font-semibold tabular-nums">
            {citation.relevance_score.toFixed(3)} ({scorePct}%)
          </span>
        </div>
        <div className="flex justify-between items-center text-ink-muted text-[10px]">
          <span>CHUNK SHA</span>
          <span className="truncate max-w-[180px] text-ink-muted">{citation.chunk_id}</span>
        </div>
      </div>

      {/* Dossier Content Body */}
      <div className="flex-1 overflow-y-auto p-5 space-y-6">
        {/* Child Query Match Quote */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-[11px] font-mono uppercase tracking-wider text-ink-muted select-none">
            <span>Direct Passage Match</span>
            <button
              onClick={handleCopyQuote}
              className="inline-flex items-center gap-1 hover:text-ink-primary transition-colors cursor-pointer"
            >
              {copiedQuote ? <Check className="h-3 w-3 text-signal-green" /> : <Copy className="h-3 w-3" />}
              <span>{copiedQuote ? 'Copied' : 'Copy'}</span>
            </button>
          </div>
          <div className="p-3.5 bg-surface-base border border-surface-border rounded text-xs text-ink-primary font-mono leading-relaxed select-text">
            {citation.exact_quote}
          </div>
        </div>

        {/* Parent Context Section */}
        {citation.parent_content && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-[11px] font-mono uppercase tracking-wider text-ink-muted select-none">
              <span>Parent Context Window</span>
              <button
                onClick={handleCopyParent}
                className="inline-flex items-center gap-1 hover:text-ink-primary transition-colors cursor-pointer"
              >
                {copiedParent ? <Check className="h-3 w-3 text-signal-green" /> : <Copy className="h-3 w-3" />}
                <span>{copiedParent ? 'Copied' : 'Copy'}</span>
              </button>
            </div>
            <div className="p-4 bg-surface-base border border-surface-border rounded text-[13px] font-serif text-ink-secondary leading-relaxed select-text max-h-80 overflow-y-auto">
              {citation.parent_content}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
