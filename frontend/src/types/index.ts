export interface Citation {
  citation_id: number;
  chunk_id: string;
  parent_id: string;
  doc_id: string;
  filename: string;
  page_number: number;
  exact_quote: string;
  relevance_score: number;
  parent_content?: string;
}

export interface LatencyBreakdown {
  total_ms?: number;
  embed_ms?: number;
  retrieval_ms?: number;
  rerank_ms?: number;
  ttft_ms?: number;
  generation_ms?: number;
  [key: string]: number | undefined;
}

export interface ArtifactItem {
  id: string;
  title: string;
  type: 'code' | 'html' | 'svg' | 'markdown' | 'mermaid';
  language?: string;
  content: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: Citation[];
  latency_ms?: LatencyBreakdown;
  isStreaming?: boolean;
  timestamp: string;
  thinking_content?: string;
  artifacts?: ArtifactItem[];
}

export interface ChatSession {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface DocumentItem {
  doc_id: string;
  filename: string;
  file_hash: string;
  file_size_bytes: number;
  mime_type: string;
  total_pages: number;
  total_parent_chunks: number;
  total_child_chunks: number;
  clearance_level?: number;
  allowed_departments?: string[];
  created_at: string;
}

export interface FeedbackSubmission {
  message_id?: string;
  session_id?: string;
  rating: number; // 1 or -1
  feedback_category?: string;
  expert_correction?: string;
  citations_approved?: any[];
  is_expert_verified?: boolean;
}

export interface ComplianceIntegrity {
  is_valid: boolean;
  total_records: number;
  tampered_records: any[];
  verified_at: string;
  message: string;
}

export interface DeviceInfo {
  index: number;
  vendor: string;
  name: string;
  architecture: string;
  compute_capability?: string;
  vram_total_mb: number;
  vram_free_mb: number;
  driver_version?: string;
  pci_bus_id?: string;
  is_compatible: boolean;
}

export interface HardwareInfo {
  os_type: string;
  selected_vendor: string;
  recommended_provider: 'cuda' | 'rocm' | 'cpu';
  is_vllm_supported: boolean;
  status_summary: string;
  selected_device?: DeviceInfo;
  docker_access: {
    docker_available: boolean;
    nvidia_container_accessible: boolean;
    rocm_container_accessible: boolean;
    rocm_kfd_accessible: boolean;
    rocm_dri_accessible: boolean;
    details?: string[];
  };
}

export interface SystemHealth {
  status: string;
  app_version: string;
  gpu_available: boolean;
  gpu_name?: string;
  gpu_memory_used_mb?: number;
  gpu_memory_total_mb?: number;
  vector_db_ready: boolean;
  vllm_ready?: boolean;
  vllm_model?: string;
  total_indexed_documents: number;
  total_indexed_chunks: number;
}

export type JobStatus = 'pending' | 'running' | 'paused' | 'completed' | 'failed';

export interface IndexingJob {
  job_id: string;
  job_type: 'folder' | 'repository' | 'file' | string;
  source_path: string;
  total_files: number;
  processed_files: number;
  total_chunks: number;
  status: JobStatus;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SystemMetrics {
  cpu_usage_percent?: number;
  ram_used_mb: number;
  ram_total_mb: number;
  ram_percent: number;
  vram_used_mb: number;
  vram_total_mb: number;
  vram_percent: number;
  gpu_temperature_c?: number;
  disk_used_gb: number;
  disk_total_gb: number;
  disk_percent: number;
  total_indexed_chunks: number;
  total_indexed_documents: number;
  vector_storage_mb?: number;
  indexing_throughput_chunks_sec?: number;
  hnsw_memory_mb?: number;
}

export interface AppSettings {
  top_k: number;
  min_rerank_score: number;
  context_budget_tokens: number;
  dense_weight: number;
  sparse_weight: number;
  parent_chunk_size: number;
  child_chunk_size: number;
  chunk_overlap: number;
  hardware_allocation: 'cuda' | 'rocm' | 'cpu';
  embedding_batch_size: number;
  hnsw_m: number;
  hnsw_ef_construct: number;
  scalar_quantization: boolean;
  clearance_level_filter?: number;
  // Local Machine & Air-Gapped Network Configuration
  node_mode: 'localhost' | 'lan_airgap';
  network_bind_host: string;
  network_port: number;
  inference_provider: 'vllm' | 'ollama' | 'custom';
  inference_base_url: string;
  active_model_name: string;
  operator_name: string;
  station_id: string;
  airgap_strict_mode: boolean;
  allowed_lan_subnets: string;
}

export type ActiveView = 'chat' | 'evals' | 'knowledge' | 'admin' | 'indexing' | 'dashboard' | 'library' | 'settings';


