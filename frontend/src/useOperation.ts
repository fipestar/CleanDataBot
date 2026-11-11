import { useEffect, useRef, useState } from 'react'
import { ApiError, Run } from './api'

export function useOperation(onConflict?: (signal: AbortSignal) => Promise<void>) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const active = useRef<AbortController | null>(null)
  useEffect(() => () => active.current?.abort(), [])
  const run: Run = (operation) => {
    // Synchronous guard also blocks a second click before React re-renders.
    if (active.current) return
    const controller = new AbortController()
    active.current = controller
    setBusy(true); setError(''); setNotice('')
    void (async () => {
      try { await operation(controller.signal) }
      catch (reason) {
        if (controller.signal.aborted) return
        setError(reason instanceof Error ? reason.message : 'Error de conexión.')
        if (reason instanceof ApiError && reason.code === 'stale_proposal' && onConflict) {
          try { await onConflict(controller.signal) }
          catch { setError('No se pudo actualizar el estado. Vuelve a intentar actualizar el dataset.') }
        }
      } finally {
        if (!controller.signal.aborted) { active.current = null; setBusy(false) }
      }
    })()
  }
  return { busy, error, notice, setNotice, run }
}
