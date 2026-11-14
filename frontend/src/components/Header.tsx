import React from 'react';
import type { SystemHealth, HardwareInfo, ActiveView } from '../types';

interface HeaderProps {
  health: SystemHealth | null;
  hardware?: HardwareInfo | null;
  activeView?: ActiveView;
  onChangeView?: (view: ActiveView) => void;
  onOpenDocManager?: () => void;
  clearanceLevel?: number;
  onChangeClearance?: (level: number) => void;
  operatorName?: string;
  stationId?: string;
  nodeMode?: 'localhost' | 'lan_airgap';
}

export const Header: React.FC<HeaderProps> = ({
  health,
  clearanceLevel = 4,
  onChangeClearance,
  operatorName = 'Dana Ruiz',
  stationId = 'WORKSTATION-01',
  nodeMode = 'localhost',
}) => {
  return (
    <header
      style={{
        flex: 'none',
        display: 'flex',
        alignItems: 'center',
        gap: '20px',
        padding: '0 24px',
        height: '52px',
        boxShadow: 'inset 0 -1px 0 var(--color-divider)',
        background: 'color-mix(in srgb, var(--color-bg) 80%, transparent)',
        backdropFilter: 'blur(8px)',
        flexWrap: 'wrap',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontFamily: 'var(--font-heading)', fontWeight: 500, fontSize: '15px' }}>
        <span className="brand-mark"></span>
        <span>Sealed</span>
      </div>

      {/* Screen Sub-Heading */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span className="tag tag-neutral" style={{ fontSize: '11px' }}>
          Model: {health?.vllm_model ? health.vllm_model.split('/').pop() : 'Qwen2.5-3B'}
        </span>
        <span className="tag tag-neutral" style={{ fontSize: '11px' }}>
          Node: {stationId}
        </span>
        <span className="tag tag-accent" style={{ fontSize: '11px' }}>
          {nodeMode === 'lan_airgap' ? 'Airgap LAN Enclave' : 'Local Enclave'}
        </span>
      </div>

      {/* Right Telemetry */}
      <div style={{ marginLeft: 'auto', display: 'flex', gap: '18px', alignItems: 'center', fontSize: '12.5px', color: 'color-mix(in srgb, var(--color-text) 64%, transparent)' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="status-dot"></span>
          Offline · 0 egress
        </span>
        <span style={{ fontSize: '12px' }}>{operatorName}</span>
        {onChangeClearance && (
          <select
            value={clearanceLevel}
            onChange={(e) => onChangeClearance(Number(e.target.value))}
            style={{
              background: 'var(--color-surface)',
              color: 'var(--color-accent-300)',
              border: '1px solid var(--color-divider)',
              borderRadius: 'var(--radius-sm)',
              padding: '2px 8px',
              fontSize: '11.5px',
              cursor: 'pointer',
              outline: 'none',
            }}
            title="Switch Active Session Clearance Level"
          >
            <option value={4}>L4 Top Secret</option>
            <option value={3}>L3 Confidential</option>
            <option value={2}>L2 Internal</option>
            <option value={1}>L1 Public</option>
          </select>
        )}
      </div>
    </header>
  );
};
