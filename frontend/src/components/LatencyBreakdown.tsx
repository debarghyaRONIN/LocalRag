import React from 'react';
import type { LatencyBreakdown as LatencyType } from '../types';

interface LatencyProps {
  latency?: LatencyType;
}

export const LatencyBreakdownBadge: React.FC<LatencyProps> = ({ latency }) => {
  if (!latency) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-2 font-mono text-[10px] text-ink-muted border-t border-surface-border/60">
      {latency.total_ms !== undefined && (
        <span className="text-ink-secondary tabular-nums">
          total <span className="text-ink-primary font-semibold">{(latency.total_ms / 1000).toFixed(2)}s</span>
        </span>
      )}

      {latency.ttft_ms !== undefined && (
        <span className="text-ink-secondary tabular-nums">
          ttft <span className="text-signal-green font-semibold">{latency.ttft_ms.toFixed(0)}ms</span>
        </span>
      )}

      {latency.embed_ms !== undefined && (
        <span className="tabular-nums">
          embed {latency.embed_ms.toFixed(0)}ms
        </span>
      )}

      {latency.retrieval_ms !== undefined && (
        <span className="tabular-nums">
          qdrant {latency.retrieval_ms.toFixed(0)}ms
        </span>
      )}

      {latency.rerank_ms !== undefined && (
        <span className="tabular-nums">
          rerank {latency.rerank_ms.toFixed(0)}ms
        </span>
      )}
    </div>
  );
};
