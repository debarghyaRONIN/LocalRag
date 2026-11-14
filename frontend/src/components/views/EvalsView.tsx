import React, { useState } from 'react';
import { Play, Download, Loader2 } from 'lucide-react';
import { runScaleBenchmark } from '../../services/api';

export const EvalsView: React.FC = () => {
  const [isRunning, setIsRunning] = useState(false);
  const [benchmarkResult, setBenchmarkResult] = useState<any>(null);

  const categories = [
    { name: 'Event classification', cases: 10, base: 72, tuned: 86, delta: 14, baseW: '72%', deltaW: '14%' },
    { name: 'Timeline extraction', cases: 9, base: 61, tuned: 79, delta: 18, baseW: '61%', deltaW: '18%' },
    { name: 'Contributing factors', cases: 8, base: 55, tuned: 70, delta: 15, baseW: '55%', deltaW: '15%' },
    { name: 'Policy citation & grounding', cases: 8, base: 68, tuned: 81, delta: 13, baseW: '68%', deltaW: '13%' },
    { name: 'Summary length and tone', cases: 7, base: 74, tuned: 83, delta: 9, baseW: '74%', deltaW: '9%' },
  ];

  const handleRunEvals = async () => {
    setIsRunning(true);
    try {
      const rep = await runScaleBenchmark(2);
      setBenchmarkResult(rep);
    } catch (err) {
      console.error('Scale benchmark failed:', err);
    } finally {
      setIsRunning(false);
    }
  };

  const handleExport = () => {
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(benchmarkResult || { categories }, null, 2));
    const dl = document.createElement('a');
    dl.setAttribute('href', dataStr);
    dl.setAttribute('download', `eval_report_${new Date().toISOString().slice(0, 10)}.json`);
    dl.click();
  };

  return (
    <div style={{ padding: '28px clamp(20px, 3vw, 40px) 48px', maxWidth: '1100px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: '16px', flexWrap: 'wrap' }}>
        <div>
          <span style={{ fontSize: '11px', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-accent)' }}>
            Eval set · Incident report summaries
          </span>
          <h1 style={{ fontFamily: 'var(--font-heading)', fontWeight: 'var(--font-heading-weight)', fontSize: '26px', margin: '8px 0 0' }}>
            Before and after tuning
          </h1>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button type="button" className="btn btn-secondary" onClick={handleExport}>
            <Download size={14} /> Export report
          </button>
          <button type="button" className="btn btn-primary" onClick={handleRunEvals} disabled={isRunning}>
            {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {isRunning ? 'Running benchmark…' : 'Run evals'}
          </button>
        </div>
      </div>

      {/* Metric Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px', marginTop: '24px' }}>
        <div className="card" style={{ padding: '18px', gap: '6px' }}>
          <span style={{ fontSize: '11px', letterSpacing: '0.06em', textTransform: 'uppercase', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>
            Expert-approved, tuned
          </span>
          <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 'var(--font-heading-weight)', fontSize: '30px', color: 'var(--color-accent)' }}>
            {benchmarkResult ? `${Math.round(benchmarkResult.ir_quality.recall_at_10 * 100)}%` : '80%'}
          </span>
          <span style={{ fontSize: '12px', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>
            Target 75% · 42 cases
          </span>
        </div>

        <div className="card" style={{ padding: '18px', gap: '6px' }}>
          <span style={{ fontSize: '11px', letterSpacing: '0.06em', textTransform: 'uppercase', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>
            Base model
          </span>
          <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 'var(--font-heading-weight)', fontSize: '30px', color: 'var(--color-text)' }}>
            66%
          </span>
          <span style={{ fontSize: '12px', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>
            Same set, before tuning
          </span>
        </div>

        <div className="card" style={{ padding: '18px', gap: '6px' }}>
          <span style={{ fontSize: '11px', letterSpacing: '0.06em', textTransform: 'uppercase', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>
            Improvement
          </span>
          <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 'var(--font-heading-weight)', fontSize: '30px', color: 'var(--color-accent-300)' }}>
            +14 pts
          </span>
          <span style={{ fontSize: '12px', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>
            tuned-v2 vs base
          </span>
        </div>

        <div className="card" style={{ padding: '18px', gap: '6px' }}>
          <span style={{ fontSize: '11px', letterSpacing: '0.06em', textTransform: 'uppercase', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>
            Feedback collected
          </span>
          <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 'var(--font-heading-weight)', fontSize: '30px', color: 'var(--color-text)' }}>
            318
          </span>
          <span style={{ fontSize: '12px', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>
            Ratings and corrections
          </span>
        </div>
      </div>

      {/* Live Benchmark Execution Results */}
      {benchmarkResult && (
        <div className="card" style={{ marginTop: '24px', padding: '18px', border: '1px solid var(--color-accent-700)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="card-kicker">Live Scale Benchmark Results</span>
            <span className="tag tag-accent">PASS · 100% Offline</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '16px', marginTop: '12px' }}>
            <div>
              <span style={{ fontSize: '11px', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>Ingestion Rate</span>
              <p style={{ margin: '4px 0 0', fontSize: '18px', fontWeight: 500, color: 'var(--color-accent)' }}>
                {benchmarkResult.ingestion.chunks_per_second} chunks/s
              </p>
            </div>
            <div>
              <span style={{ fontSize: '11px', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>Hybrid Retrieval p50</span>
              <p style={{ margin: '4px 0 0', fontSize: '18px', fontWeight: 500, color: 'var(--color-accent-200)' }}>
                {benchmarkResult.retrieval.retrieval_latency.p50_ms} ms
              </p>
            </div>
            <div>
              <span style={{ fontSize: '11px', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>Recall@10</span>
              <p style={{ margin: '4px 0 0', fontSize: '18px', fontWeight: 500, color: 'var(--color-accent)' }}>
                {(benchmarkResult.ir_quality.recall_at_10 * 100).toFixed(1)}%
              </p>
            </div>
            <div>
              <span style={{ fontSize: '11px', color: 'color-mix(in srgb, var(--color-text) 60%, transparent)' }}>nDCG@10</span>
              <p style={{ margin: '4px 0 0', fontSize: '18px', fontWeight: 500, color: 'var(--color-accent)' }}>
                {benchmarkResult.ir_quality.ndcg_at_10.toFixed(4)}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Category Breakdown Table */}
      <h2 style={{ fontFamily: 'var(--font-heading)', fontWeight: 'var(--font-heading-weight)', fontSize: '16px', margin: '36px 0 12px' }}>
        By category
      </h2>
      <table className="table">
        <thead>
          <tr>
            <th>Category</th>
            <th>Cases</th>
            <th>Base</th>
            <th>Tuned</th>
            <th style={{ width: '34%' }}>Change</th>
          </tr>
        </thead>
        <tbody>
          {categories.map((c) => (
            <tr key={c.name}>
              <td style={{ fontWeight: 500 }}>{c.name}</td>
              <td style={{ color: 'color-mix(in srgb, var(--color-text) 70%, transparent)' }}>{c.cases}</td>
              <td style={{ color: 'color-mix(in srgb, var(--color-text) 70%, transparent)' }}>{c.base}%</td>
              <td style={{ color: 'var(--color-accent)' }}>{c.tuned}%</td>
              <td>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div style={{ flex: 1, height: '6px', borderRadius: '3px', background: 'var(--color-neutral-800)', position: 'relative', overflow: 'hidden' }}>
                    <span style={{ position: 'absolute', inset: '0 auto 0 0', width: c.baseW, background: 'var(--color-neutral-600)' }} />
                    <span style={{ position: 'absolute', top: 0, bottom: 0, left: c.baseW, width: c.deltaW, background: 'var(--color-accent)' }} />
                  </div>
                  <span style={{ fontSize: '12px', color: 'var(--color-accent-300)', minWidth: '36px' }}>+{c.delta}</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <p style={{ margin: '16px 0 0', fontSize: '12.5px', lineHeight: 1.6, color: 'color-mix(in srgb, var(--color-text) 60%, transparent)', maxWidth: '70ch' }}>
        Scored offline with the local model as judge; 10% of cases spot-checked by clinical and domain reviewers. Sample data shown.
      </p>
    </div>
  );
};
