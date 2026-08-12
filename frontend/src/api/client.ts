// Thin fetch wrapper. Base URL points at the FastAPI backend (see
// backend/app/main.py) -- set VITE_API_BASE_URL in .env for local dev,
// and to the real deployed backend URL once it's hosted (see README.md's
// hosting plan: Vercel for this frontend, Oracle Cloud for the backend).
const API_BASE = import.meta.env.VITE_API_BASE_URL as string

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) {
    throw new ApiError(res.status, `${path} -> ${res.status}`)
  }
  return res.json() as Promise<T>
}
