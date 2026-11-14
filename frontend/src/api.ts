export type Project = { id: string; name: string; role: 'admin' | 'viewer'; created_at: string }
export type CurrentUser = { platform_admin: boolean }
export type PlatformAdmin = { issuer: string; subject: string; granted_by: string; created_at: string }
export type Capability = { kind: string; state: string; resource_name: string | null; endpoint: Record<string, unknown> | null; error: string | null }
export type Operation = { id: string; project_id: string; capability_kind: string; action: string; state: string; attempts: number; error: string | null; created_at: string }
export type Credential = { id: string; label: string; access: 'runtime' | 'migration'; username: string; state: string; delivery_pending: boolean; created_at: string }
export type IssuedCredential = { credential: Credential; secret: string | null; operation: Operation }
export type Member = { issuer: string; subject: string; role: 'admin' | 'viewer' }
export type StoredObject = { key: string; size: number }

const baseUrl = import.meta.env.VITE_API_URL ?? '/api'

export async function api<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers },
    cache: 'no-store',
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${response.status}`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
