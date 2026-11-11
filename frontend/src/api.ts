export type Row = Record<string, string | number | boolean | null>
export type Analysis = {
  analysis_id: string; revision: number; filename: string; columns: string[]; text_columns: string[]
  rows: number; original_rows: number; column_count: number; modified_values: number; deleted_rows: number
  null_count: number; exact_duplicate_count: number; completeness: number
  nulls_by_column: Record<string, number>
  column_profiles: { name: string; data_type: string; empty_count: number; completeness: number; unique_count: number }[]
  preview: Row[]; preview_limit: number; preview_row_numbers: number[]
  equivalences: { column: string; variants: string[]; canonical: string; changed_values: number; revision: number }[]
}
export type ApplyResult = { analysis: Analysis; changed_values: number; deleted_rows: number }
export type Run = (operation: (signal: AbortSignal) => Promise<void>) => void
export type ModuleProps = { analysis: Analysis; run: Run; applied: (result: ApplyResult) => void }
export const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) { super(message) }
}
export async function checked(response: Response) {
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    const message = typeof payload.detail === 'string' ? payload.detail : payload.detail?.message
    throw new ApiError(message ?? 'La solicitud no es válida. Revisa los datos e inténtalo de nuevo.', response.status, payload.detail?.code)
  }
  return response
}
export async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  return (await checked(await fetch(`${API}${path}`, { signal }))).json()
}
export async function post<T>(id: string, path: string, body: unknown, signal: AbortSignal): Promise<T> {
  return (await checked(await fetch(`${API}/api/analyses/${id}/${path}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
  }))).json()
}
export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url; link.download = filename; link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export function valueText(value: unknown) {
  return value === null || value === undefined ? '— (vacío)' : typeof value === 'string' ? JSON.stringify(value) : String(value)
}
