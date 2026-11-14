import type {
  SystemHealth,
  DocumentItem,
  ChatSession,
  ChatMessage,
  Citation,
  LatencyBreakdown,
  HardwareInfo,
  FeedbackSubmission,
  ComplianceIntegrity,
  IndexingJob,
  AppSettings,
} from '../types';

/**
 * Automatically resolves the backend API URL across all supported deployment modes:
 * 1. Tauri desktop application (window.__TAURI_INTERNALS__ / __TAURI__, protocol 'tauri:', 'asset:', or origin 'localhost')
 * 2. Standalone Vite dev or SPA proxy servers (ports 5173, 3000, 8080)
 * 3. Local desktop browser access (localhost / 127.0.0.1)
 * 4. Production reverse-proxy / gateway deployments (relative path /api/v1)
 */
export function resolveApiBase(): string {
  if (typeof window === 'undefined') {
    return 'http://127.0.0.1:8000/api/v1';
  }

  // 1. Explicit window override if present
  if ((window as any).__SEALED_API_BASE__) {
    return (window as any).__SEALED_API_BASE__;
  }

  const { protocol, hostname, port } = window.location;

  // 2. If directly served by FastAPI on port 8000, relative /api/v1 works directly
  if (port === '8000') {
    return '/api/v1';
  }

  // 3. Detect Tauri desktop app or local dev/preview
  const isTauriApp =
    (window as any).__TAURI_INTERNALS__ !== undefined ||
    (window as any).__TAURI__ !== undefined ||
    protocol.startsWith('tauri') ||
    protocol === 'asset:' ||
    protocol === 'file:' ||
    hostname === 'tauri.localhost' ||
    // Tauri on Windows WebView2 serves custom scheme or localhost without port 8000:
    (hostname === 'localhost' && (!port || port === '80' || port === '443'));

  if (isTauriApp) {
    return 'http://127.0.0.1:8000/api/v1';
  }

  // 4. If running from any local frontend dev/proxy server (Vite 5173, SPA server 3000, etc.)
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return 'http://127.0.0.1:8000/api/v1';
  }

  // 5. Otherwise (e.g. reverse proxy / gateway)
  return '/api/v1';
}

export let API_BASE = resolveApiBase();

export function setApiBase(url: string) {
  API_BASE = url;
}

export async function getHealth(): Promise<SystemHealth> {
  const currentBase = API_BASE || resolveApiBase();
  try {
    const res = await fetch(`${currentBase}/health`);
    if (res.ok) {
      API_BASE = currentBase;
      return await res.json();
    }
  } catch (err) {
    // Resilient fallback: Try alternate between 127.0.0.1:8000 and /api/v1
    const fallbackBase = currentBase.startsWith('http') ? '/api/v1' : 'http://127.0.0.1:8000/api/v1';
    try {
      const res = await fetch(`${fallbackBase}/health`);
      if (res.ok) {
        API_BASE = fallbackBase;
        return await res.json();
      }
    } catch {}
    throw err;
  }
  throw new Error('Failed to fetch system health');
}

export async function getHardwareInfo(): Promise<HardwareInfo> {
  const res = await fetch(`${API_BASE}/inference/hardware`);
  if (!res.ok) throw new Error('Failed to fetch hardware information');
  return res.json();
}

export async function getAvailableModels(): Promise<{ active_model: string; available_models: string[] }> {
  try {
    const res = await fetch(`${API_BASE}/inference/models`);
    if (res.ok) {
      return await res.json();
    }
  } catch (err) {
    console.warn('Failed to fetch available models:', err);
  }
  return { active_model: 'Qwen/Qwen2.5-3B-Instruct', available_models: [] };
}

export async function getDocuments(): Promise<DocumentItem[]> {
  const res = await fetch(`${API_BASE}/documents`);
  if (!res.ok) throw new Error('Failed to fetch documents');
  return res.json();
}

export async function uploadDocument(
  file: File,
  clearanceLevel: number = 1,
  departments?: string[]
): Promise<DocumentItem> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('clearance_level', clearanceLevel.toString());
  if (departments && departments.length > 0) {
    formData.append('allowed_departments', JSON.stringify(departments));
  }

  const res = await fetch(`${API_BASE}/documents/upload`, {
    method: 'POST',
    body: formData,
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(errorData.detail || 'Upload failed');
  }

  return res.json();
}

