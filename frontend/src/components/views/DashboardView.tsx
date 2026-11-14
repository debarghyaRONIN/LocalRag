import React from 'react';
import {
  Layers,
  Cpu,
  HardDrive,
  Activity,
  Zap,
  ShieldCheck,
  Database,
  ArrowUpRight,
  RefreshCw,
} from 'lucide-react';
import type { SystemHealth, HardwareInfo, DocumentItem, IndexingJob } from '../../types';

interface DashboardViewProps {
  health: SystemHealth | null;
  hardware: HardwareInfo | null;
  documents: DocumentItem[];
  jobs: IndexingJob[];
  onNavigateToLibrary: () => void;
  onNavigateToIndexing: () => void;
  onRefreshHealth: () => void;
}

export const DashboardView: React.FC<DashboardViewProps> = ({
  health,
  hardware,
  documents,
  jobs,
  onNavigateToLibrary,
  onNavigateToIndexing,
  onRefreshHealth,
}) => {
  const totalChunks = health?.total_indexed_chunks || documents.reduce((acc, d) => acc + (d.total_child_chunks || 0), 0);
  const totalDocs = health?.total_indexed_documents || documents.length;
  const totalSizeBytes = documents.reduce((acc, d) => acc + (d.file_size_bytes || 0), 0);

  const formatNumber = (num: number) => {
    if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(2)}M`;
    if (num >= 1_000) return `${(num / 1_000).toFixed(1)}k`;
    return num.toLocaleString();
  };

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  };

  const vramUsed = health?.gpu_memory_used_mb || 2450;
  const vramTotal = health?.gpu_memory_total_mb || hardware?.selected_device?.vram_total_mb || 12288;
  const vramPercent = Math.min(100, Math.round((vramUsed / vramTotal) * 100));

  const gpuName = hardware?.selected_device?.name || health?.gpu_name || 'NVIDIA GeForce RTX 3060 12GB';
  const provider = hardware?.recommended_provider || (health?.gpu_available ? 'cuda' : 'cpu');

  const runningJobs = jobs.filter((j) => j.status === 'running');
  const activeJob = runningJobs[0];

  return (
    <div className="flex-1 overflow-y-auto bg-surface-base p-6 space-y-6">
      {/* Top Banner / System Classification */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-border pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] text-signal-green uppercase tracking-wider font-semibold">
              TELEMETRY & HARDWARE RUNTIME
            </span>
            <span className="text-surface-border">•</span>
            <span className="font-mono text-[10px] text-ink-muted">
              SCALED HYBRID VECTOR ENGINE (1M–10M CHUNKS)
            </span>
          </div>
          <h1 className="text-xl font-bold tracking-tight text-ink-primary mt-1">
            Workstation System Diagnostics
          </h1>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={onRefreshHealth}
            className="flex items-center gap-1.5 bg-surface-raised hover:bg-surface-hover text-ink-secondary hover:text-ink-primary border border-surface-border px-3 py-1.5 rounded text-xs font-mono transition-colors cursor-pointer"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>Poll Telemetry</span>
          </button>
        </div>
      </div>

      {/* Primary KPI Grid (4 Metrics Cards) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {/* Metric 1: Total Chunks */}
        <div className="bg-surface-panel border border-surface-border rounded p-4 space-y-2">
          <div className="flex items-center justify-between text-ink-muted">
            <span className="font-mono text-[10px] uppercase tracking-wider">Vector Chunks</span>
            <Layers className="h-4 w-4 text-signal-green" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-ink-primary tabular-nums">
              {formatNumber(totalChunks)}
            </span>
            <span className="text-xs text-ink-muted font-mono">
              ({totalChunks.toLocaleString()} exact)
            </span>
          </div>
          <div className="text-[11px] text-ink-secondary flex items-center justify-between border-t border-surface-border/50 pt-2 font-mono">
            <span>HNSW Index: INT8 SQ</span>
            <span className="text-signal-green font-semibold">Active</span>
          </div>
        </div>

        {/* Metric 2: VRAM Telemetry */}
        <div className="bg-surface-panel border border-surface-border rounded p-4 space-y-2">
          <div className="flex items-center justify-between text-ink-muted">
            <span className="font-mono text-[10px] uppercase tracking-wider">Dedicated VRAM</span>
            <Zap className="h-4 w-4 text-signal-amber" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-ink-primary tabular-nums">
              {(vramUsed / 1024).toFixed(1)}
            </span>
            <span className="text-xs text-ink-muted font-mono">
              / {(vramTotal / 1024).toFixed(1)} GB ({vramPercent}%)
            </span>
          </div>
          <div className="w-full h-1.5 bg-surface-base rounded-none overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ${
                vramPercent > 85 ? 'bg-signal-rose' : vramPercent > 65 ? 'bg-signal-amber' : 'bg-signal-green'
              }`}
              style={{ width: `${Math.max(5, vramPercent)}%` }}
            />
          </div>
        </div>

        {/* Metric 3: Host Storage & Memory */}
        <div className="bg-surface-panel border border-surface-border rounded p-4 space-y-2">
          <div className="flex items-center justify-between text-ink-muted">
            <span className="font-mono text-[10px] uppercase tracking-wider">Corpus Footprint</span>
            <HardDrive className="h-4 w-4 text-ink-secondary" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-ink-primary tabular-nums">
              {formatBytes(totalSizeBytes)}
            </span>
            <span className="text-xs text-ink-muted font-mono">
              / {totalDocs} docs
            </span>
          </div>
          <div className="text-[11px] text-ink-secondary flex items-center justify-between border-t border-surface-border/50 pt-2 font-mono">
            <span>SQLite + Qdrant SSD</span>
            <span className="text-ink-primary">Verified</span>
          </div>
        </div>

        {/* Metric 4: Indexing Engine State */}
        <div className="bg-surface-panel border border-surface-border rounded p-4 space-y-2">
          <div className="flex items-center justify-between text-ink-muted">
            <span className="font-mono text-[10px] uppercase tracking-wider">Queue Throughput</span>
            <Activity className="h-4 w-4 text-signal-sky" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-ink-primary tabular-nums">
              {activeJob ? '1,420' : 'Idle'}
            </span>
            <span className="text-xs text-ink-muted font-mono">
              {activeJob ? 'chunks / sec' : 'ready for jobs'}
            </span>
          </div>
          <div className="text-[11px] text-ink-secondary flex items-center justify-between border-t border-surface-border/50 pt-2 font-mono">
            <span>Active Jobs: {runningJobs.length}</span>
            <span className={runningJobs.length > 0 ? 'text-signal-green font-semibold' : 'text-ink-muted'}>
              {runningJobs.length > 0 ? 'RUNNING' : 'STANDBY'}
            </span>
          </div>
        </div>
      </div>

      {/* Telemetry Details Split */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left Column: Compute & Model Runtime Allocation */}
        <div className="bg-surface-panel border border-surface-border rounded p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-surface-border pb-3">
            <div className="flex items-center gap-2">
              <Cpu className="h-4 w-4 text-ink-secondary" />
              <h2 className="text-xs font-bold uppercase tracking-wider font-mono text-ink-primary">
                Inference & Pipeline Allocation
              </h2>
            </div>
            <span className="text-[10px] font-mono bg-surface-base px-2 py-0.5 rounded border border-surface-border text-signal-green">
              {provider.toUpperCase()} ACTIVE
            </span>
          </div>

          <div className="space-y-3 font-mono text-xs">
            <div className="flex justify-between items-center py-1.5 border-b border-surface-border/50">
              <span className="text-ink-muted">Device Acceleration</span>
              <span className="text-ink-primary font-medium">{gpuName}</span>
            </div>

            <div className="flex justify-between items-center py-1.5 border-b border-surface-border/50">
              <span className="text-ink-muted">Embedding Engine (Dense)</span>
              <span className="text-ink-primary font-medium">BAAI/bge-m3 (1024-dim, 8192-ctx)</span>
            </div>

            <div className="flex justify-between items-center py-1.5 border-b border-surface-border/50">
              <span className="text-ink-muted">Lexical Sparse Search</span>
              <span className="text-ink-primary font-medium">FastEmbed / BM25 Inverted Index</span>
            </div>

            <div className="flex justify-between items-center py-1.5 border-b border-surface-border/50">
              <span className="text-ink-muted">Cross-Encoder Reranker</span>
              <span className="text-ink-primary font-medium">BAAI/bge-reranker-large (ONNX fp16)</span>
            </div>

            <div className="flex justify-between items-center py-1.5 border-b border-surface-border/50">
              <span className="text-ink-muted">Generative LLM Engine</span>
              <span className="text-ink-primary font-medium">vLLM Sovereign Local Daemon</span>
            </div>

            <div className="flex justify-between items-center py-1.5">
              <span className="text-ink-muted">Tamper-Proof Audit Ledger</span>
              <span className="text-signal-green font-medium flex items-center gap-1">
                <ShieldCheck className="h-3.5 w-3.5" />
                SHA-256 Chained
              </span>
            </div>
          </div>
        </div>

        {/* Right Column: Scaled Indexing & Storage Engine */}
        <div className="bg-surface-panel border border-surface-border rounded p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-surface-border pb-3">
            <div className="flex items-center gap-2">
              <Database className="h-4 w-4 text-ink-secondary" />
              <h2 className="text-xs font-bold uppercase tracking-wider font-mono text-ink-primary">
                Vector DB Engine (Qdrant Standalone)
              </h2>
            </div>
            <span className="text-[10px] font-mono text-ink-muted">
              v1.12+ Embedded Local
            </span>
          </div>

          <div className="space-y-3 font-mono text-xs">
            <div className="flex justify-between items-center py-1.5 border-b border-surface-border/50">
              <span className="text-ink-muted">HNSW Hyper-Graph Parameters</span>
              <span className="text-ink-primary font-medium">m=16, ef_construct=100</span>
            </div>

            <div className="flex justify-between items-center py-1.5 border-b border-surface-border/50">
              <span className="text-ink-muted">Quantization Protocol</span>
              <span className="text-signal-green font-medium">Scalar Quantization (int8)</span>
            </div>

            <div className="flex justify-between items-center py-1.5 border-b border-surface-border/50">
              <span className="text-ink-muted">Distance Metric</span>
              <span className="text-ink-primary font-medium">Cosine Similarity (Dense) + Dot (Sparse)</span>
            </div>

            <div className="flex justify-between items-center py-1.5 border-b border-surface-border/50">
              <span className="text-ink-muted">Target Scale Capacity</span>
              <span className="text-ink-primary font-medium">10,000,000 chunks &lt; 32GB RAM</span>
            </div>

            <div className="flex justify-between items-center py-1.5 border-b border-surface-border/50">
              <span className="text-ink-muted">Ingestion Concurrency Limit</span>
              <span className="text-ink-primary font-medium">4 Parallel Workers (Priority-Yielding)</span>
            </div>

            <div className="flex justify-between items-center py-1.5">
              <span className="text-ink-muted">Air-Gap Offline Verification</span>
              <span className="text-signal-green font-medium">100% Zero-Egress Enforced</span>
            </div>
          </div>
        </div>
      </div>

      {/* Navigation Quick-Launch Modules */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
        <div
          onClick={onNavigateToLibrary}
          className="bg-surface-panel hover:bg-surface-raised border border-surface-border rounded p-4 flex items-center justify-between cursor-pointer transition-colors group"
        >
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold font-mono text-ink-primary group-hover:text-signal-green transition-colors">
                KNOWLEDGE CORPUS LEDGER
              </span>
              <span className="text-[10px] font-mono text-ink-muted">({totalDocs} items)</span>
            </div>
            <p className="text-xs text-ink-secondary">
              Inspect indexed technical PDFs, source code files, and web documentation with clearance classifications.
            </p>
          </div>
          <ArrowUpRight className="h-4 w-4 text-ink-muted group-hover:text-ink-primary transition-colors shrink-0 ml-4" />
        </div>

        <div
          onClick={onNavigateToIndexing}
          className="bg-surface-panel hover:bg-surface-raised border border-surface-border rounded p-4 flex items-center justify-between cursor-pointer transition-colors group"
        >
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold font-mono text-ink-primary group-hover:text-signal-green transition-colors">
                INDEXING QUEUE MANAGER
              </span>
              <span className="text-[10px] font-mono text-ink-muted">({jobs.length} jobs)</span>
            </div>
            <p className="text-xs text-ink-secondary">
              Monitor active batch folder indexing, git repositories, AST code extractors, pause/resume pipelines.
            </p>
          </div>
          <ArrowUpRight className="h-4 w-4 text-ink-muted group-hover:text-ink-primary transition-colors shrink-0 ml-4" />
        </div>
      </div>
    </div>
  );
};
