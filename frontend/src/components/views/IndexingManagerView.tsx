import React, { useState, useEffect, useCallback } from 'react';
import {
  Folder,
  GitBranch,
  Play,
  Pause,
  RefreshCw,
  Clock,
  CheckCircle2,
  AlertTriangle,
  FolderPlus,
  GitFork,
  Loader2,
  X,
  AlertCircle,
} from 'lucide-react';
import type { IndexingJob } from '../../types';
import {
  getIndexingJobs,
  pauseIndexingJob,
  resumeIndexingJob,
  ingestFolder,
  ingestRepository,
} from '../../services/api';

interface IndexingManagerViewProps {
  initialJobs?: IndexingJob[];
  onRefreshJobs?: () => void;
}

export const IndexingManagerView: React.FC<IndexingManagerViewProps> = ({
  initialJobs = [],
  onRefreshJobs,
}) => {
  const [jobs, setJobs] = useState<IndexingJob[]>(initialJobs);
  const [isLoading, setIsLoading] = useState(false);
  const [activeModal, setActiveModal] = useState<'folder' | 'repo' | null>(null);
  const [inputPath, setInputPath] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [notification, setNotification] = useState<{ text: string; isError?: boolean } | null>(null);

  const fetchJobs = useCallback(async () => {
    try {
      setIsLoading(true);
      const data = await getIndexingJobs();
      if (Array.isArray(data)) {
        setJobs(data);
      }
      if (onRefreshJobs) onRefreshJobs();
    } catch (err: any) {
      console.warn('Failed to fetch jobs:', err);
    } finally {
      setIsLoading(false);
    }
  }, [onRefreshJobs]);

  useEffect(() => {
    const hasActive = jobs.some((j) => j.status === 'running' || j.status === 'pending');
    if (!hasActive) return;

    const interval = setInterval(() => {
      fetchJobs();
    }, 3000);
    return () => clearInterval(interval);
  }, [jobs, fetchJobs]);

  const handlePause = async (jobId: string) => {
    try {
      await pauseIndexingJob(jobId);
      setJobs((prev) =>
        prev.map((j) => (j.job_id === jobId ? { ...j, status: 'paused' } : j))
      );
      setNotification({ text: `Job ${jobId.slice(0, 8)} paused.` });
    } catch (err: any) {
      setNotification({ text: err.message || 'Failed to pause job', isError: true });
    }
  };

  const handleResume = async (jobId: string) => {
    try {
      await resumeIndexingJob(jobId);
      setJobs((prev) =>
        prev.map((j) => (j.job_id === jobId ? { ...j, status: 'running' } : j))
      );
      setNotification({ text: `Job ${jobId.slice(0, 8)} resumed.` });
    } catch (err: any) {
      setNotification({ text: err.message || 'Failed to resume job', isError: true });
    }
  };

  const handleStartIngest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputPath.trim()) return;

    try {
      setIsSubmitting(true);
      if (activeModal === 'folder') {
        const result = await ingestFolder(inputPath.trim());
        setNotification({
          text: `Folder ingestion job queued: ${result?.job_id ? result.job_id.slice(0, 8) : 'Started'}.`,
        });
      } else if (activeModal === 'repo') {
        const result = await ingestRepository(inputPath.trim());
        setNotification({
          text: `Repository ingestion job queued: ${result?.job_id ? result.job_id.slice(0, 8) : 'Started'}.`,
        });
      }
      setInputPath('');
      setActiveModal(null);
      await fetchJobs();
    } catch (err: any) {
      setNotification({ text: err.message || 'Failed to trigger ingestion job', isError: true });
    } finally {
      setIsSubmitting(false);
    }
  };

  const runningCount = jobs.filter((j) => j.status === 'running').length;
  const pausedCount = jobs.filter((j) => j.status === 'paused').length;
  const completedCount = jobs.filter((j) => j.status === 'completed').length;
  const totalChunksProcessed = jobs.reduce((acc, j) => acc + (j.total_chunks || 0), 0);

  const getStatusBadge = (status: IndexingJob['status']) => {
    switch (status) {
      case 'running':
        return (
          <span className="flex items-center gap-1.5 font-mono text-[10px] text-signal-green bg-signal-green/10 border border-signal-green/30 px-2 py-0.5 rounded font-semibold animate-pulse">
            <span className="h-1.5 w-1.5 rounded-full bg-signal-green" />
            RUNNING
          </span>
        );
      case 'paused':
        return (
          <span className="flex items-center gap-1.5 font-mono text-[10px] text-signal-amber bg-signal-amber/10 border border-signal-amber/30 px-2 py-0.5 rounded font-medium">
            <Pause className="h-2.5 w-2.5" />
            PAUSED
          </span>
        );
      case 'completed':
        return (
          <span className="flex items-center gap-1.5 font-mono text-[10px] text-ink-secondary bg-surface-base border border-surface-border px-2 py-0.5 rounded">
            <CheckCircle2 className="h-3 w-3 text-signal-green" />
            COMPLETED
          </span>
        );
      case 'failed':
        return (
          <span className="flex items-center gap-1.5 font-mono text-[10px] text-signal-rose bg-signal-rose/10 border border-signal-rose/30 px-2 py-0.5 rounded font-medium">
            <AlertTriangle className="h-3 w-3" />
            FAILED
          </span>
        );
      default:
        return (
          <span className="flex items-center gap-1.5 font-mono text-[10px] text-signal-sky bg-signal-sky/10 border border-signal-sky/30 px-2 py-0.5 rounded">
            <Clock className="h-3 w-3" />
            PENDING
          </span>
        );
    }
  };

  return (
    <div className="flex-1 overflow-y-auto bg-surface-base p-6 space-y-6">
      {/* View Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-border pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] text-signal-green uppercase tracking-wider font-semibold">
              BACKGROUND SCALE SCHEDULER
            </span>
            <span className="text-surface-border">•</span>
            <span className="font-mono text-[10px] text-ink-muted">
              PRIORITY RESOURCE MANAGEMENT & PERSISTENT RESUME
            </span>
          </div>
          <h1 className="text-xl font-bold tracking-tight text-ink-primary mt-1">
            Indexing Queue Manager
          </h1>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              setActiveModal('folder');
              setInputPath('');
            }}
            className="flex items-center gap-1.5 bg-surface-raised hover:bg-surface-hover text-ink-primary border border-surface-border px-3 py-1.5 rounded text-xs font-mono transition-colors cursor-pointer"
          >
            <FolderPlus className="h-3.5 w-3.5 text-signal-green" />
            <span>Ingest Folder</span>
          </button>

          <button
            onClick={() => {
              setActiveModal('repo');
              setInputPath('');
            }}
            className="flex items-center gap-1.5 bg-surface-raised hover:bg-surface-hover text-ink-primary border border-surface-border px-3 py-1.5 rounded text-xs font-mono transition-colors cursor-pointer"
          >
            <GitFork className="h-3.5 w-3.5 text-signal-sky" />
            <span>Ingest Repository</span>
          </button>

          <button
            onClick={fetchJobs}
            disabled={isLoading}
            className="p-1.5 bg-surface-raised hover:bg-surface-hover text-ink-secondary hover:text-ink-primary border border-surface-border rounded transition-colors cursor-pointer disabled:opacity-50"
            title="Refresh jobs"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Status Feedback Toast */}
      {notification && (
        <div
          className={`px-4 py-2 rounded text-xs font-mono flex items-center justify-between border ${
            notification.isError
              ? 'bg-signal-rose/10 border-signal-rose/30 text-signal-rose'
              : 'bg-signal-green/10 border-signal-green/30 text-signal-green'
          }`}
        >
          <div className="flex items-center gap-2">
            {notification.isError ? (
              <AlertCircle className="h-4 w-4 shrink-0" />
            ) : (
              <CheckCircle2 className="h-4 w-4 shrink-0" />
            )}
            <span>{notification.text}</span>
          </div>
          <button
            onClick={() => setNotification(null)}
            className="text-[10px] underline hover:opacity-80 cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Priority Scheduler Banner */}
      <div className="bg-surface-panel border border-surface-border rounded p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-3 font-mono text-xs">
        <div className="flex items-center gap-3">
          <div className="h-2 w-2 rounded-full bg-signal-green shrink-0" />
          <div className="space-y-0.5">
            <span className="text-ink-primary font-bold">Dynamic Priority Yielding Enabled</span>
            <p className="text-ink-muted text-[11px] font-sans">
              Background file chunking automatically throttles when an interactive chat generation is requested, preventing GPU out-of-memory errors and maintaining ultra-low latency.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3 font-mono text-[11px] text-ink-muted shrink-0">
          <span>Active: <strong className="text-signal-green">{runningCount}</strong></span>
          <span>Paused: <strong className="text-signal-amber">{pausedCount}</strong></span>
          <span>Done: <strong className="text-ink-primary">{completedCount}</strong></span>
        </div>
      </div>

      {/* Jobs Queue List */}
      <div className="space-y-3">
        <div className="flex items-center justify-between text-xs font-mono text-ink-muted uppercase tracking-wider px-1">
          <span>Registered Ingestion Workloads ({jobs.length})</span>
          <span>Cumulative Vectors: {totalChunksProcessed.toLocaleString()}</span>
        </div>

        {jobs.length === 0 ? (
          <div className="p-8 border border-dashed border-surface-border rounded bg-surface-panel/40 text-center space-y-3">
            <Folder className="h-8 w-8 text-ink-faint mx-auto" />
            <div className="text-xs font-mono text-ink-secondary">
              NO ACTIVE OR RECENT INDEXING JOBS FOUND
            </div>
            <p className="text-xs text-ink-muted max-w-md mx-auto">
              Add a directory containing PDF/documentation files or a source code repository to run high-throughput batch vectorization.
            </p>
            <div className="flex items-center justify-center gap-3 pt-2">
              <button
                onClick={() => setActiveModal('folder')}
                className="inline-flex items-center gap-1.5 bg-ink-primary hover:bg-white text-surface-base font-semibold px-3 py-1.5 rounded text-xs transition-colors cursor-pointer"
              >
                <FolderPlus className="h-3.5 w-3.5" />
                <span>Ingest Directory</span>
              </button>
              <button
                onClick={() => setActiveModal('repo')}
                className="inline-flex items-center gap-1.5 bg-surface-raised hover:bg-surface-hover text-ink-primary border border-surface-border px-3 py-1.5 rounded text-xs transition-colors cursor-pointer"
              >
                <GitFork className="h-3.5 w-3.5" />
                <span>Ingest Codebase</span>
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {jobs.map((job) => {
              const totalFiles = job.total_files || 1;
              const processedFiles = job.processed_files || 0;
              const percent = Math.min(100, Math.round((processedFiles / Math.max(1, totalFiles)) * 100));

              return (
                <div
                  key={job.job_id}
                  className="bg-surface-panel border border-surface-border rounded p-4 space-y-3 hover:border-surface-border/80 transition-colors"
                >
                  {/* Job Header */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div className="flex items-center gap-3">
                      {job.job_type === 'repository' ? (
                        <div className="p-2 bg-signal-sky/10 border border-signal-sky/30 rounded text-signal-sky">
                          <GitBranch className="h-4 w-4" />
                        </div>
                      ) : (
                        <div className="p-2 bg-signal-green/10 border border-signal-green/30 rounded text-signal-green">
                          <Folder className="h-4 w-4" />
                        </div>
                      )}

                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs font-bold text-ink-primary">
                            {job.source_path}
                          </span>
                          <span className="font-mono text-[10px] text-ink-muted uppercase bg-surface-base px-1.5 py-0.2 rounded border border-surface-border">
                            {job.job_type}
                          </span>
                        </div>
                        <div className="font-mono text-[10px] text-ink-muted">
                          Job ID: {job.job_id} · Created: {new Date(job.created_at).toLocaleTimeString()}
                        </div>
                      </div>
                    </div>

                    {/* Status & Control Actions */}
                    <div className="flex items-center gap-3 self-end sm:self-center">
                      {getStatusBadge(job.status)}

                      {job.status === 'running' && (
                        <button
                          onClick={() => handlePause(job.job_id)}
                          className="flex items-center gap-1 bg-surface-raised hover:bg-surface-hover text-signal-amber border border-surface-border px-2.5 py-1 rounded text-xs font-mono transition-colors cursor-pointer"
                          title="Pause background embedding"
                        >
                          <Pause className="h-3 w-3" />
                          <span>Pause</span>
                        </button>
                      )}

                      {job.status === 'paused' && (
                        <button
                          onClick={() => handleResume(job.job_id)}
                          className="flex items-center gap-1 bg-surface-raised hover:bg-surface-hover text-signal-green border border-surface-border px-2.5 py-1 rounded text-xs font-mono transition-colors cursor-pointer"
                          title="Resume background embedding"
                        >
                          <Play className="h-3 w-3" />
                          <span>Resume</span>
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Live Progress Bar */}
                  <div className="space-y-1">
                    <div className="flex justify-between items-center font-mono text-[11px] text-ink-secondary">
                      <span>Progress: {processedFiles} / {totalFiles} files vectorized ({percent}%)</span>
                      <span className="text-ink-primary font-semibold tabular-nums">
                        {job.total_chunks.toLocaleString()} chunks produced
                      </span>
                    </div>

                    <div className="w-full h-1.5 bg-surface-base rounded-none overflow-hidden border border-surface-border">
                      <div
                        className={`h-full transition-all duration-300 ${
                          job.status === 'completed'
                            ? 'bg-signal-green'
                            : job.status === 'paused'
                            ? 'bg-signal-amber'
                            : job.status === 'failed'
                            ? 'bg-signal-rose'
                            : 'bg-signal-green animate-pulse'
                        }`}
                        style={{ width: `${Math.max(2, percent)}%` }}
                      />
                    </div>
                  </div>

                  {/* Failure Error Message */}
                  {job.status === 'failed' && job.error_message && (
                    <div className="bg-signal-rose/10 border border-signal-rose/30 p-2.5 rounded font-mono text-[11px] text-signal-rose">
                      Error: {job.error_message}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Modal Dialog for Ingestion */}
      {activeModal && (
        <div className="fixed inset-0 bg-surface-base/80 backdrop-blur-sm z-50 flex items-center justify-center p-6 animate-in fade-in duration-150">
          <div className="bg-surface-panel border border-surface-border rounded-lg w-full max-w-lg shadow-2xl overflow-hidden">
            <div className="h-12 px-5 border-b border-surface-border flex items-center justify-between bg-surface-base">
              <span className="font-mono text-xs font-bold uppercase tracking-wider text-ink-primary">
                {activeModal === 'folder' ? 'Ingest Local Directory' : 'Ingest Code Repository'}
              </span>
              <button
                onClick={() => setActiveModal(null)}
                className="text-ink-muted hover:text-ink-primary transition-colors cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleStartIngest} className="p-5 space-y-4">
              <div className="space-y-1.5">
                <label className="font-mono text-[11px] text-ink-secondary uppercase tracking-wider block">
                  Absolute Path on Host Machine:
                </label>
                <input
                  type="text"
                  required
                  placeholder={
                    activeModal === 'folder'
                      ? 'C:\\Path\\To\\Documents or /home/docs'
                      : 'C:\\Path\\To\\Repository or /home/repos/project'
                  }
                  value={inputPath}
                  onChange={(e) => setInputPath(e.target.value)}
                  className="w-full bg-surface-base border border-surface-border rounded px-3 py-2 text-xs font-mono text-ink-primary placeholder-ink-muted focus:outline-none focus:border-ink-faint"
                />
                <p className="text-[11px] text-ink-muted font-sans pt-1">
                  {activeModal === 'folder'
                    ? 'All supported files (.pdf, .html, .txt, .md, .py, .ts, etc.) will be discovered recursively.'
                    : 'Code files will be parsed via AST chunker preserving function boundaries, docstrings, and imports.'}
                </p>
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-surface-border">
                <button
                  type="button"
                  onClick={() => setActiveModal(null)}
                  className="px-3 py-1.5 rounded text-xs font-mono text-ink-secondary hover:text-ink-primary cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting || !inputPath.trim()}
                  className="flex items-center gap-1.5 bg-ink-primary hover:bg-white text-surface-base font-semibold px-4 py-1.5 rounded text-xs font-mono transition-colors cursor-pointer disabled:opacity-50"
                >
                  {isSubmitting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Play className="h-3.5 w-3.5 fill-current" />
                  )}
                  <span>Launch Ingestion Job</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