export async function submitFeedback(payload: FeedbackSubmission): Promise<any> {
  const res = await fetch(`${API_BASE}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to submit feedback');
  return res.json();
}

export async function getComplianceIntegrity(): Promise<ComplianceIntegrity> {
  const res = await fetch(`${API_BASE}/compliance/verify-integrity`);
  if (!res.ok) throw new Error('Failed to verify compliance integrity');
  return res.json();
}

export async function getComplianceAuditLogs(limit: number = 20): Promise<any[]> {
  const res = await fetch(`${API_BASE}/compliance/audit-logs?limit=${limit}`);
  if (!res.ok) throw new Error('Failed to fetch audit logs');
  return res.json();
}

export async function verifyAuditChain(): Promise<ComplianceIntegrity> {
  const res = await fetch(`${API_BASE}/compliance/verify-integrity`);
  if (!res.ok) throw new Error('Failed to verify compliance chain');
  return res.json();
}

export async function deleteDocument(docId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/documents/${docId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to delete document' }));
    throw new Error(err.detail || 'Failed to delete document');
  }
}

export async function purgeAllDocuments(): Promise<{ status: string; deleted_count: number }> {
  const res = await fetch(`${API_BASE}/documents/purge-all`, {
    method: 'POST',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to purge corpus' }));
    throw new Error(err.detail || 'Failed to purge corpus');
  }
  return res.json();
}

export async function getDocumentChunks(docId: string): Promise<any[]> {
  const res = await fetch(`${API_BASE}/documents/${docId}/chunks`);
  if (!res.ok) throw new Error('Failed to fetch document chunks');
  return res.json();
}

export async function ingestUrl(url: string, clearanceLevel: number = 1): Promise<DocumentItem> {
  const res = await fetch(`${API_BASE}/documents/ingest-url`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, clearance_level: clearanceLevel }),
  });
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({ detail: 'URL ingestion failed' }));
    throw new Error(errorData.detail || 'URL ingestion failed');
  }
  return res.json();
}

export async function getSessions(): Promise<ChatSession[]> {
  const res = await fetch(`${API_BASE}/sessions`);
  if (!res.ok) throw new Error('Failed to fetch sessions');
  return res.json();
}

export async function createSession(title?: string): Promise<ChatSession> {
  const res = await fetch(`${API_BASE}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: title || 'New Conversation' }),
  });
  if (!res.ok) throw new Error('Failed to create session');
  return res.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('Failed to delete session');
}

export async function getSessionMessages(sessionId: string): Promise<ChatMessage[]> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/messages`);
  if (!res.ok) throw new Error('Failed to fetch session messages');
  return res.json();
}

export interface StreamQueryParams {
  query: string;
  sessionId?: string;
  topK?: number;
  minRerankScore?: number;
  userClearance?: number;
  userDepartments?: string[];
  model?: string;
  signal?: AbortSignal;
  onToken: (token: string) => void;
  onCitations: (citations: Citation[]) => void;
  onLatency: (latency: LatencyBreakdown) => void;
  onComplete: () => void;
  onError: (err: Error) => void;
}

export async function streamQuery({
  query,
  sessionId,
  topK = 5,
  minRerankScore = 0.20,
  userClearance,
  userDepartments,
  model,
  signal,
  onToken,
  onCitations,
  onLatency,
  onComplete,
  onError,
}: StreamQueryParams): Promise<void> {
  try {
    const response = await fetch(`${API_BASE}/query/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      signal,
      body: JSON.stringify({
        query,
        session_id: sessionId,
        top_k: topK,
        min_rerank_score: minRerankScore,
        user_clearance: userClearance,
        user_departments: userDepartments,
        model: model,
        stream: true,
      }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: 'Query failed' }));
      throw new Error(err.detail || `Server error: ${response.status}`);
    }

    if (!response.body) {
      throw new Error('Response body is null');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || !trimmed.startsWith('data:')) continue;

        const dataStr = trimmed.slice(5).trim();
        if (dataStr === '[DONE]') {
          onComplete();
          return;
        }

        try {
          const payload = JSON.parse(dataStr);
          if (payload.type === 'token') {
            onToken(payload.content);
          } else if (payload.type === 'citations') {
            onCitations(payload.data);
          } else if (payload.type === 'latency') {
            onLatency(payload.data);
          } else if (payload.type === 'error') {
            onError(new Error(payload.message || 'Stream error'));
          }
        } catch {
          onToken(dataStr);
        }
      }
    }

    onComplete();
  } catch (err: any) {
    if (err.name === 'AbortError') {
      onComplete();
      return;
    }
    onError(err);
  }
}

