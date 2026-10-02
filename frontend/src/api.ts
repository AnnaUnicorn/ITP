export type Asset = {
  id: string; url: string; kind: string; width?: number; height?: number;
  size: number; format?: string; background_removed?: boolean;
};
export type Capabilities = {
  geometry: boolean; pose: boolean; segmentation: boolean;
  tryon: boolean; tryon_model: string;
  faceverse: boolean; faceverse_model: string;
  provider: string; pose_provider: string; model: string; pose_model: string;
};
export type ProviderSettings = {
  tencent_endpoint: string; tencent_region: string; tencent_model: string;
  tencent_secret_id_set: boolean; tencent_secret_key_set: boolean;
  pose_endpoint: string; pose_model: string; pose_api_key_set: boolean;
  seedream_endpoint: string; seedream_model: string; seedream_api_key_set: boolean;
  faceverse_endpoint: string; faceverse_model: string; faceverse_api_key_set: boolean;
};
export type FaceRefinement = {
  id: string; state: 'queued' | 'submitting' | 'ready' | 'failed';
  result_asset: string | null; error: string | null; report: Record<string, unknown> | null;
};
export type TryOnJob = {
  id: string; name: string; state: 'queued' | 'running' | 'submitting' | 'ready' | 'failed';
  model: string; active_view: string | null; results: Record<string, string>; error: string | null;
};
export type PoseMode = 'original' | 'custom' | 'a-pose' | 't-pose';
export type Job = {
  id: string; name: string; state: string; created: number; error: string | null;
  request: { front: string; pose_mode: PoseMode; topology: boolean; texture: boolean;
    rig: boolean; export_fbx: boolean };
  pose_asset: string | null;
  steps: { name: string; status: string; provider_job_id?: string; request_id?: string }[];
  artifacts: { asset_id: string; stage: string; format: string; index: number }[];
};

export async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === 'string' ? data.detail :
      Array.isArray(data.detail) ? data.detail.map((d: { msg: string }) => d.msg).join('；') :
      `请求失败（${response.status}）`;
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function post<T>(url: string, body: unknown): Promise<T> {
  return api<T>(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) });
}

export const fileUrl = (id: string) => `/api/assets/${id}/file`;
