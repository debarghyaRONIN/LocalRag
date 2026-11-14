import React from 'react';
import { Plus, Trash2 } from 'lucide-react';
import type { ChatSession, ActiveView } from '../types';

interface SidebarProps {
  activeView: ActiveView;
  onChangeView: (view: ActiveView) => void;
  sessions: ChatSession[];
  activeSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onNewSession: () => void;
  onDeleteSession: (sessionId: string) => void;
  documentCount?: number;
  activeJobCount?: number;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeView,
  onChangeView,
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  onDeleteSession,
  documentCount = 0,
  activeJobCount = 0,
}) => {
  const navItems = [
    { id: 'chat' as ActiveView, label: 'Chat', meta: '' },
    { id: 'evals' as ActiveView, label: 'Evals', meta: '42 cases' },
    { id: 'knowledge' as ActiveView, label: 'Knowledge', meta: `${documentCount} sets` },
    { id: 'admin' as ActiveView, label: 'Admin', meta: '' },
    { id: 'indexing' as ActiveView, label: 'Indexing', meta: activeJobCount > 0 ? `${activeJobCount} active` : '' },
    { id: 'settings' as ActiveView, label: 'Settings', meta: '' },
  ];

  const filteredSessions = sessions;

  return (
    <aside
      style={{
        width: '230px',
        flex: 'none',
        display: 'flex',
        flexDirection: 'column',
        gap: '4px',
        padding: '18px 12px',
        background: 'color-mix(in srgb, var(--color-surface) 55%, transparent)',
        boxShadow: 'inset -1px 0 0 var(--color-divider)',
        height: '100vh',
        boxSizing: 'border-box',
        userSelect: 'none',
      }}
    >
      {/* Brand Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          padding: '4px 10px 18px',
          fontFamily: 'var(--font-heading)',
          fontWeight: 500,
          fontSize: '16px',
          color: 'var(--color-text)',
        }}
      >
        <span className="brand-mark"></span>
        Sealed
      </div>

      {/* Primary Navigation */}
      <nav style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
        {navItems.map((n) => {
          const isActive =
            activeView === n.id ||
            (n.id === 'knowledge' && activeView === 'library') ||
            (n.id === 'admin' && (activeView === 'dashboard' || activeView === 'settings'));

          return (
            <button
              key={n.id}
              type="button"
              onClick={() => onChangeView(n.id)}
              style={{
                all: 'unset',
                cursor: 'pointer',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '8px 10px',
                borderRadius: 'var(--radius-md)',
                background: isActive
                  ? 'color-mix(in srgb, var(--color-accent) 14%, transparent)'
                  : 'transparent',
                color: isActive
                  ? 'var(--color-accent-200)'
                  : 'color-mix(in srgb, var(--color-text) 78%, transparent)',
                fontSize: '13.5px',
                transition: 'background 0.15s ease, color 0.15s ease',
              }}
              onMouseEnter={(e) => {
                if (!isActive) (e.currentTarget as HTMLElement).style.background = 'color-mix(in srgb, var(--color-text) 6%, transparent)';
              }}
              onMouseLeave={(e) => {
                if (!isActive) (e.currentTarget as HTMLElement).style.background = 'transparent';
              }}
            >
              <span>{n.label}</span>
              {n.meta && (
                <span style={{ fontSize: '11px', color: 'color-mix(in srgb, var(--color-text) 50%, transparent)' }}>
                  {n.meta}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* When in Chat, show conversation thread manager */}
      {activeView === 'chat' && (
        <div style={{ marginTop: '16px', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 10px 8px' }}>
            <span style={{ fontSize: '11px', letterSpacing: '0.06em', textTransform: 'uppercase', color: 'color-mix(in srgb, var(--color-text) 50%, transparent)' }}>
              Threads
            </span>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={onNewSession}
              style={{ padding: '2px 6px', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}
              title="Start New Thread"
            >
              <Plus size={12} /> New
            </button>
          </div>

          <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '2px', paddingRight: '4px' }}>
            {filteredSessions.map((s) => {
              const isSelected = activeSessionId === s.session_id;
              return (
                <div
                  key={s.session_id}
                  onClick={() => onSelectSession(s.session_id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '6px 10px',
                    borderRadius: 'var(--radius-sm)',
                    cursor: 'pointer',
                    fontSize: '12.5px',
                    background: isSelected ? 'var(--color-surface)' : 'transparent',
                    color: isSelected ? 'var(--color-text)' : 'color-mix(in srgb, var(--color-text) 70%, transparent)',
                    border: isSelected ? '1px solid var(--color-divider)' : '1px solid transparent',
                  }}
                >
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '150px' }}>
                    {s.title || 'New Thread'}
                  </span>
                  {isSelected && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteSession(s.session_id);
                      }}
                      style={{ all: 'unset', color: 'color-mix(in srgb, var(--color-text) 45%, transparent)', padding: '2px' }}
                      title="Delete thread"
                    >
                      <Trash2 size={11} />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Footer System Status */}
      <div
        style={{
          marginTop: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          padding: '14px 10px 4px',
          fontSize: '12px',
          color: 'color-mix(in srgb, var(--color-text) 64%, transparent)',
          boxShadow: 'inset 0 1px 0 var(--color-divider)',
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="status-dot"></span>
          Offline · 0 egress
        </span>
        <span style={{ fontSize: '11.5px', color: 'color-mix(in srgb, var(--color-text) 50%, transparent)' }}>
          Dana Ruiz · admin (L4)
        </span>
      </div>
    </aside>
  );
};
