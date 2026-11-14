import React, { useState, useRef } from 'react';
import { X, UploadCloud, Trash2, CheckCircle2, AlertCircle, Loader2, Search, Globe, FileText } from 'lucide-react';
import type { DocumentItem } from '../types';
import { uploadDocument, deleteDocument, purgeAllDocuments, ingestUrl } from '../services/api';

interface DocumentManagerProps {
  isOpen: boolean;
  onClose: () => void;
  documents: DocumentItem[];
  onRefreshDocuments: () => void;
}

export const DocumentManager: React.FC<DocumentManagerProps> = ({
  isOpen,
  onClose,
  documents,
  onRefreshDocuments,
}) => {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [selectedClearance, setSelectedClearance] = useState<number>(1);
  const [searchTerm, setSearchTerm] = useState('');
  const [activeTab, setActiveTab] = useState<'files' | 'url'>('files');
  const [urlInput, setUrlInput] = useState('');
  const [statusMessage, setStatusMessage] = useState<{ text: string; isError?: boolean } | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmPurgeAll, setConfirmPurgeAll] = useState(false);
  const [isPurgingAll, setIsPurgingAll] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!isOpen) return null;

  const handleUrlSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!urlInput.trim()) return;
    try {
      setUploading(true);
      setStatusMessage({ text: `Crawling & extracting HTML from "${urlInput.trim()}" (Clearance L${selectedClearance})...` });
      await ingestUrl(urlInput.trim(), selectedClearance);
      setStatusMessage({ text: `Indexed web page content from "${urlInput.trim()}" successfully under Clearance L${selectedClearance}.` });
      setUrlInput('');
      onRefreshDocuments();
    } catch (err: any) {
      setStatusMessage({ text: err.message || 'Web ingestion failed.', isError: true });
    } finally {
      setUploading(false);
    }
  };

  const handleFiles = async (files: FileList | File[]) => {
    const fileArray = Array.from(files);
    if (fileArray.length === 0) return;

    try {
      setUploading(true);
      let successCount = 0;
      for (let i = 0; i < fileArray.length; i++) {
        const file = fileArray[i];
        setStatusMessage({
          text: `[${i + 1}/${fileArray.length}] Parsing "${file.name}" (Clearance L${selectedClearance}) into hierarchical parent-child vectors...`,
        });
        await uploadDocument(file, selectedClearance);
        successCount++;
        onRefreshDocuments();
      }
      setStatusMessage({
        text: `Indexed ${successCount} file(s) successfully under Clearance L${selectedClearance}.`,
      });
    } catch (err: any) {
      setStatusMessage({ text: err.message || 'Ingestion failed.', isError: true });
    } finally {
      setUploading(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  };

  const executeDelete = async (docId: string, filename: string) => {
    setDeletingId(docId);
    try {
      await deleteDocument(docId);
      setConfirmDeleteId(null);
      onRefreshDocuments();
      setStatusMessage({ text: `Deleted "${filename}" and purged vectors.` });
    } catch (err: any) {
      setStatusMessage({ text: err.message || 'Failed to delete.', isError: true });
    } finally {
      setDeletingId(null);
    }
  };

  const handlePurgeAll = async () => {
    setIsPurgingAll(true);
    try {
      const res = await purgeAllDocuments();
      setConfirmPurgeAll(false);
      onRefreshDocuments();
      setStatusMessage({ text: `Purged ${res.deleted_count} documents and wiped all vectors.` });
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

  const filteredDocs = documents.filter((d) =>
    d.filename.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="fixed inset-0 bg-surface-base/80 backdrop-blur-sm z-50 flex items-center justify-center p-6 animate-in fade-in duration-150">
      <div className="bg-surface-panel border border-surface-border rounded-lg w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Header Bar */}
        <div className="h-14 px-6 border-b border-surface-border flex items-center justify-between bg-surface-base select-none">
          <div className="flex items-center gap-3">
            <span className="font-mono text-xs font-bold uppercase tracking-wider text-ink-primary">
              Document Corpus Ledger
            </span>
            <span className="font-mono text-[11px] text-ink-muted">
              ({documents.length} files · {totalChunks} vectors · {formatBytes(totalBytes)})
            </span>
          </div>
          <div className="flex items-center gap-3">
            {documents.length > 0 && (
              confirmPurgeAll ? (
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={handlePurgeAll}
                    disabled={isPurgingAll}
                    className="bg-signal-rose hover:bg-red-600 text-white font-mono text-[10px] px-2 py-1 rounded transition-colors cursor-pointer"
                  >
                    {isPurgingAll ? 'Purging...' : 'Confirm Purge All'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmPurgeAll(false)}
                    className="bg-surface-raised hover:bg-surface-hover text-ink-muted hover:text-ink-primary font-mono text-[10px] px-1.5 py-1 rounded border border-surface-border transition-colors cursor-pointer"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmPurgeAll(true)}
                  className="flex items-center gap-1 text-signal-rose hover:bg-signal-rose/10 border border-signal-rose/30 hover:border-signal-rose px-2 py-1 rounded font-mono text-[10px] transition-colors cursor-pointer"
                  title="Purge all documents and vector embeddings"
                >
                  <Trash2 className="h-3 w-3" />
                  <span>Purge All</span>
                </button>
              )
            )}
            <button
              onClick={onClose}
              className="p-1 rounded text-ink-muted hover:text-ink-primary hover:bg-surface-raised transition-colors cursor-pointer"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Action & Drop Area */}
        <div className="p-6 border-b border-surface-border bg-surface-base/30 space-y-4">
          <div className="flex items-center justify-between font-mono text-xs">
            <span className="text-ink-secondary text-[11px] uppercase tracking-wider">
              Document Clearance Classification:
            </span>
            <div className="flex items-center gap-1.5">
              {[
                { level: 1, label: 'L1 Public' },
                { level: 2, label: 'L2 Internal' },
                { level: 3, label: 'L3 Confidential' },
                { level: 4, label: 'L4 Top Secret' },
              ].map((opt) => (
                <button
                  key={opt.level}
                  type="button"
                  onClick={() => setSelectedClearance(opt.level)}
                  className={`px-2 py-0.5 rounded text-[10px] font-mono transition-colors cursor-pointer border ${
                    selectedClearance === opt.level
                      ? 'bg-ink-primary text-surface-base border-ink-primary font-bold'
                      : 'bg-surface-base text-ink-muted border-surface-border hover:text-ink-primary'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Tab Selector: Files vs Web URL */}
          <div className="flex items-center gap-2 border-b border-surface-border pb-2">
            <button
              type="button"
              onClick={() => setActiveTab('files')}
              className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs font-mono transition-colors cursor-pointer border ${
                activeTab === 'files'
                  ? 'bg-surface-raised border-signal-green text-ink-primary font-bold'
                  : 'bg-transparent border-transparent text-ink-muted hover:text-ink-secondary'
              }`}
            >
              <FileText className="h-3.5 w-3.5 text-signal-green" />
              <span>Upload Local Files & Code</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('url')}
              className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs font-mono transition-colors cursor-pointer border ${
                activeTab === 'url'
                  ? 'bg-surface-raised border-signal-sky text-ink-primary font-bold'
                  : 'bg-transparent border-transparent text-ink-muted hover:text-ink-secondary'
              }`}
            >
              <Globe className="h-3.5 w-3.5 text-signal-sky" />
              <span>Index Web / Intranet URL</span>
            </button>
          </div>

          {activeTab === 'files' ? (
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setIsDragging(true);
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`border border-dashed rounded p-4 text-center cursor-pointer transition-colors ${
                isDragging
                  ? 'border-signal-green bg-signal-green/5'
                  : 'border-surface-border hover:border-ink-faint bg-surface-base'
              }`}
            >
              <input
                type="file"
                ref={fileInputRef}
                multiple
                onChange={(e) => {
                  if (e.target.files && e.target.files.length > 0) {
                    handleFiles(e.target.files);
                  }
                }}
                accept=".pdf,.docx,.doc,.xlsx,.xls,.pptx,.ppt,.txt,.md,.csv,.json,.yaml,.yml,.toml,.xml,.ipynb,.zip,.png,.jpg,.jpeg,.py,.js,.ts,.tsx,.jsx,.go,.rs,.java,.cpp,.c,.h,.sh,.sql"
                className="hidden"
              />
              <div className="flex items-center justify-center gap-3 font-mono text-xs text-ink-secondary">
                {uploading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin text-signal-green" />
                    <span>INGESTING DOCUMENT STREAM (L{selectedClearance})...</span>
                  </>
                ) : (
                  <>
                    <UploadCloud className="h-4 w-4 text-ink-muted" />
                    <span>DROP FILES OR CLICK TO MULTI-SELECT UNDER CLEARANCE L{selectedClearance}</span>
                  </>
                )}
              </div>
            </div>
          ) : (
            <form onSubmit={handleUrlSubmit} className="flex gap-2">
              <input
                type="url"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                placeholder="https://intranet-wiki.local/docs/incident-sop or https://docs.python.org/3/"
                disabled={uploading}
                className="flex-1 bg-surface-base border border-surface-border rounded px-3 py-2 text-xs font-mono text-ink-primary focus:outline-none focus:border-ink-faint"
              />
              <button
                type="submit"
                disabled={uploading || !urlInput.trim()}
                className="btn btn-primary text-xs font-mono flex items-center gap-1.5 shrink-0"
              >
                {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Globe className="h-3.5 w-3.5" />}
                <span>{uploading ? 'Crawling…' : 'Ingest URL'}</span>
              </button>
            </form>
          )}

          {statusMessage && (
            <div className={`p-2.5 rounded font-mono text-xs flex items-center gap-2 border ${
              statusMessage.isError
                ? 'bg-signal-rose/10 border-signal-rose/30 text-signal-rose'
                : 'bg-signal-green/10 border-signal-green/30 text-signal-green'
            }`}>
              {statusMessage.isError ? <AlertCircle className="h-3.5 w-3.5" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
              <span>{statusMessage.text}</span>
            </div>
          )}
        </div>

        {/* Ledger Table */}
        <div className="flex-1 overflow-y-auto p-6 space-y-3">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] uppercase tracking-wider text-ink-muted">
              Indexed Artifacts
            </span>
            {documents.length > 2 && (
              <div className="relative w-56">
                <Search className="h-3 w-3 text-ink-muted absolute left-2.5 top-2.5" />
                <input
                  type="text"
                  placeholder="Filter by name..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="w-full bg-surface-base border border-surface-border rounded pl-8 pr-2 py-1 text-xs text-ink-primary font-mono placeholder-ink-muted focus:outline-none focus:border-ink-faint"
                />
              </div>
            )}
          </div>

          {filteredDocs.length === 0 ? (
            <div className="py-12 text-center font-mono text-xs text-ink-muted border border-surface-border rounded bg-surface-base/30">
              {searchTerm ? 'NO MATCHING RECORDS.' : 'CORPUS EMPTY. INGEST A DOCUMENT TO ENABLE GROUNDED RETRIEVAL.'}
            </div>
          ) : (
            <div className="border border-surface-border rounded overflow-hidden divide-y divide-surface-border font-mono text-xs">
              <div className="grid grid-cols-12 px-4 py-2 bg-surface-base text-[10px] text-ink-muted uppercase tracking-wider">
                <div className="col-span-4">File & Format</div>
                <div className="col-span-2 text-center">Clearance</div>
                <div className="col-span-2 text-right">Size</div>
                <div className="col-span-1 text-right">Pages</div>
                <div className="col-span-2 text-right">Vectors</div>
                <div className="col-span-1 text-right">Action</div>
              </div>

              {filteredDocs.map((doc) => {
                const ext = doc.filename.split('.').pop()?.toUpperCase() || 'FILE';
                const clearanceBadge = (() => {
                  switch (doc.clearance_level) {
                    case 4:
                      return <span className="text-[9px] px-1.5 py-0.5 rounded bg-signal-rose/20 text-signal-rose font-mono font-bold">L4 TOP SECRET</span>;
                    case 3:
                      return <span className="text-[9px] px-1.5 py-0.5 rounded bg-signal-amber/20 text-signal-amber font-mono font-bold">L3 CONFIDENTIAL</span>;
                    case 2:
                      return <span className="text-[9px] px-1.5 py-0.5 rounded bg-sky-500/20 text-sky-400 font-mono font-bold">L2 INTERNAL</span>;
                    default:
                      return <span className="text-[9px] px-1.5 py-0.5 rounded bg-surface-border text-ink-muted font-mono font-bold">L1 PUBLIC</span>;
                  }
                })();

                return (
                  <div key={doc.doc_id} className="grid grid-cols-12 px-4 py-2.5 items-center hover:bg-surface-raised transition-colors">
                    <div className="col-span-4 flex items-center gap-2 truncate pr-2">
                      <span className="text-[9px] px-1 py-0.5 rounded bg-surface-base border border-surface-border font-bold text-ink-muted">
                        {ext}
                      </span>
                      <span className="truncate text-ink-primary font-sans font-medium" title={doc.filename}>
                        {doc.filename}
                      </span>
                    </div>

                    <div className="col-span-2 text-center">
                      {clearanceBadge}
                    </div>

                    <div className="col-span-2 text-right text-ink-secondary tabular-nums">
                      {formatBytes(doc.file_size_bytes)}
                    </div>

                    <div className="col-span-1 text-right text-ink-secondary tabular-nums">
                      {doc.total_pages}
                    </div>

                    <div className="col-span-2 text-right text-signal-green tabular-nums">
                      {doc.total_child_chunks}
                    </div>

                    <div className="col-span-1 text-right">
                      {confirmDeleteId === doc.doc_id ? (
                        <div className="inline-flex items-center gap-1 justify-end">
                          <button
                            onClick={() => executeDelete(doc.doc_id, doc.filename)}
                            disabled={deletingId === doc.doc_id}
                            className="bg-signal-rose hover:bg-red-600 text-white font-mono text-[9px] px-1.5 py-0.5 rounded transition-colors cursor-pointer"
                          >
                            {deletingId === doc.doc_id ? '...' : 'Del'}
                          </button>
                          <button
                            onClick={() => setConfirmDeleteId(null)}
                            className="text-ink-muted hover:text-ink-primary font-mono text-[9px] px-1 py-0.5 rounded border border-surface-border transition-colors cursor-pointer"
                            title="Cancel"
                          >
                            ✕
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setConfirmDeleteId(doc.doc_id)}
                          className="text-ink-muted hover:text-signal-rose transition-colors cursor-pointer p-1"
                          title="Purge document"
                        >
                          <Trash2 className="h-3 w-3 inline" />
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
