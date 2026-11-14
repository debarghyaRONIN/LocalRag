import React, { useState, useEffect } from 'react';
import { Cpu, Check, X, RefreshCw } from 'lucide-react';
import { getAvailableModels } from '../services/api';

interface ModelSelectorModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentModel: string;
  onSelectModel: (modelName: string) => void;
}

const POPULAR_PRESETS = [
  { id: 'llama3.2:latest', name: 'Llama 3.2 (3B)', desc: 'Meta 3B · Balanced speed & reasoning' },
  { id: 'qwen2.5:3b', name: 'Qwen 2.5 (3B)', desc: 'Alibaba 3B · Multilingual & structured' },
  { id: 'gemma4:latest', name: 'Gemma (Local)', desc: 'Google lightweight edge model' },
  { id: 'deepseek-r1:8b', name: 'DeepSeek R1 (8B)', desc: 'DeepSeek reasoning & chain-of-thought' },
  { id: 'mistral:latest', name: 'Mistral (7B)', desc: 'High capability general instruct' },
  { id: 'phi3:mini', name: 'Phi-3.5 Mini', desc: 'Microsoft ultra-compact edge model' },
];

export const ModelSelectorModal: React.FC<ModelSelectorModalProps> = ({
  isOpen,
  onClose,
  currentModel,
  onSelectModel,
}) => {
  const [customModel, setCustomModel] = useState('');
  const [detectedModels, setDetectedModels] = useState<string[]>([]);
  const [isLoadingDetected, setIsLoadingDetected] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setCustomModel(currentModel);
      fetchDetectedModels();
    }
  }, [isOpen, currentModel]);

  const fetchDetectedModels = async () => {
    setIsLoadingDetected(true);
    try {
      const data = await getAvailableModels();
      if (data && data.available_models) {
        setDetectedModels(data.available_models);
      }
    } catch {
      // Ignore
    } finally {
      setIsLoadingDetected(false);
    }
  };

  if (!isOpen) return null;

  const handleApply = (model: string) => {
    const clean = model.trim();
    if (clean) {
      onSelectModel(clean);
      onClose();
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        background: 'rgba(0, 0, 0, 0.65)',
        backdropFilter: 'blur(6px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px',
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: 'var(--color-surface)',
          border: '1px solid color-mix(in srgb, var(--color-text) 16%, transparent)',
          borderRadius: '16px',
          boxShadow: '0 20px 50px rgba(0, 0, 0, 0.5)',
          maxWidth: '560px',
          width: '100%',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          maxHeight: '85vh',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            padding: '18px 24px',
            borderBottom: '1px solid color-mix(in srgb, var(--color-text) 10%, transparent)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'between',
            gap: '12px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                width: '32px',
                height: '32px',
                borderRadius: '8px',
                background: 'color-mix(in srgb, var(--color-accent) 20%, transparent)',
                color: 'var(--color-accent)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Cpu size={18} />
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: '15px', fontWeight: 600, color: 'var(--color-text)' }}>
                Select Active Inference Model
              </h2>
              <p style={{ margin: 0, fontSize: '12px', color: 'color-mix(in srgb, var(--color-text) 55%, transparent)' }}>
                Specify any custom local model or select an installed runtime
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="btn btn-ghost"
            style={{ marginLeft: 'auto', padding: '6px', borderRadius: '8px' }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: '20px 24px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Custom Model Input Portion */}
          <div>
            <label
              style={{
                display: 'block',
                fontSize: '11px',
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                color: 'color-mix(in srgb, var(--color-text) 65%, transparent)',
                marginBottom: '8px',
              }}
            >
              Exact Model Identifier / Custom Model
            </label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input
                type="text"
                value={customModel}
                onChange={(e) => setCustomModel(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleApply(customModel);
                }}
                placeholder="e.g. llama3.2:latest, mistral:7b, gemma4:latest"
                style={{
                  flex: 1,
                  background: 'var(--color-bg)',
                  border: '1px solid color-mix(in srgb, var(--color-text) 18%, transparent)',
                  borderRadius: '8px',
                  padding: '9px 12px',
                  fontSize: '13px',
                  fontFamily: 'monospace',
                  color: 'var(--color-text)',
                  outline: 'none',
                }}
              />
              <button
                type="button"
                onClick={() => handleApply(customModel)}
                disabled={!customModel.trim()}
                style={{
                  background: 'var(--color-accent)',
                  color: '#ffffff',
                  border: 'none',
                  borderRadius: '8px',
                  padding: '0 16px',
                  fontSize: '13px',
                  fontWeight: 500,
                  cursor: customModel.trim() ? 'pointer' : 'not-allowed',
                  opacity: customModel.trim() ? 1 : 0.6,
                  transition: 'opacity 0.15s ease',
                }}
              >
                Apply Model
              </button>
            </div>
            <p style={{ margin: '6px 0 0', fontSize: '11px', color: 'color-mix(in srgb, var(--color-text) 45%, transparent)' }}>
              Works with any model installed in Ollama (<code style={{ fontFamily: 'monospace' }}>ollama list</code>) or hosted in vLLM.
            </p>
          </div>

          {/* Detected Models from Local Node */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
              <label
                style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  color: 'color-mix(in srgb, var(--color-text) 65%, transparent)',
                }}
              >
                Detected on Local Node ({detectedModels.length})
              </label>
              <button
                type="button"
                onClick={fetchDetectedModels}
                disabled={isLoadingDetected}
                className="btn btn-ghost"
                style={{ fontSize: '11px', padding: '2px 6px', display: 'flex', alignItems: 'center', gap: '4px' }}
                title="Refresh detected models"
              >
                <RefreshCw size={11} className={isLoadingDetected ? 'animate-spin' : ''} />
                <span>Refresh</span>
              </button>
            </div>

            {detectedModels.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {detectedModels.map((m) => {
                  const isActive = currentModel.toLowerCase() === m.toLowerCase();
                  return (
                    <button
                      key={m}
                      type="button"
                      onClick={() => handleApply(m)}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '10px 14px',
                        borderRadius: '8px',
                        border: isActive
                          ? '1px solid var(--color-accent)'
                          : '1px solid color-mix(in srgb, var(--color-text) 10%, transparent)',
                        background: isActive
                          ? 'color-mix(in srgb, var(--color-accent) 12%, transparent)'
                          : 'color-mix(in srgb, var(--color-bg) 50%, transparent)',
                        cursor: 'pointer',
                        textAlign: 'left',
                        transition: 'all 0.15s ease',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span
                          style={{
                            width: '8px',
                            height: '8px',
                            borderRadius: '50%',
                            background: '#10b981',
                            display: 'inline-block',
                          }}
                        />
                        <span style={{ fontSize: '13px', fontFamily: 'monospace', fontWeight: 600, color: 'var(--color-text)' }}>
                          {m}
                        </span>
                        <span
                          style={{
                            fontSize: '10px',
                            textTransform: 'uppercase',
                            background: 'rgba(16, 185, 129, 0.15)',
                            color: '#10b981',
                            padding: '2px 6px',
                            borderRadius: '4px',
                            fontWeight: 600,
                          }}
                        >
                          Installed
                        </span>
                      </div>
                      {isActive && <Check size={16} color="var(--color-accent)" />}
                    </button>
                  );
                })}
              </div>
            ) : (
              <div
                style={{
                  padding: '12px',
                  borderRadius: '8px',
                  background: 'color-mix(in srgb, var(--color-bg) 40%, transparent)',
                  border: '1px dashed color-mix(in srgb, var(--color-text) 15%, transparent)',
                  fontSize: '12px',
                  color: 'color-mix(in srgb, var(--color-text) 50%, transparent)',
                  textAlign: 'center',
                }}
              >
                No active Ollama/vLLM daemon detected on port 11434 / 8001. You can enter any model name above.
              </div>
            )}
          </div>

          {/* Popular Sovereign Presets */}
          <div>
            <label
              style={{
                display: 'block',
                fontSize: '11px',
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                color: 'color-mix(in srgb, var(--color-text) 65%, transparent)',
                marginBottom: '8px',
              }}
            >
              Popular Presets
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
              {POPULAR_PRESETS.map((p) => {
                const isActive = currentModel.toLowerCase() === p.id.toLowerCase();
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => handleApply(p.id)}
                    style={{
                      padding: '10px 12px',
                      borderRadius: '8px',
                      border: isActive
                        ? '1px solid var(--color-accent)'
                        : '1px solid color-mix(in srgb, var(--color-text) 10%, transparent)',
                      background: isActive
                        ? 'color-mix(in srgb, var(--color-accent) 12%, transparent)'
                        : 'color-mix(in srgb, var(--color-bg) 50%, transparent)',
                      cursor: 'pointer',
                      textAlign: 'left',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '3px',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: '12.5px', fontWeight: 600, color: 'var(--color-text)' }}>
                        {p.name}
                      </span>
                      {isActive && <Check size={14} color="var(--color-accent)" />}
                    </div>
                    <span style={{ fontSize: '10.5px', color: 'color-mix(in srgb, var(--color-text) 50%, transparent)' }}>
                      {p.desc}
                    </span>
                    <span style={{ fontSize: '10px', fontFamily: 'monospace', color: 'var(--color-accent)', marginTop: '2px' }}>
                      {p.id}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '14px 24px',
            borderTop: '1px solid color-mix(in srgb, var(--color-text) 10%, transparent)',
            background: 'color-mix(in srgb, var(--color-bg) 30%, transparent)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span style={{ fontSize: '11.5px', color: 'color-mix(in srgb, var(--color-text) 55%, transparent)' }}>
            Active: <strong style={{ color: 'var(--color-text)' }}>{currentModel}</strong>
          </span>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={onClose}
            style={{ fontSize: '12.5px', padding: '6px 14px' }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
