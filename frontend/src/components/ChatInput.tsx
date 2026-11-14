import React, { useState, useRef, useEffect } from 'react';
import { ArrowUp, Square, SlidersHorizontal, ChevronUp, ChevronDown, Paperclip, X, FileText, Cpu } from 'lucide-react';

interface AttachedFile {
  file: File;
  name: string;
  size: number;
}

interface ChatInputProps {
  onSendMessage: (text: string, topK: number, minScore: number, attachedFile?: File) => void;
  onStopStreaming: () => void;
  isStreaming: boolean;
  disabled?: boolean;
  activeModel?: string;
  onChangeModel?: (model: string) => void;
  onOpenModelSelector?: () => void;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSendMessage,
  onStopStreaming,
  isStreaming,
  disabled = false,
  activeModel,
  onChangeModel,
  onOpenModelSelector,
}) => {
  const [text, setText] = useState('');
  const [topK, setTopK] = useState(5);
  const [minScore, setMinScore] = useState(0.20);
  const [showConfig, setShowConfig] = useState(false);
  const [attachedFile, setAttachedFile] = useState<AttachedFile | null>(null);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isStreaming) {
      textareaRef.current?.focus();
    }
  }, [isStreaming]);

  // Auto-resize textarea height
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 220)}px`;
    }
  }, [text]);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if ((!text.trim() && !attachedFile) || isStreaming || disabled) return;
    onSendMessage(text.trim() || 'Analyze attached document', topK, minScore, attachedFile?.file);
    setText('');
    setAttachedFile(null);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const f = e.target.files[0];
      setAttachedFile({ file: f, name: f.name, size: f.size });
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div
      style={{
        padding: '16px clamp(16px, 4vw, 32px) 24px',
        maxWidth: '850px',
        margin: '0 auto',
        width: '100%',
        boxSizing: 'border-box',
      }}
    >
      {/* Tuning Controls Accordion */}
      {showConfig && (
        <div
          style={{
            background: 'var(--color-surface)',
            border: '1px solid var(--color-surface-raised)',
            borderRadius: 'var(--radius-md)',
            padding: '10px 16px',
            marginBottom: '10px',
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            gap: '20px',
            fontSize: '12px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>Passages (Top-K):</span>
            <input
              type="range"
              min="1"
              max="10"
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
              style={{ width: '80px', accentColor: 'var(--color-accent)' }}
            />
            <span style={{ fontWeight: 600, color: 'var(--color-accent)' }}>{topK}</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>Confidence Cutoff:</span>
            <input
              type="range"
              min="0.0"
              max="0.8"
              step="0.05"
              value={minScore}
              onChange={(e) => setMinScore(Number(e.target.value))}
              style={{ width: '80px', accentColor: 'var(--color-accent)' }}
            />
            <span style={{ fontWeight: 600, color: 'var(--color-accent)' }}>{minScore.toFixed(2)}</span>
          </div>

          {/* Active Model Custom Input Field */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ color: 'color-mix(in srgb, var(--color-text) 60%, transparent)', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <Cpu size={12} /> Model:
            </span>
            <input
              type="text"
              value={activeModel || ''}
              onChange={(e) => onChangeModel?.(e.target.value)}
              placeholder="e.g. llama3.2:latest"
              style={{
                background: 'var(--color-bg)',
                border: '1px solid color-mix(in srgb, var(--color-text) 16%, transparent)',
                borderRadius: '6px',
                padding: '3px 8px',
                fontSize: '11.5px',
                fontFamily: 'monospace',
                color: 'var(--color-accent)',
                width: '140px',
                outline: 'none',
              }}
              title="Type exact model name (e.g. llama3.2:latest, gemma4:latest)"
            />
            {onOpenModelSelector && (
              <button
                type="button"
                onClick={onOpenModelSelector}
                className="btn btn-ghost"
                style={{ fontSize: '11px', padding: '2px 6px', color: 'var(--color-accent)' }}
                title="Browse & select installed local models"
              >
                Browse...
              </button>
            )}
          </div>

          <div style={{ marginLeft: 'auto', fontSize: '11px', color: 'color-mix(in srgb, var(--color-text) 45%, transparent)' }}>
            BM25 + BGE-M3 Dense + Cross-Encoder
          </div>
        </div>
      )}

      {/* Floating Card Container */}
      <div
        style={{
          background: 'var(--color-surface)',
          border: '1px solid color-mix(in srgb, var(--color-text) 14%, transparent)',
          borderRadius: '16px',
          boxShadow: '0 8px 30px rgba(0, 0, 0, 0.35)',
          display: 'flex',
          flexDirection: 'column',
          transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
          overflow: 'hidden',
        }}
      >
        {/* Attached File Chip */}
        {attachedFile && (
          <div style={{ padding: '10px 14px 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                background: 'color-mix(in srgb, var(--color-accent) 15%, transparent)',
                border: '1px solid color-mix(in srgb, var(--color-accent) 30%, transparent)',
                borderRadius: '8px',
                padding: '4px 8px',
                fontSize: '12px',
                color: 'var(--color-accent-200)',
              }}
            >
              <FileText size={13} style={{ color: 'var(--color-accent)' }} />
              <span style={{ fontWeight: 500, maxWidth: '240px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {attachedFile.name}
              </span>
              <span style={{ fontSize: '10.5px', color: 'color-mix(in srgb, var(--color-text) 50%, transparent)' }}>
                ({formatFileSize(attachedFile.size)})
              </span>
              <button
                type="button"
                onClick={() => setAttachedFile(null)}
                style={{ all: 'unset', cursor: 'pointer', padding: '2px', display: 'flex', alignItems: 'center' }}
                title="Remove attachment"
              >
                <X size={12} />
              </button>
            </div>
          </div>
        )}

        {/* Text Input Area */}
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder={
            disabled
              ? 'Local runtime disconnected...'
              : 'Message Sealed or ask a question about your knowledge corpus...'
          }
          rows={1}
          style={{
            width: '100%',
            background: 'transparent',
            border: 'none',
            outline: 'none',
            padding: '14px 18px 8px',
            fontSize: '14.5px',
            color: 'var(--color-text)',
            fontFamily: 'inherit',
            lineHeight: 1.55,
            resize: 'none',
            boxSizing: 'border-box',
            minHeight: '44px',
            maxHeight: '220px',
          }}
        />

        {/* Bottom Toolbar & Controls */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '4px 12px 10px',
          }}
        >
          {/* Left Actions: Attachment + Tuning */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <input
              ref={fileInputRef}
              type="file"
              style={{ display: 'none' }}
              onChange={handleFileSelected}
            />
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => fileInputRef.current?.click()}
              title="Attach document to consultation"
              style={{ padding: '6px', borderRadius: '8px', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}
            >
              <Paperclip size={16} />
            </button>

            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setShowConfig(!showConfig)}
              style={{
                fontSize: '11.5px',
                padding: '4px 8px',
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                color: showConfig ? 'var(--color-accent)' : 'color-mix(in srgb, var(--color-text) 55%, transparent)',
              }}
            >
              <SlidersHorizontal size={13} />
              <span>Tuning</span>
              {showConfig ? <ChevronDown size={11} /> : <ChevronUp size={11} />}
            </button>
          </div>

          {/* Right Actions: Hints + Send Button */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontSize: '11px', color: 'color-mix(in srgb, var(--color-text) 35%, transparent)' }}>
              ⏎ send · Shift+⏎ newline
            </span>

            {isStreaming ? (
              <button
                type="button"
                onClick={onStopStreaming}
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '16px',
                  background: 'var(--color-accent)',
                  border: 'none',
                  color: '#ffffff',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  cursor: 'pointer',
                  transition: 'opacity 0.15s ease',
                }}
                title="Stop generation"
              >
                <Square size={13} fill="currentColor" />
              </button>
            ) : (
              <button
                type="button"
                onClick={() => handleSubmit()}
                disabled={(!text.trim() && !attachedFile) || disabled}
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '16px',
                  background: (!text.trim() && !attachedFile) || disabled
                    ? 'color-mix(in srgb, var(--color-text) 10%, transparent)'
                    : 'var(--color-accent)',
                  border: 'none',
                  color: (!text.trim() && !attachedFile) || disabled
                    ? 'color-mix(in srgb, var(--color-text) 40%, transparent)'
                    : '#ffffff',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  cursor: (!text.trim() && !attachedFile) || disabled ? 'not-allowed' : 'pointer',
                  transition: 'all 0.15s ease',
                }}
                title="Send message"
              >
                <ArrowUp size={16} strokeWidth={2.4} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
