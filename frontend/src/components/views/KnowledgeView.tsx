import React, { useState } from 'react';
import { Plus, FileText, Trash2, Layers, X, Shield, Hash } from 'lucide-react';
import type { DocumentItem } from '../../types';
import { deleteDocument, purgeAllDocuments, getDocumentChunks } from '../../services/api';

interface KnowledgeViewProps {
  documents: DocumentItem[];
  onOpenUpload: () => void;
  onRefresh: () => void;
}

interface ChunkRecord {
  id: string;
  chunk_id: string;
  parent_id?: string;
  content: string;
  token_count?: number;
  page_number?: number;
  clearance_level?: number;
  metadata?: any;
}

export const KnowledgeView: React.FC<KnowledgeViewProps> = ({ documents, onOpenUpload, onRefresh }) => {
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [confirmPurgeAll, setConfirmPurgeAll] = useState<boolean>(false);
  const [isPurgingAll, setIsPurgingAll] = useState<boolean>(false);
  const [selectedDoc, setSelectedDoc] = useState<DocumentItem | null>(null);
  const [inspectChunks, setInspectChunks] = useState<ChunkRecord[]>([]);
  const [loadingChunks, setLoadingChunks] = useState<boolean>(false);
  const [chunkError, setChunkError] = useState<string | null>(null);

  const handleInspectChunks = async (doc: DocumentItem) => {
    setSelectedDoc(doc);
    setLoadingChunks(true);
    setChunkError(null);
    try {
      const chunks = await getDocumentChunks(doc.doc_id);
      setInspectChunks(chunks);
    } catch (err: any) {
      console.error('Failed to load chunks:', err);
      setChunkError(err?.message || 'Could not fetch document chunks');
    } finally {
      setLoadingChunks(false);
    }
  };

  const executeDelete = async (docId: string) => {
    setDeletingId(docId);
    try {
      await deleteDocument(docId);
      setConfirmDeleteId(null);
      onRefresh();
    } catch (err) {
      console.error('Failed to delete doc:', err);
    } finally {
      setDeletingId(null);
    }
  };

  const handlePurgeAll = async () => {
    setIsPurgingAll(true);
    try {
      await purgeAllDocuments();
      setConfirmPurgeAll(false);
      onRefresh();
    } catch (err) {
      console.error('Failed to purge corpus:', err);
    } finally {
      setIsPurgingAll(false);
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const getClearanceLabel = (level?: number) => {
    switch (level) {
      case 4: return 'Top Secret (L4)';
      case 3: return 'Confidential (L3)';
      case 2: return 'Internal (L2)';
      default: return 'Public (L1)';
    }
  };

  return (
    <div style={{ padding: '28px clamp(20px, 3vw, 40px) 48px', maxWidth: '1100px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: '16px', flexWrap: 'wrap' }}>
        <div>
          <span style={{ fontSize: '11px', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-accent)' }}>
            Retrieval
          </span>
          <h1 style={{ fontFamily: 'var(--font-heading)', fontWeight: 'var(--font-heading-weight)', fontSize: '26px', margin: '8px 0 0' }}>
            Document sets
          </h1>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {documents.length > 0 && (
            confirmPurgeAll ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <button
                  type="button"
                  onClick={handlePurgeAll}
                  disabled={isPurgingAll}
                  className="btn"
                  style={{
                    padding: '6px 12px',
                    fontSize: '12px',
                    backgroundColor: 'var(--color-signal-rose, #ef4444)',
                    color: '#fff',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: 'pointer',
                  }}
                >
                  {isPurgingAll ? 'Purging All...' : 'Confirm Purge All'}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmPurgeAll(false)}
                  className="btn btn-secondary"
                  style={{ padding: '6px 10px', fontSize: '12px' }}
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setConfirmPurgeAll(true)}
                title="Wipe entire document corpus and vector index"
                style={{
                  color: 'var(--color-signal-rose, #ef4444)',
                  borderColor: 'color-mix(in srgb, #ef4444 30%, transparent)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                }}
              >
                <Trash2 size={13} />
                <span>Purge Corpus</span>
              </button>
            )
          )}
          <button type="button" className="btn btn-primary" onClick={onOpenUpload}>
            <Plus size={14} /> Add document set
          </button>
        </div>
      </div>

      {/* Table */}
      <table className="table" style={{ marginTop: '24px' }}>
        <thead>
          <tr>
            <th>Set</th>
            <th>Documents / Chunks</th>
            <th>Last indexed</th>
            <th>Access</th>
            <th>Status</th>
            <th style={{ width: '40px' }}></th>
          </tr>
        </thead>
        <tbody>
          {documents.length === 0 ? (
            <tr>
              <td colSpan={6} style={{ padding: '36px', textAlign: 'center', color: 'color-mix(in srgb, var(--color-text) 50%, transparent)' }}>
                No document sets indexed yet. Click "Add document set" to ingest PDFs, Office docs, codebases, or scanned records.
              </td>
            </tr>
          ) : (
            documents.map((d) => (
              <tr key={d.doc_id}>
                <td style={{ fontWeight: 500 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <FileText size={15} style={{ color: 'var(--color-accent)' }} />
                    <span>{d.filename}</span>
                  </div>
                </td>
                <td style={{ color: 'color-mix(in srgb, var(--color-text) 70%, transparent)' }}>
                  {d.total_child_chunks || d.total_parent_chunks || 1} chunks · {formatFileSize(d.file_size_bytes)}
                </td>
                <td style={{ color: 'color-mix(in srgb, var(--color-text) 60%, transparent)', fontSize: '12.5px' }}>
                  {new Date(d.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </td>
                <td>
                  <span className="tag tag-neutral" style={{ fontSize: '11px' }}>
                    {getClearanceLabel(d.clearance_level)}
                  </span>
                </td>
                <td>
                  <span className="tag tag-accent">Indexed</span>
                </td>
                <td style={{ textAlign: 'right' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '6px' }}>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => handleInspectChunks(d)}
                      title="Inspect AST & Vector Chunks"
                      style={{ padding: '4px 8px', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}
                    >
                      <Layers size={12} />
                      <span>Chunks</span>
                    </button>
                    {confirmDeleteId === d.doc_id ? (
                      <div style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                        <button
                          type="button"
                          className="btn"
                          onClick={() => executeDelete(d.doc_id)}
                          disabled={deletingId === d.doc_id}
                          style={{
                            padding: '3px 8px',
                            fontSize: '11px',
                            backgroundColor: 'var(--color-signal-rose, #ef4444)',
                            color: '#fff',
                            border: 'none',
                            borderRadius: '4px',
                            cursor: 'pointer',
                          }}
                        >
                          {deletingId === d.doc_id ? 'Purging...' : 'Delete'}
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost"
                          onClick={() => setConfirmDeleteId(null)}
                          style={{ padding: '3px 6px', fontSize: '11px' }}
                          title="Cancel"
                        >
                          ✕
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="btn btn-ghost"
                        onClick={() => setConfirmDeleteId(d.doc_id)}
                        disabled={deletingId === d.doc_id}
                        title="Remove from index"
                        style={{ padding: '4px', color: 'color-mix(in srgb, var(--color-text) 50%, transparent)' }}
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <p style={{ margin: '16px 0 0', fontSize: '12.5px', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>
        Embeddings and inverted lexical index stored locally in Qdrant and SQLite. Every answer cites its sources.
      </p>

      {/* Chunk & AST Visualizer Modal */}
      {selectedDoc && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.75)',
            backdropFilter: 'blur(4px)',
            zIndex: 1000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24px',
          }}
          onClick={() => setSelectedDoc(null)}
        >
          <div
            style={{
              backgroundColor: 'var(--color-surface)',
              border: '1px solid var(--color-surface-raised)',
              borderRadius: 'var(--radius-lg)',
              width: '100%',
              maxWidth: '850px',
              maxHeight: '85vh',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '0 20px 40px rgba(0,0,0,0.5)',
              overflow: 'hidden',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div
              style={{
                padding: '16px 20px',
                borderBottom: '1px solid var(--color-surface-raised)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Layers size={16} style={{ color: 'var(--color-accent)' }} />
                  <span style={{ fontWeight: 600, fontSize: '15px' }}>Chunk & AST Inspector</span>
                  <span className="tag tag-accent" style={{ fontSize: '10px' }}>
                    {inspectChunks.length} Chunks
                  </span>
                </div>
                <div style={{ fontSize: '12px', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)', marginTop: '2px' }}>
                  {selectedDoc.filename} · {getClearanceLabel(selectedDoc.clearance_level)}
                </div>
              </div>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setSelectedDoc(null)}
                style={{ padding: '6px' }}
              >
                <X size={16} />
              </button>
            </div>

            {/* Modal Body */}
            <div style={{ padding: '20px', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {loadingChunks ? (
                <div style={{ textAlign: 'center', padding: '40px', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>
                  Loading chunk hierarchy and embeddings payload...
                </div>
              ) : chunkError ? (
                <div style={{ padding: '16px', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.3)', borderRadius: '6px', color: '#f87171', fontSize: '13px' }}>
                  {chunkError}
                </div>
              ) : inspectChunks.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '40px', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>
                  No individual chunks recorded for this item.
                </div>
              ) : (
                inspectChunks.map((chunk, idx) => (
                  <div
                    key={chunk.id || idx}
                    style={{
                      background: 'color-mix(in srgb, var(--color-surface-raised) 50%, transparent)',
                      border: '1px solid var(--color-surface-raised)',
                      borderRadius: 'var(--radius-md)',
                      padding: '14px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '8px',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--color-accent)', display: 'flex', alignItems: 'center', gap: '2px' }}>
                          <Hash size={12} /> Chunk {idx + 1}
                        </span>
                        <span style={{ fontSize: '11px', fontFamily: 'monospace', color: 'color-mix(in srgb, var(--color-text) 50%, transparent)' }}>
                          ID: {(chunk.chunk_id || chunk.id).slice(0, 12)}...
                        </span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        {chunk.page_number && (
                          <span className="tag tag-neutral" style={{ fontSize: '10px' }}>
                            Page {chunk.page_number}
                          </span>
                        )}
                        {chunk.token_count && (
                          <span className="tag tag-neutral" style={{ fontSize: '10px' }}>
                            {chunk.token_count} tokens
                          </span>
                        )}
                        <span className="tag tag-neutral" style={{ fontSize: '10px', display: 'flex', alignItems: 'center', gap: '3px' }}>
                          <Shield size={10} /> L{chunk.clearance_level || selectedDoc.clearance_level || 1}
                        </span>
                      </div>
                    </div>
                    <div
                      style={{
                        fontSize: '12.5px',
                        lineHeight: 1.55,
                        color: 'var(--color-text)',
                        background: 'rgba(0, 0, 0, 0.25)',
                        padding: '10px',
                        borderRadius: '4px',
                        fontFamily: selectedDoc.filename.match(/\.(cpp|hpp|c|h|py|js|ts|go|rs|json|yaml)$/i) ? 'monospace' : 'inherit',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        maxHeight: '180px',
                        overflowY: 'auto',
                      }}
                    >
                      {chunk.content}
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* Modal Footer */}
            <div
              style={{
                padding: '12px 20px',
                borderTop: '1px solid var(--color-surface-raised)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                background: 'rgba(0,0,0,0.1)',
              }}
            >
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setSelectedDoc(null)}
              >
                Close Inspector
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
