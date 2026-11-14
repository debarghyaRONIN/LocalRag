import React, { useState } from 'react';
import {
  Sliders,
  Cpu,
  Layers,
  Database,
  Save,
  RotateCcw,
  CheckCircle2,
  Network,
  ShieldCheck,
  Server,
  Radio,
  AlertCircle,
  Loader2,
} from 'lucide-react';
import type { AppSettings, HardwareInfo } from '../../types';
import { getSavedSettings, saveSettings, DEFAULT_SETTINGS } from '../../services/api';

interface SettingsViewProps {
  hardware?: HardwareInfo | null;
  onSettingsSaved?: (settings: AppSettings) => void;
}

export const SettingsView: React.FC<SettingsViewProps> = ({
  hardware,
  onSettingsSaved,
}) => {
  const [settings, setSettings] = useState<AppSettings>(() => getSavedSettings());
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [testStatus, setTestStatus] = useState<{ ok: boolean; message: string } | null>(null);
  const [isTesting, setIsTesting] = useState(false);

  const handleTestInference = async () => {
    setIsTesting(true);
    setTestStatus(null);
    try {
      const target = (settings.inference_base_url || 'http://localhost:8001/v1').replace(/\/$/, '');
      const res = await fetch(`${target}/models`, {
        signal: AbortSignal.timeout(3000),
      });
      if (res.ok) {
        const data = await res.json().catch(() => ({}));
        const modelList = data.data?.map((m: any) => m.id).join(', ') || settings.active_model_name;
        setTestStatus({ ok: true, message: `Connected! Model(s): ${modelList}` });
      } else {
        setTestStatus({ ok: false, message: `HTTP ${res.status}: Server returned error status.` });
      }
    } catch (e: any) {
      setTestStatus({ ok: false, message: `Could not reach ${settings.inference_base_url}. Ensure local engine is running.` });
    } finally {
      setIsTesting(false);
    }
  };

  const handleChange = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = () => {
    saveSettings(settings);
    setSaveSuccess(true);
    if (onSettingsSaved) onSettingsSaved(settings);
    setTimeout(() => setSaveSuccess(false), 3000);
  };

  const handleReset = () => {
    if (window.confirm('Reset all workstation retrieval and hardware settings to defaults?')) {
      setSettings(DEFAULT_SETTINGS);
      saveSettings(DEFAULT_SETTINGS);
      if (onSettingsSaved) onSettingsSaved(DEFAULT_SETTINGS);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto bg-surface-base p-6 space-y-6">
      {/* Header Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-border pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] text-signal-green uppercase tracking-wider font-semibold">
              PIPELINE HYPERPARAMETERS & HARDWARE CONFIGURATION
            </span>
            <span className="text-surface-border">•</span>
            <span className="font-mono text-[10px] text-ink-muted">
              PERSISTENT WORKSTATION STATE
            </span>
          </div>
          <h1 className="text-xl font-bold tracking-tight text-ink-primary mt-1">
            Retrieval & Engine Settings
          </h1>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleReset}
            className="flex items-center gap-1.5 bg-surface-raised hover:bg-surface-hover text-ink-secondary hover:text-ink-primary border border-surface-border px-3 py-1.5 rounded text-xs font-mono transition-colors cursor-pointer"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            <span>Reset Defaults</span>
          </button>

          <button
            onClick={handleSave}
            className="flex items-center gap-1.5 bg-ink-primary hover:bg-white text-surface-base font-semibold px-4 py-1.5 rounded text-xs font-mono transition-colors cursor-pointer"
          >
            <Save className="h-3.5 w-3.5" />
            <span>Save Configuration</span>
          </button>
        </div>
      </div>

      {/* Save Success Banner */}
      {saveSuccess && (
        <div className="bg-signal-green/10 border border-signal-green/30 px-4 py-2 rounded text-xs font-mono text-signal-green flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>Workstation retrieval configuration and hardware allocations saved successfully.</span>
        </div>
      )}

      {/* Settings Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Section 1: Retrieval & Reranker Settings */}
        <div className="bg-surface-panel border border-surface-border rounded p-5 space-y-5">
          <div className="flex items-center gap-2 border-b border-surface-border pb-3">
            <Sliders className="h-4 w-4 text-signal-green" />
            <h2 className="text-xs font-bold uppercase tracking-wider font-mono text-ink-primary">
              Multi-Stage Retrieval & Reranking
            </h2>
          </div>

          {/* Top-K Chunks */}
          <div className="space-y-2">
            <div className="flex justify-between items-center font-mono text-xs">
              <label className="text-ink-secondary">Top-K Retrieved Chunks</label>
              <span className="text-ink-primary font-bold bg-surface-base px-2 py-0.5 rounded border border-surface-border">
                {settings.top_k}
              </span>
            </div>
            <input
              type="range"
              min={1}
              max={20}
              step={1}
              value={settings.top_k}
              onChange={(e) => handleChange('top_k', parseInt(e.target.value, 10))}
              className="w-full accent-signal-green cursor-pointer"
            />
            <p className="text-[11px] text-ink-muted">
              Number of most relevant child passages dispatched to the LLM prompt context after cross-encoder scoring.
            </p>
          </div>

          {/* Min Rerank Score */}
          <div className="space-y-2">
            <div className="flex justify-between items-center font-mono text-xs">
              <label className="text-ink-secondary">Cross-Encoder Cutoff Threshold</label>
              <span className="text-ink-primary font-bold bg-surface-base px-2 py-0.5 rounded border border-surface-border">
                {settings.min_rerank_score.toFixed(2)}
              </span>
            </div>
            <input
              type="range"
              min={0.0}
              max={0.9}
              step={0.05}
              value={settings.min_rerank_score}
              onChange={(e) => handleChange('min_rerank_score', parseFloat(e.target.value))}
              className="w-full accent-signal-green cursor-pointer"
            />
            <p className="text-[11px] text-ink-muted">
              Chunks with ONNX cross-encoder rerank score below this threshold are purged as hallucinations or noise.
            </p>
          </div>

          {/* Context Budget */}
          <div className="space-y-2">
            <div className="flex justify-between items-center font-mono text-xs">
              <label className="text-ink-secondary">Context Token Budget</label>
              <span className="text-ink-primary font-bold bg-surface-base px-2 py-0.5 rounded border border-surface-border">
                {settings.context_budget_tokens.toLocaleString()} tokens
              </span>
            </div>
            <input
              type="range"
              min={1024}
              max={16384}
              step={512}
              value={settings.context_budget_tokens}
              onChange={(e) => handleChange('context_budget_tokens', parseInt(e.target.value, 10))}
              className="w-full accent-signal-green cursor-pointer"
            />
            <p className="text-[11px] text-ink-muted">
              Maximum allowable tokens reserved for grounded source passages inside the generation window.
            </p>
          </div>

          {/* Dense vs Sparse Ratio */}
          <div className="space-y-2">
            <div className="flex justify-between items-center font-mono text-xs">
              <label className="text-ink-secondary">Hybrid Search Ratio (Dense vs BM25)</label>
              <span className="text-ink-primary font-bold bg-surface-base px-2 py-0.5 rounded border border-surface-border">
                {(settings.dense_weight * 100).toFixed(0)}% Dense / {((1 - settings.dense_weight) * 100).toFixed(0)}% Sparse
              </span>
            </div>
            <input
              type="range"
              min={0.1}
              max={0.9}
              step={0.05}
              value={settings.dense_weight}
              onChange={(e) => {
                const dw = parseFloat(e.target.value);
                handleChange('dense_weight', dw);
                handleChange('sparse_weight', parseFloat((1 - dw).toFixed(2)));
              }}
              className="w-full accent-signal-green cursor-pointer"
            />
            <p className="text-[11px] text-ink-muted">
              Balance between deep semantic dense vector search (BGE-M3) and exact keyword lexical matching (BM25).
            </p>
          </div>
        </div>

        {/* Section 2: Chunking & Layout Parameters */}
        <div className="bg-surface-panel border border-surface-border rounded p-5 space-y-5">
          <div className="flex items-center gap-2 border-b border-surface-border pb-3">
            <Layers className="h-4 w-4 text-signal-sky" />
            <h2 className="text-xs font-bold uppercase tracking-wider font-mono text-ink-primary">
              Hierarchical Chunking Hyperparameters
            </h2>
          </div>

          {/* Parent Chunk Size */}
          <div className="space-y-2">
            <div className="flex justify-between items-center font-mono text-xs">
              <label className="text-ink-secondary">Parent Chunk Size</label>
              <span className="text-ink-primary font-bold bg-surface-base px-2 py-0.5 rounded border border-surface-border">
                {settings.parent_chunk_size} tokens
              </span>
            </div>
            <input
              type="range"
              min={500}
              max={4000}
              step={100}
              value={settings.parent_chunk_size}
              onChange={(e) => handleChange('parent_chunk_size', parseInt(e.target.value, 10))}
              className="w-full accent-signal-sky cursor-pointer"
            />
            <p className="text-[11px] text-ink-muted">
              Broader contextual window stored in SQLite and pulled for full paragraph citation verification.
            </p>
          </div>

          {/* Child Chunk Size */}
          <div className="space-y-2">
            <div className="flex justify-between items-center font-mono text-xs">
              <label className="text-ink-secondary">Child Chunk Size (Vector Embedding Target)</label>
              <span className="text-ink-primary font-bold bg-surface-base px-2 py-0.5 rounded border border-surface-border">
                {settings.child_chunk_size} tokens
              </span>
            </div>
            <input
              type="range"
              min={100}
              max={800}
              step={50}
              value={settings.child_chunk_size}
              onChange={(e) => handleChange('child_chunk_size', parseInt(e.target.value, 10))}
              className="w-full accent-signal-sky cursor-pointer"
            />
            <p className="text-[11px] text-ink-muted">
              Granular passage vector embedded in Qdrant for pinpoint similarity search and sentence attribution.
            </p>
          </div>

          {/* Chunk Overlap */}
          <div className="space-y-2">
            <div className="flex justify-between items-center font-mono text-xs">
              <label className="text-ink-secondary">Chunk Boundary Overlap</label>
              <span className="text-ink-primary font-bold bg-surface-base px-2 py-0.5 rounded border border-surface-border">
                {settings.chunk_overlap} tokens
              </span>
            </div>
            <input
              type="range"
              min={10}
              max={200}
              step={10}
              value={settings.chunk_overlap}
              onChange={(e) => handleChange('chunk_overlap', parseInt(e.target.value, 10))}
              className="w-full accent-signal-sky cursor-pointer"
            />
            <p className="text-[11px] text-ink-muted">
              Token overlap between contiguous chunks to preserve cross-sentence semantic continuity.
            </p>
          </div>
        </div>

        {/* Section 3: Hardware Acceleration & Scale */}
        <div className="bg-surface-panel border border-surface-border rounded p-5 space-y-5">
          <div className="flex items-center gap-2 border-b border-surface-border pb-3">
            <Cpu className="h-4 w-4 text-signal-amber" />
            <h2 className="text-xs font-bold uppercase tracking-wider font-mono text-ink-primary">
              Hardware Engine & Quantization Allocation
            </h2>
          </div>

          {/* Provider Selection */}
          <div className="space-y-2">
            <div className="flex justify-between items-center">
              <label className="font-mono text-xs text-ink-secondary block">
                Acceleration Backend
              </label>
              {hardware?.selected_device?.name && (
                <span className="font-mono text-[10px] text-ink-muted">
                  Detected: {hardware.selected_device.name}
                </span>
              )}
            </div>
            <div className="grid grid-cols-3 gap-2">
              {[
                { id: 'cuda', label: 'CUDA', desc: 'NVIDIA GPU' },
                { id: 'rocm', label: 'ROCm', desc: 'AMD GPU' },
                { id: 'cpu', label: 'CPU', desc: 'AVX-512 / Host' },
              ].map((prov) => (
                <button
                  key={prov.id}
                  type="button"
                  onClick={() => handleChange('hardware_allocation', prov.id as any)}
                  className={`p-3 rounded border text-left transition-colors cursor-pointer ${
                    settings.hardware_allocation === prov.id
                      ? 'bg-surface-raised border-signal-green text-ink-primary'
                      : 'bg-surface-base border-surface-border text-ink-muted hover:text-ink-secondary'
                  }`}
                >
                  <div className="font-mono font-bold text-xs">{prov.label}</div>
                  <div className="text-[10px] text-ink-muted mt-0.5">{prov.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Embedding Batch Size */}
          <div className="space-y-2">
            <label className="font-mono text-xs text-ink-secondary block">
              Batch Vectorization Size
            </label>
            <select
              value={settings.embedding_batch_size}
              onChange={(e) => handleChange('embedding_batch_size', parseInt(e.target.value, 10))}
              className="w-full bg-surface-base border border-surface-border rounded px-3 py-1.5 text-xs font-mono text-ink-primary focus:outline-none focus:border-ink-faint cursor-pointer"
            >
              <option value={16}>16 chunks (Low VRAM)</option>
              <option value={32}>32 chunks (Balanced / Default)</option>
              <option value={64}>64 chunks (High VRAM)</option>
              <option value={128}>128 chunks (Extreme Throughput)</option>
            </select>
          </div>

          {/* Scalar Quantization Toggle */}
          <div className="pt-2 flex items-center justify-between border-t border-surface-border/50">
            <div className="space-y-0.5 pr-4">
              <span className="font-mono text-xs text-ink-primary block font-medium">
                Scalar Quantization (INT8 Compression)
              </span>
              <span className="text-[11px] text-ink-muted block font-sans">
                Compacts 1024-dim dense float32 vectors to 8-bit integers, reducing RAM consumption by 75% for 1M-10M chunks with &gt;99% recall.
              </span>
            </div>
            <button
              type="button"
              onClick={() => handleChange('scalar_quantization', !settings.scalar_quantization)}
              className={`w-11 h-6 rounded-full transition-colors relative cursor-pointer shrink-0 ${
                settings.scalar_quantization ? 'bg-signal-green' : 'bg-surface-border'
              }`}
            >
              <div
                className={`w-4 h-4 rounded-full bg-surface-base transition-transform absolute top-1 ${
                  settings.scalar_quantization ? 'left-6' : 'left-1'
                }`}
              />
            </button>
          </div>
        </div>

        {/* Section 4: HNSW & Vector Graph Topology */}
        <div className="bg-surface-panel border border-surface-border rounded p-5 space-y-5">
          <div className="flex items-center gap-2 border-b border-surface-border pb-3">
            <Database className="h-4 w-4 text-ink-secondary" />
            <h2 className="text-xs font-bold uppercase tracking-wider font-mono text-ink-primary">
              HNSW Hypergraph Topology (Qdrant)
            </h2>
          </div>

          {/* HNSW M */}
          <div className="space-y-2">
            <div className="flex justify-between items-center font-mono text-xs">
              <label className="text-ink-secondary">m (Node Edge Degree)</label>
              <span className="text-ink-primary font-bold bg-surface-base px-2 py-0.5 rounded border border-surface-border">
                {settings.hnsw_m}
              </span>
            </div>
            <input
              type="range"
              min={8}
              max={64}
              step={4}
              value={settings.hnsw_m}
              onChange={(e) => handleChange('hnsw_m', parseInt(e.target.value, 10))}
              className="w-full accent-ink-primary cursor-pointer"
            />
            <p className="text-[11px] text-ink-muted">
              Number of bi-directional links created per vector node. Higher values improve recall on complex high-dimensional manifolds.
            </p>
          </div>

          {/* HNSW EF_CONSTRUCT */}
          <div className="space-y-2">
            <div className="flex justify-between items-center font-mono text-xs">
              <label className="text-ink-secondary">ef_construct (Graph Construction Horizon)</label>
              <span className="text-ink-primary font-bold bg-surface-base px-2 py-0.5 rounded border border-surface-border">
                {settings.hnsw_ef_construct}
              </span>
            </div>
            <input
              type="range"
              min={50}
              max={400}
              step={25}
              value={settings.hnsw_ef_construct}
              onChange={(e) => handleChange('hnsw_ef_construct', parseInt(e.target.value, 10))}
              className="w-full accent-ink-primary cursor-pointer"
            />
            <p className="text-[11px] text-ink-muted">
              Size of the dynamic candidate list during graph indexing. 100 provides optimal indexing speed vs accuracy trade-off.
            </p>
          </div>

          {/* Clearance Default Filter */}
          <div className="pt-2 border-t border-surface-border/50 space-y-2">
            <label className="font-mono text-xs text-ink-secondary block">
              Default Clearance Filter for User Inquiries
            </label>
            <div className="flex items-center gap-2">
              {[
                { lvl: 1, label: 'L1 Public' },
                { lvl: 2, label: 'L2 Internal' },
                { lvl: 3, label: 'L3 Confidential' },
                { lvl: 4, label: 'L4 Top Secret' },
              ].map((item) => (
                <button
                  key={item.lvl}
                  type="button"
                  onClick={() => handleChange('clearance_level_filter', item.lvl)}
                  className={`px-2.5 py-1 text-xs font-mono rounded border transition-colors cursor-pointer ${
                    (settings.clearance_level_filter ?? 1) === item.lvl
                      ? 'bg-ink-primary text-surface-base border-ink-primary font-bold'
                      : 'bg-surface-base border-surface-border text-ink-muted hover:text-ink-secondary'
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Section 5: Local Machine & Air-Gapped Network Configuration */}
        <div className="bg-surface-panel border border-surface-border rounded p-5 space-y-5">
          <div className="flex items-center gap-2 border-b border-surface-border pb-3">
            <Network className="h-4 w-4 text-signal-green" />
            <h2 className="text-xs font-bold uppercase tracking-wider font-mono text-ink-primary">
              Air-Gapped Network & Workstation Topology
            </h2>
          </div>

          {/* Deployment Mode */}
          <div className="space-y-2">
            <label className="font-mono text-xs text-ink-secondary block">
              Node Network Binding Mode
            </label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => {
                  handleChange('node_mode', 'localhost');
                  handleChange('network_bind_host', '127.0.0.1');
                }}
                className={`p-3 rounded border text-left transition-colors cursor-pointer ${
                  settings.node_mode === 'localhost'
                    ? 'bg-surface-raised border-signal-green text-ink-primary'
                    : 'bg-surface-base border-surface-border text-ink-muted hover:text-ink-secondary'
                }`}
              >
                <div className="font-mono font-bold text-xs flex items-center gap-1.5">
                  <ShieldCheck className="h-3.5 w-3.5 text-signal-green" />
                  <span>Standalone Localhost</span>
                </div>
                <div className="text-[10px] text-ink-muted mt-0.5">
                  127.0.0.1 · Isolated to this local PC only.
                </div>
              </button>

              <button
                type="button"
                onClick={() => {
                  handleChange('node_mode', 'lan_airgap');
                  handleChange('network_bind_host', '0.0.0.0');
                }}
                className={`p-3 rounded border text-left transition-colors cursor-pointer ${
                  settings.node_mode === 'lan_airgap'
                    ? 'bg-surface-raised border-signal-sky text-ink-primary'
                    : 'bg-surface-base border-surface-border text-ink-muted hover:text-ink-secondary'
                }`}
              >
                <div className="font-mono font-bold text-xs flex items-center gap-1.5">
                  <Radio className="h-3.5 w-3.5 text-signal-sky" />
                  <span>Air-Gapped Private LAN</span>
                </div>
                <div className="text-[10px] text-ink-muted mt-0.5">
                  0.0.0.0 · Shareable across isolated LAN switch.
                </div>
              </button>
            </div>
          </div>

          {/* Host & Port */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="font-mono text-[11px] text-ink-secondary block">
                Network Bind Address
              </label>
              <input
                type="text"
                value={settings.network_bind_host}
                onChange={(e) => handleChange('network_bind_host', e.target.value)}
                placeholder="127.0.0.1"
                className="w-full bg-surface-base border border-surface-border rounded px-3 py-1.5 text-xs font-mono text-ink-primary focus:outline-none focus:border-ink-faint"
              />
            </div>
            <div className="space-y-1.5">
              <label className="font-mono text-[11px] text-ink-secondary block">
                Service Port
              </label>
              <input
                type="number"
                value={settings.network_port}
                onChange={(e) => handleChange('network_port', parseInt(e.target.value, 10) || 8000)}
                placeholder="8000"
                className="w-full bg-surface-base border border-surface-border rounded px-3 py-1.5 text-xs font-mono text-ink-primary focus:outline-none focus:border-ink-faint"
              />
            </div>
          </div>

          {/* Operator Name & Station ID */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="font-mono text-[11px] text-ink-secondary block">
                Operator / User Name
              </label>
              <input
                type="text"
                value={settings.operator_name}
                onChange={(e) => handleChange('operator_name', e.target.value)}
                placeholder="Dana Ruiz"
                className="w-full bg-surface-base border border-surface-border rounded px-3 py-1.5 text-xs font-mono text-ink-primary focus:outline-none focus:border-ink-faint"
              />
            </div>
            <div className="space-y-1.5">
              <label className="font-mono text-[11px] text-ink-secondary block">
                Station / Node Identifier
              </label>
              <input
                type="text"
                value={settings.station_id}
                onChange={(e) => handleChange('station_id', e.target.value)}
                placeholder="WORKSTATION-01"
                className="w-full bg-surface-base border border-surface-border rounded px-3 py-1.5 text-xs font-mono text-ink-primary focus:outline-none focus:border-ink-faint"
              />
            </div>
          </div>

          {/* Strict Air-Gap Guard Toggle */}
          <div className="pt-2 flex items-center justify-between border-t border-surface-border/50">
            <div className="space-y-0.5 pr-4">
              <span className="font-mono text-xs text-ink-primary block font-medium">
                Strict Air-Gap Socket Guard
              </span>
              <span className="text-[11px] text-ink-muted block font-sans">
                Blocks all outbound internet/WAN socket connections. Only local loopback and permitted internal subnet IPs are authorized.
              </span>
            </div>
            <button
              type="button"
              onClick={() => handleChange('airgap_strict_mode', !settings.airgap_strict_mode)}
              className={`w-11 h-6 rounded-full transition-colors relative cursor-pointer shrink-0 ${
                settings.airgap_strict_mode ? 'bg-signal-green' : 'bg-surface-border'
              }`}
            >
              <div
                className={`w-4 h-4 rounded-full bg-surface-base transition-transform absolute top-1 ${
                  settings.airgap_strict_mode ? 'left-6' : 'left-1'
                }`}
              />
            </button>
          </div>

          {/* Allowed LAN Subnets */}
          <div className="space-y-1.5">
            <label className="font-mono text-[11px] text-ink-secondary block">
              Permitted Air-Gapped Subnets (CIDR)
            </label>
            <input
              type="text"
              value={settings.allowed_lan_subnets}
              onChange={(e) => handleChange('allowed_lan_subnets', e.target.value)}
              placeholder="127.0.0.1/32, 192.168.0.0/16, 10.0.0.0/8"
              className="w-full bg-surface-base border border-surface-border rounded px-3 py-1.5 text-xs font-mono text-ink-primary focus:outline-none focus:border-ink-faint"
            />
          </div>
        </div>

        {/* Section 6: Local Inference Server & Model Gateway */}
        <div className="bg-surface-panel border border-surface-border rounded p-5 space-y-5">
          <div className="flex items-center gap-2 border-b border-surface-border pb-3">
            <Server className="h-4 w-4 text-signal-amber" />
            <h2 className="text-xs font-bold uppercase tracking-wider font-mono text-ink-primary">
              Local Inference Engine & Model Server
            </h2>
          </div>

          {/* Provider Selection */}
          <div className="space-y-2">
            <label className="font-mono text-xs text-ink-secondary block">
              Inference Engine Type
            </label>
            <div className="grid grid-cols-3 gap-2">
              {[
                {
                  id: 'vllm',
                  label: 'vLLM',
                  desc: 'High-throughput GPU',
                  url: 'http://localhost:8001/v1',
                  model: 'Qwen/Qwen2.5-3B-Instruct',
                },
                {
                  id: 'ollama',
                  label: 'Ollama',
                  desc: 'Local CPU / Apple / iGPU',
                  url: 'http://localhost:11434/v1',
                  model: 'qwen2.5:3b',
                },
                {
                  id: 'custom',
                  label: 'Custom',
                  desc: 'Air-Gap LAN Gateway',
                  url: settings.inference_base_url || 'http://127.0.0.1:8001/v1',
                  model: settings.active_model_name || 'Qwen/Qwen2.5-3B-Instruct',
                },
              ].map((prov) => (
                <button
                  key={prov.id}
                  type="button"
                  onClick={() => {
                    handleChange('inference_provider', prov.id as any);
                    if (prov.id !== 'custom') {
                      handleChange('inference_base_url', prov.url);
                      handleChange('active_model_name', prov.model);
                    }
                  }}
                  className={`p-3 rounded border text-left transition-colors cursor-pointer ${
                    settings.inference_provider === prov.id
                      ? 'bg-surface-raised border-signal-amber text-ink-primary'
                      : 'bg-surface-base border-surface-border text-ink-muted hover:text-ink-secondary'
                  }`}
                >
                  <div className="font-mono font-bold text-xs">{prov.label}</div>
                  <div className="text-[10px] text-ink-muted mt-0.5">{prov.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Base URL */}
          <div className="space-y-1.5">
            <label className="font-mono text-[11px] text-ink-secondary block">
              Inference Endpoint URL
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={settings.inference_base_url}
                onChange={(e) => handleChange('inference_base_url', e.target.value)}
                placeholder="http://localhost:8001/v1"
                className="flex-1 bg-surface-base border border-surface-border rounded px-3 py-1.5 text-xs font-mono text-ink-primary focus:outline-none focus:border-ink-faint"
              />
              <button
                type="button"
                onClick={handleTestInference}
                disabled={isTesting}
                className="bg-surface-raised hover:bg-surface-hover text-ink-primary border border-surface-border px-3 py-1.5 rounded text-xs font-mono transition-colors cursor-pointer flex items-center gap-1.5 shrink-0"
              >
                {isTesting ? <Loader2 className="h-3 w-3 animate-spin text-signal-amber" /> : <Radio className="h-3 w-3" />}
                <span>Test Link</span>
              </button>
            </div>
            {testStatus && (
              <div
                className={`mt-1.5 px-3 py-1.5 rounded text-[11px] font-mono flex items-center gap-2 ${
                  testStatus.ok
                    ? 'bg-signal-green/10 border border-signal-green/30 text-signal-green'
                    : 'bg-red-500/10 border border-red-500/30 text-red-400'
                }`}
              >
                {testStatus.ok ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0" /> : <AlertCircle className="h-3.5 w-3.5 shrink-0" />}
                <span>{testStatus.message}</span>
              </div>
            )}
          </div>

          {/* Active Model Name */}
          <div className="space-y-1.5">
            <label className="font-mono text-[11px] text-ink-secondary block">
              Active Model Identifier
            </label>
            <input
              type="text"
              value={settings.active_model_name}
              onChange={(e) => handleChange('active_model_name', e.target.value)}
              placeholder="Qwen/Qwen2.5-3B-Instruct"
              className="w-full bg-surface-base border border-surface-border rounded px-3 py-1.5 text-xs font-mono text-ink-primary focus:outline-none focus:border-ink-faint"
            />
            <p className="text-[11px] text-ink-muted">
              Must match the model loaded in vLLM or Ollama on the local machine or air-gapped node.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
