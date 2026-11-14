import React, { useState } from 'react';
import { Code, Eye, Copy, Check, Download, X, Sparkles } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ArtifactItem } from '../types';

interface ArtifactPanelProps {
  artifact: ArtifactItem | null;
  onClose: () => void;
}

export const ArtifactPanel: React.FC<ArtifactPanelProps> = ({ artifact, onClose }) => {
  const [activeTab, setActiveTab] = useState<'preview' | 'code'>('preview');
  const [copied, setCopied] = useState(false);

  if (!artifact) return null;

  const isPreviewable = ['html', 'svg', 'markdown'].includes(artifact.type) || 
    (artifact.language && ['html', 'svg', 'markdown', 'md'].includes(artifact.language.toLowerCase()));

  const handleCopy = () => {
    navigator.clipboard.writeText(artifact.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const ext = artifact.language || (artifact.type === 'html' ? 'html' : artifact.type === 'svg' ? 'svg' : 'txt');
    const blob = new Blob([artifact.content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${artifact.title.replace(/\s+/g, '_').toLowerCase()}.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <aside
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: 'var(--color-surface)',
        borderLeft: '1px solid var(--color-surface-raised)',
        boxShadow: '-4px 0 20px rgba(0,0,0,0.35)',
        width: '100%',
        minWidth: 0,
      }}
    >
      {/* Top Action Bar */}
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid var(--color-surface-raised)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px',
          background: 'color-mix(in srgb, var(--color-bg) 70%, transparent)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
          <div
            style={{
              width: '26px',
              height: '26px',
              borderRadius: '6px',
              background: 'color-mix(in srgb, var(--color-accent) 20%, transparent)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--color-accent)',
              flexShrink: 0,
            }}
          >
            <Sparkles size={14} />
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: '13px', color: 'var(--color-text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {artifact.title}
            </div>
            <div style={{ fontSize: '11px', color: 'color-mix(in srgb, var(--color-text) 50%, transparent)', textTransform: 'uppercase' }}>
              {artifact.language || artifact.type} · Sovereign Artifact
            </div>
          </div>
        </div>

        {/* Tab Controls (Preview / Code) */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          {isPreviewable && (
            <div
              style={{
                display: 'flex',
                background: 'rgba(0,0,0,0.3)',
                padding: '2px',
                borderRadius: '6px',
                border: '1px solid var(--color-divider)',
              }}
            >
              <button
                type="button"
                onClick={() => setActiveTab('preview')}
                style={{
                  all: 'unset',
                  cursor: 'pointer',
                  padding: '3px 8px',
                  borderRadius: '4px',
                  fontSize: '11px',
                  fontWeight: 500,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  background: activeTab === 'preview' ? 'var(--color-surface-raised)' : 'transparent',
                  color: activeTab === 'preview' ? 'var(--color-text)' : 'color-mix(in srgb, var(--color-text) 60%, transparent)',
                }}
              >
                <Eye size={12} />
                <span>Preview</span>
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('code')}
                style={{
                  all: 'unset',
                  cursor: 'pointer',
                  padding: '3px 8px',
                  borderRadius: '4px',
                  fontSize: '11px',
                  fontWeight: 500,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  background: activeTab === 'code' ? 'var(--color-surface-raised)' : 'transparent',
                  color: activeTab === 'code' ? 'var(--color-text)' : 'color-mix(in srgb, var(--color-text) 60%, transparent)',
                }}
              >
                <Code size={12} />
                <span>Code</span>
              </button>
            </div>
          )}

          <button
            type="button"
            className="btn btn-ghost"
            onClick={handleCopy}
            title="Copy artifact content"
            style={{ padding: '6px' }}
          >
            {copied ? <Check size={14} style={{ color: '#4ade80' }} /> : <Copy size={14} />}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={handleDownload}
            title="Download file"
            style={{ padding: '6px' }}
          >
            <Download size={14} />
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={onClose}
            title="Close artifact"
            style={{ padding: '6px' }}
          >
            <X size={15} />
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {activeTab === 'preview' && isPreviewable ? (
          artifact.type === 'svg' || artifact.language === 'svg' ? (
            <div
              style={{
                padding: '24px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                minHeight: '100%',
                background: '#ffffff',
                borderRadius: '0 0 var(--radius-md) var(--radius-md)',
              }}
              dangerouslySetInnerHTML={{ __html: artifact.content }}
            />
          ) : artifact.type === 'html' || artifact.language === 'html' ? (
            <iframe
              title={artifact.title}
              srcDoc={artifact.content}
              sandbox="allow-scripts"
              style={{
                width: '100%',
                height: '100%',
                border: 'none',
                background: '#ffffff',
              }}
            />
          ) : (
            <div style={{ padding: '24px', lineHeight: 1.65, fontSize: '14px', color: 'var(--color-text)' }}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {artifact.content}
              </ReactMarkdown>
            </div>
          )
        ) : (
          <div style={{ position: 'relative', height: '100%' }}>
            <pre
              style={{
                margin: 0,
                padding: '16px',
                fontSize: '12.5px',
                fontFamily: 'JetBrains Mono, Menlo, monospace',
                lineHeight: 1.6,
                color: '#e2e8f0',
                background: '#11121d',
                minHeight: '100%',
                overflowX: 'auto',
                boxSizing: 'border-box',
              }}
            >
              <code>{artifact.content}</code>
            </pre>
          </div>
        )}
      </div>
    </aside>
  );
};
