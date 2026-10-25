export type Crop = { x: number; y: number; width: number; height: number };
export type Video = {
  id: string; name: string; width: number; height: number; duration: number; fps: number;
  size: number; url: string; poster: string; camera: Crop;
  detection: { mode: 'detected' | 'suggested'; message: string };
};
export type Job = {
  id: string; status: 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled';
  progress: number; error?: string; url?: string; filename?: string;
};
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'İşlem tamamlanamadı. Lütfen tekrar dene.');
  return data as T;
}
export const clock = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds || 0));
  return (s >= 3600 ? `${Math.floor(s / 3600)}:` : '') + `${Math.floor(s / 60) % 60}`.padStart(2, '0') + ':' + `${s % 60}`.padStart(2, '0');
};
