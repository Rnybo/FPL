// Thin fetch wrapper. Base URL points at the FastAPI backend (see
// backend/app/main.py) -- set VITE_API_BASE_URL in .env for local dev,
// and to the real deployed backend URL once it's hosted (see README.md's
// hosting plan: Vercel for this frontend, Oracle Cloud for the backend).
const API_BASE = import.meta.env.VITE_API_BASE_URL as string

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) {
    throw new ApiError(res.status, `${path} -> ${res.status}`)
  }
  return res.json() as Promise<T>
}

// POST/PUT/DELETE -- only used by saved_squads (Squad Builder's "save as
// draft"); everything else in this app is read-only. DELETE responses have
// no body (204), so that one skips the json() parse.
async function apiWrite<T>(method: 'POST' | 'PUT' | 'DELETE', path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    throw new ApiError(res.status, `${method} ${path} -> ${res.status}`)
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}

export const apiPost = <T>(path: string, body: unknown) => apiWrite<T>('POST', path, body)
export const apiPut = <T>(path: string, body: unknown) => apiWrite<T>('PUT', path, body)
export const apiDelete = <T = void>(path: string) => apiWrite<T>('DELETE', path)