// -------------------------------------------------------------
// Scaled Ingestion & Scheduling API (1M-10M Chunk Engine)
// -------------------------------------------------------------

export async function getIndexingJobs(): Promise<IndexingJob[]> {
  try {
    const res = await fetch(`${API_BASE}/indexing/jobs`);
    if (!res.ok) {
      if (res.status === 404) return [];
      throw new Error(`Failed to fetch indexing jobs: ${res.statusText}`);
    }
    return res.json();
  } catch (err) {
    console.warn('Indexing jobs API unavailable:', err);
    return [];
  }
}

export async function pauseIndexingJob(jobId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/indexing/jobs/${jobId}/pause`, {
    method: 'POST',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to pause job' }));
    throw new Error(err.detail || 'Failed to pause job');
  }
  return res.json();
}

export async function resumeIndexingJob(jobId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/indexing/jobs/${jobId}/resume`, {
    method: 'POST',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to resume job' }));
    throw new Error(err.detail || 'Failed to resume job');
  }
  return res.json();
}

export async function ingestFolder(path: string): Promise<any> {
  const res = await fetch(`${API_BASE}/indexing/ingest-folder`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Folder ingestion failed' }));
    throw new Error(err.detail || 'Folder ingestion failed');
  }
  return res.json();
}

export async function ingestRepository(path: string): Promise<any> {
  const res = await fetch(`${API_BASE}/indexing/ingest-repo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Repository ingestion failed' }));
    throw new Error(err.detail || 'Repository ingestion failed');
  }
  return res.json();
}

// -------------------------------------------------------------
// Local Configuration Persistence
// -------------------------------------------------------------

export const DEFAULT_SETTINGS: AppSettings = {
  top_k: 5,
  min_rerank_score: 0.20,
  context_budget_tokens: 4096,
  dense_weight: 0.70,
  sparse_weight: 0.30,
  parent_chunk_size: 1500,
  child_chunk_size: 300,
  chunk_overlap: 50,
  hardware_allocation: 'cuda',
  embedding_batch_size: 32,
  hnsw_m: 16,
  hnsw_ef_construct: 100,
  scalar_quantization: true,
  clearance_level_filter: 1,
  // Local Machine & Air-Gapped Network Configuration Defaults
  node_mode: 'localhost',
  network_bind_host: '127.0.0.1',
  network_port: 8000,
  inference_provider: 'vllm',
  inference_base_url: 'http://localhost:8001/v1',
  active_model_name: 'Qwen/Qwen2.5-3B-Instruct',
  operator_name: 'Dana Ruiz',
  station_id: 'WORKSTATION-01',
  airgap_strict_mode: true,
  allowed_lan_subnets: '127.0.0.1/32, 192.168.0.0/16, 10.0.0.0/8',
};

const SETTINGS_KEY = 'ragapp_workstation_settings_v1';

export function getSavedSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings: AppSettings): void {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch (err) {
    console.error('Failed to save settings:', err);
  }
}

export async function runScaleBenchmark(documents: number = 2): Promise<any> {
  const res = await fetch(`${API_BASE}/benchmarks/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ documents }),
  });
  if (!res.ok) throw new Error('Benchmark execution failed');
  return res.json();
}

export async function getBenchmarkHardware(): Promise<any> {
  const res = await fetch(`${API_BASE}/benchmarks/hardware`);
  if (!res.ok) throw new Error('Failed to fetch benchmark hardware');
  return res.json();
}


