import React, { useState, useRef, useMemo } from 'react';
import {
  Search,
  UploadCloud,
  Trash2,
  FileText,
  Code,
  Globe,
  FileCode,
  Layers,
  CheckCircle2,
  AlertCircle,
  Loader2,
  RefreshCw,
  FolderOpen,
} from 'lucide-react';
import type { DocumentItem } from '../../types';
import { uploadDocument, deleteDocument, purgeAllDocuments } from '../../services/api';

interface KnowledgeLibraryViewProps {
  documents: DocumentItem[];
  onRefreshDocuments: () => void;
  onNavigateToIndexing?: () => void;
}

type FileTypeFilter = 'all' | 'pdf' | 'code' | 'web' | 'text';

export const KnowledgeLibraryView: React.FC<KnowledgeLibraryViewProps> = ({
  documents,
  onRefreshDocuments,
  onNavigateToIndexing,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [typeFilter, setTypeFilter] = useState<FileTypeFilter>('all');
  const [clearanceFilter, setClearanceFilter] = useState<number | 'all'>('all');
  const [isUploading, setIsUploading] = useState(false);
  const [uploadClearance, setUploadClearance] = useState<number>(1);
  const [statusMessage, setStatusMessage] = useState<{ text: string; isError?: boolean } | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmPurgeAll, setConfirmPurgeAll] = useState(false);
  const [isPurgingAll, setIsPurgingAll] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const detectType = (filename: string, mime?: string): 'pdf' | 'code' | 'web' | 'text' | 'other' => {
    const ext = filename.split('.').pop()?.toLowerCase() || '';
    if (ext === 'pdf' || mime?.includes('pdf')) return 'pdf';
    if (['py', 'ts', 'js', 'jsx', 'tsx', 'go', 'rs', 'java', 'cpp', 'c', 'h', 'cs', 'php'].includes(ext)) {
      return 'code';
    }
    if (['html', 'htm', 'xhtml'].includes(ext) || mime?.includes('html')) return 'web';
    if (['txt', 'md', 'markdown', 'json', 'yaml', 'yml', 'csv'].includes(ext)) return 'text';
    return 'other';
  };

  const filteredDocuments = useMemo(() => {
    return documents.filter((doc) => {
      // Search term
      if (searchTerm && !doc.filename.toLowerCase().includes(searchTerm.toLowerCase())) {
        return false;
      }

      // Clearance filter
      if (clearanceFilter !== 'all') {
        const docClearance = doc.clearance_level ?? 1;
        if (docClearance !== clearanceFilter) return false;
      }

      // File type filter
      if (typeFilter !== 'all') {
        const detected = detectType(doc.filename, doc.mime_type);
        if (typeFilter === 'code' && detected !== 'code') return false;
        if (typeFilter === 'pdf' && detected !== 'pdf') return false;
        if (typeFilter === 'web' && detected !== 'web') return false;
        if (typeFilter === 'text' && detected !== 'text') return false;
      }

      return true;
    });
  }, [documents, searchTerm, clearanceFilter, typeFilter]);

  const handleFileUpload = async (file: File) => {
    try {
      setIsUploading(true);
      setStatusMessage({ text: `Parsing "${file.name}" with layout & syntax awareness...` });
      await uploadDocument(file, uploadClearance);
      setStatusMessage({ text: `Successfully indexed "${file.name}" under Clearance L${uploadClearance}.` });
      onRefreshDocuments();
    } catch (err: any) {
      setStatusMessage({ text: err.message || 'Ingestion failed.', isError: true });
    } finally {
      setIsUploading(false);
    }
  };

  const executeDelete = async (docId: string, filename: string) => {
    setDeletingId(docId);
    try {
      await deleteDocument(docId);
      setConfirmDeleteId(null);
      setStatusMessage({ text: `Deleted "${filename}" and purged all associated vectors.` });
      onRefreshDocuments();
    } catch (err: any) {
      setStatusMessage({ text: err.message || 'Failed to delete document.', isError: true });
    } finally {
      setDeletingId(null);
    }
  };

  const handlePurgeAll = async () => {
    setIsPurgingAll(true);
    try {
      const res = await purgeAllDocuments();
      setConfirmPurgeAll(false);
      setStatusMessage({ text: `Entire corpus purged: wiped ${res.deleted_count} documents, all vector embeddings, and storage.` });
      onRefreshDocuments();
    } catch (err: any) {
      setStatusMessage({ text: err.message || 'Failed to purge corpus.', isError: true });
    } finally {
      setIsPurgingAll(false);
    }
  };

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const totalBytes = documents.reduce((acc, d) => acc + (d.file_size_bytes || 0), 0);
  const totalChunks = documents.reduce((acc, d) => acc + (d.total_child_chunks || 0), 0);
  const totalParentChunks = documents.reduce((acc, d) => acc + (d.total_parent_chunks || 0), 0);

  const getTypeBadge = (filename: string, mime?: string) => {
    const type = detectType(filename, mime);
    switch (type) {
      case 'pdf':
        return (
          <span className="inline-flex items-center gap-1 font-mono text-[10px] text-signal-rose bg-signal-rose/10 border border-signal-rose/30 px-1.5 py-0.5 rounded">
            <FileText className="h-3 w-3" />
            PDF
          </span>
        );
      case 'code':
        return (
          <span className="inline-flex items-center gap-1 font-mono text-[10px] text-signal-sky bg-signal-sky/10 border border-signal-sky/30 px-1.5 py-0.5 rounded">
            <Code className="h-3 w-3" />
            CODE
          </span>
        );
      case 'web':
        return (
          <span className="inline-flex items-center gap-1 font-mono text-[10px] text-signal-amber bg-signal-amber/10 border border-signal-amber/30 px-1.5 py-0.5 rounded">
            <Globe className="h-3 w-3" />
            WEB
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 font-mono text-[10px] text-ink-secondary bg-surface-raised border border-surface-border px-1.5 py-0.5 rounded">
            <FileCode className="h-3 w-3" />
            TEXT
          </span>
        );
    }
  };

  const getClearanceBadge = (level: number = 1) => {
    switch (level) {
      case 4:
        return (
          <span className="font-mono text-[10px] text-signal-rose bg-signal-rose/10 border border-signal-rose/30 px-1.5 py-0.5 rounded font-bold">
            L4 TOP SECRET
          </span>
        );
      case 3:
        return (
          <span className="font-mono text-[10px] text-signal-amber bg-signal-amber/10 border border-signal-amber/30 px-1.5 py-0.5 rounded font-medium">
            L3 CONFIDENTIAL
          </span>
        );
      case 2:
        return (
          <span className="font-mono text-[10px] text-signal-sky bg-signal-sky/10 border border-signal-sky/30 px-1.5 py-0.5 rounded font-medium">
            L2 INTERNAL
          </span>
        );
      default:
        return (
          <span className="font-mono text-[10px] text-signal-green bg-signal-green/10 border border-signal-green/30 px-1.5 py-0.5 rounded font-medium">
            L1 PUBLIC
          </span>
        );
    }
  };

  return (
    <div className="flex-1 overflow-y-auto bg-surface-base p-6 space-y-6">
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => {
          if (e.target.files && e.target.files[0]) {
            handleFileUpload(e.target.files[0]);
          }
        }}
      />

      {/* View Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-border pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] text-signal-green uppercase tracking-wider font-semibold">
              SOVEREIGN KNOWLEDGE VAULT
            </span>
            <span className="text-surface-border">•</span>
            <span className="font-mono text-[10px] text-ink-muted">
              {documents.length} FILES · {totalChunks.toLocaleString()} VECTORS · {formatBytes(totalBytes)}
            </span>
          </div>
          <h1 className="text-xl font-bold tracking-tight text-ink-primary mt-1">
            Knowledge Corpus Ledger
          </h1>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-3">
          {/* Clearance Selector for Upload */}
          <div className="flex items-center gap-1 bg-surface-panel border border-surface-border rounded p-1">
            <span className="font-mono text-[10px] text-ink-muted px-1.5 uppercase">Ingest As:</span>
            {[1, 2, 3, 4].map((lvl) => (
              <button
                key={lvl}
                onClick={() => setUploadClearance(lvl)}
                className={`px-2 py-0.5 text-[10px] font-mono rounded cursor-pointer transition-colors ${
                  uploadClearance === lvl
                    ? 'bg-ink-primary text-surface-base font-bold'
                    : 'text-ink-secondary hover:text-ink-primary'
                }`}
              >
                L{lvl}
              </button>
            ))}
          </div>

          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading}
            className="flex items-center gap-1.5 bg-ink-primary hover:bg-white text-surface-base font-semibold px-3 py-1.5 rounded text-xs transition-colors cursor-pointer disabled:opacity-50"
          >
            {isUploading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <UploadCloud className="h-3.5 w-3.5" />
            )}
            <span>Ingest Document</span>
          </button>

          {documents.length > 0 && (
            confirmPurgeAll ? (
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={handlePurgeAll}
                  disabled={isPurgingAll}
                  className="bg-signal-rose hover:bg-red-600 text-white font-mono text-xs px-2.5 py-1.5 rounded transition-colors cursor-pointer"
                >
                  {isPurgingAll ? 'Purging...' : 'Confirm Wipe'}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmPurgeAll(false)}
                  className="bg-surface-raised hover:bg-surface-hover text-ink-muted hover:text-ink-primary font-mono text-xs px-2 py-1.5 rounded border border-surface-border transition-colors cursor-pointer"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmPurgeAll(true)}
                className="flex items-center gap-1.5 bg-surface-raised hover:bg-signal-rose/10 text-signal-rose border border-signal-rose/30 hover:border-signal-rose px-2.5 py-1.5 rounded text-xs font-mono transition-colors cursor-pointer"
                title="Purge all documents, vectors, and physical files"
              >
                <Trash2 className="h-3.5 w-3.5" />
                <span>Purge Corpus</span>
              </button>
            )
          )}

          {onNavigateToIndexing && (
            <button
              onClick={onNavigateToIndexing}
              className="flex items-center gap-1.5 bg-surface-raised hover:bg-surface-hover text-ink-secondary hover:text-ink-primary border border-surface-border px-3 py-1.5 rounded text-xs font-mono transition-colors cursor-pointer"
            >
              <FolderOpen className="h-3.5 w-3.5" />
              <span>Batch Folders</span>
            </button>
          )}

          <button
            onClick={onRefreshDocuments}
            className="p-1.5 bg-surface-raised hover:bg-surface-hover text-ink-secondary hover:text-ink-primary border border-surface-border rounded transition-colors cursor-pointer"
            title="Refresh document ledger"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Status Feedback Toast/Banner */}
      {statusMessage && (
        <div
          className={`px-4 py-2 rounded text-xs font-mono flex items-center justify-between border ${
            statusMessage.isError
              ? 'bg-signal-rose/10 border-signal-rose/30 text-signal-rose'
              : 'bg-signal-green/10 border-signal-green/30 text-signal-green'
          }`}
        >
          <div className="flex items-center gap-2">
            {statusMessage.isError ? (
              <AlertCircle className="h-4 w-4 shrink-0" />
            ) : (
              <CheckCircle2 className="h-4 w-4 shrink-0" />
            )}
            <span>{statusMessage.text}</span>
          </div>
          <button
            onClick={() => setStatusMessage(null)}
            className="text-[10px] underline hover:opacity-80 cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Filter and Search Bar */}
      <div className="flex flex-col md:flex-row gap-3 items-stretch md:items-center justify-between bg-surface-panel border border-surface-border p-3 rounded">
        {/* Search input */}
        <div className="relative flex-1 max-w-md">
          <Search className="h-3.5 w-3.5 text-ink-muted absolute left-3 top-2.5" />
          <input
            type="text"
            placeholder="Search by filename or keyword..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-surface-base border border-surface-border rounded pl-9 pr-3 py-1.5 text-xs text-ink-primary placeholder-ink-muted focus:outline-none focus:border-ink-faint font-sans"
          />
        </div>

        {/* Filter Badges: File Type */}
        <div className="flex items-center gap-1 overflow-x-auto">
          <span className="font-mono text-[10px] text-ink-muted uppercase mr-1">Type:</span>
          {(['all', 'pdf', 'code', 'web', 'text'] as FileTypeFilter[]).map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={`px-2 py-1 rounded text-xs font-mono uppercase transition-colors cursor-pointer border ${
                typeFilter === t
                  ? 'bg-surface-raised border-ink-muted text-ink-primary font-bold'
                  : 'bg-surface-base border-surface-border text-ink-muted hover:text-ink-secondary'
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Filter Badges: Clearance */}
        <div className="flex items-center gap-1 overflow-x-auto">
          <span className="font-mono text-[10px] text-ink-muted uppercase mr-1">Clearance:</span>
          {(['all', 1, 2, 3, 4] as (number | 'all')[]).map((c) => (
            <button
              key={c}
              onClick={() => setClearanceFilter(c)}
              className={`px-2 py-1 rounded text-xs font-mono transition-colors cursor-pointer border ${
                clearanceFilter === c
                  ? 'bg-surface-raised border-ink-muted text-ink-primary font-bold'
                  : 'bg-surface-base border-surface-border text-ink-muted hover:text-ink-secondary'
              }`}
            >
              {c === 'all' ? 'ALL' : `L${c}`}
            </button>
          ))}
        </div>
      </div>

      {/* Ledger Table */}
      <div className="border border-surface-border rounded bg-surface-panel overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-surface-border bg-surface-base font-mono text-[10px] text-ink-muted uppercase tracking-wider select-none">
                <th className="py-2.5 px-4 font-normal">Document Resource</th>
                <th className="py-2.5 px-3 font-normal">Format</th>
                <th className="py-2.5 px-3 font-normal">Clearance</th>
                <th className="py-2.5 px-3 font-normal text-right">Vectors (Parent / Child)</th>
                <th className="py-2.5 px-3 font-normal text-right">Size</th>
                <th className="py-2.5 px-3 font-normal text-right">Indexed</th>
                <th className="py-2.5 px-4 font-normal text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border font-sans text-xs">
              {filteredDocuments.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-ink-muted">
                    <Layers className="h-6 w-6 mx-auto mb-2 text-ink-faint" />
                    <div>No documents match the active search or classification filters.</div>
                    <div className="text-[11px] mt-1 font-mono text-ink-faint">
                      Total corpus contains {documents.length} registered documents.
                    </div>
                  </td>
                </tr>
              ) : (
                filteredDocuments.map((doc) => (
                  <tr
                    key={doc.doc_id}
                    className="hover:bg-surface-raised/40 transition-colors group"
                  >
                    {/* Document Resource */}
                    <td className="py-3 px-4 font-medium text-ink-primary max-w-xs md:max-w-md truncate">
                      <div className="truncate font-mono text-xs" title={doc.filename}>
                        {doc.filename}
                      </div>
                      <div className="font-mono text-[10px] text-ink-muted truncate">
                        ID: {doc.doc_id.slice(0, 16)}...
                      </div>
                    </td>

                    {/* Format */}
                    <td className="py-3 px-3">
                      {getTypeBadge(doc.filename, doc.mime_type)}
                    </td>

                    {/* Clearance */}
                    <td className="py-3 px-3">
                      {getClearanceBadge(doc.clearance_level)}
                    </td>

                    {/* Chunks */}
                    <td className="py-3 px-3 font-mono text-xs text-right tabular-nums">
                      <span className="text-ink-primary font-semibold">
                        {doc.total_child_chunks || 0}
                      </span>
                      <span className="text-ink-muted text-[11px]">
                        {' '}
                        / {doc.total_parent_chunks || 0} parents
                      </span>
                    </td>

                    {/* Size */}
                    <td className="py-3 px-3 font-mono text-xs text-right text-ink-muted tabular-nums">
                      {formatBytes(doc.file_size_bytes)}
                    </td>

                    {/* Date */}
                    <td className="py-3 px-3 font-mono text-[11px] text-right text-ink-muted whitespace-nowrap">
                      {doc.created_at ? new Date(doc.created_at).toLocaleDateString() : 'Active'}
                    </td>

                    {/* Actions */}
                    <td className="py-3 px-4 text-right">
                      {confirmDeleteId === doc.doc_id ? (
                        <div className="inline-flex items-center gap-1.5 justify-end">
                          <button
                            onClick={() => executeDelete(doc.doc_id, doc.filename)}
                            disabled={deletingId === doc.doc_id}
                            className="bg-signal-rose hover:bg-red-600 text-white font-mono text-[10px] px-2 py-0.5 rounded transition-colors cursor-pointer"
                          >
                            {deletingId === doc.doc_id ? 'Purging...' : 'Delete'}
                          </button>
                          <button
                            onClick={() => setConfirmDeleteId(null)}
                            className="bg-surface-raised hover:bg-surface-hover text-ink-muted hover:text-ink-primary font-mono text-[10px] px-1.5 py-0.5 rounded border border-surface-border transition-colors cursor-pointer"
                            title="Cancel"
                          >
                            ✕
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setConfirmDeleteId(doc.doc_id)}
                          className="p-1 rounded text-ink-muted hover:text-signal-rose hover:bg-surface-raised transition-colors cursor-pointer"
                          title="Purge document vectors"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Ledger Summary Footer */}
        <div className="border-t border-surface-border bg-surface-base px-4 py-2.5 flex items-center justify-between font-mono text-[11px] text-ink-muted select-none">
          <span>Showing {filteredDocuments.length} of {documents.length} entries</span>
          <span>Aggregate Chunks: {totalChunks.toLocaleString()} ({totalParentChunks.toLocaleString()} parents)</span>
        </div>
      </div>
    </div>
  );
};
