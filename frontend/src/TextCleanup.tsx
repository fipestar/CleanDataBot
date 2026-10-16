import { FormEvent, useEffect, useRef, useState } from 'react'

type CleanupPreview = {
  preview_id: string
  total: number
  changes: { row: number; column: string; original: string; proposed: string }[]
}

export default function TextCleanup({ analysisId, filename, columns, api }: {
  analysisId: string; filename: string; columns: string[]; api: string
}) {
  const [selected, setSelected] = useState<string[]>(columns.slice(0, 1))
  const [trim, setTrim] = useState(true)
  const [collapseSpaces, setCollapseSpaces] = useState(false)
  const [letterCase, setLetterCase] = useState('unchanged')
  const [preview, setPreview] = useState<CleanupPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])

  function invalidatePreview() {
    setPreview(null)
    setError('')
    setNotice('')
  }

  async function generatePreview(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    invalidatePreview()
    const controller = new AbortController()
    request.current = controller
    try {
      const response = await fetch(`${api}/api/analyses/${analysisId}/text-cleanup/preview`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
        body: JSON.stringify({ columns: selected, trim, collapse_spaces: collapseSpaces, letter_case: letterCase }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail ?? 'No se pudo generar la previsualización.')
      if (!controller.signal.aborted) setPreview(payload)
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Error de conexión.')
    } finally {
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  async function approveAndDownload() {
    if (!preview) return
    setBusy(true)
    setError('')
    setNotice('')
    const controller = new AbortController()
    request.current = controller
    try {
      const response = await fetch(`${api}/api/analyses/${analysisId}/text-cleanup/export`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
        body: JSON.stringify({ preview_id: preview.preview_id }),
      })
      if (!response.ok) {
        const payload = await response.json()
        throw new Error(payload.detail ?? 'No se pudo generar la copia limpia.')
      }
      const blob = await response.blob()
      if (controller.signal.aborted) return
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${filename.replace(/\.[^.]+$/, '')}_limpio.csv`
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      setNotice(`Transformación aprobada: ${preview.total} valores modificados en la copia descargada. El dataset original se conserva.`)
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Error de conexión.')
    } finally {
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  return <section className="match-panel cleanup-panel" aria-labelledby="cleanup-heading">
    <div className="step-label"><span>02</span> LIMPIEZA DE TEXTO</div>
    <h3 id="cleanup-heading">Previsualiza y aprueba la transformación</h3>
    <p className="section-copy">Selecciona las columnas y las opciones. Se aplican en este orden: recortar extremos, reducir espacios repetidos y cambiar mayúsculas o minúsculas. La aprobación descarga una copia CSV con esta limpieza.</p>
    {columns.length === 0 ? <p className="section-copy">No hay columnas de texto para transformar.</p> : <>
      <form onSubmit={(event) => void generatePreview(event)} onChange={invalidatePreview}>
        <fieldset className="cleanup-options" disabled={busy}>
          <legend>Columnas de texto</legend>
          <div className="cleanup-columns">{columns.map((column) => <label key={column}>
            <input type="checkbox" checked={selected.includes(column)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, column] : current.filter((name) => name !== column))} />{column}
          </label>)}</div>
          <label><input type="checkbox" checked={trim} onChange={(event) => setTrim(event.target.checked)} />Eliminar espacios al inicio y al final</label>
          <label><input type="checkbox" checked={collapseSpaces} onChange={(event) => setCollapseSpaces(event.target.checked)} />Reducir espacios repetidos a uno</label>
          <label className="control-group"><span>Mayúsculas y minúsculas</span>
            <select value={letterCase} onChange={(event) => setLetterCase(event.target.value)}>
              <option value="unchanged">Conservar texto</option><option value="upper">Convertir a MAYÚSCULAS</option><option value="lower">Convertir a minúsculas</option>
            </select>
          </label>
          <button className="button button-secondary" type="submit" disabled={selected.length === 0 || (!trim && !collapseSpaces && letterCase === 'unchanged')}>Previsualizar cambios</button>
        </fieldset>
      </form>
      {busy && <p role="status" className="section-copy">Procesando…</p>}
      {preview && <>
        <div className="results-heading"><div><h3>Original y propuesto</h3><p role="status">{preview.total} valores cambiarán. Se muestran todos los cambios del archivo.</p></div></div>
        <p className="section-copy">Las comillas delimitan cada valor para hacer visibles los espacios de los extremos.</p>
        <div className="table-wrap"><table aria-label="Comparación de limpieza de texto">
          <thead><tr><th>Registro</th><th>Columna</th><th>Valor original</th><th>Valor propuesto</th></tr></thead>
          <tbody>{preview.changes.map((change) => <tr key={`${change.column}:${change.row}`}>
            <td>{change.row}</td><td>{change.column}</td><td><code className="cleanup-value">{JSON.stringify(change.original)}</code></td><td><code className="cleanup-value">{JSON.stringify(change.proposed)}</code></td>
          </tr>)}{preview.total === 0 && <tr><td colSpan={4}>No hay cambios con estas opciones.</td></tr>}</tbody>
        </table></div>
        {preview.total > 0 && <div className="export-row">
          <p className="section-copy">Al aprobar se aplican todos los cambios de esta previsualización a una copia del dataset.</p>
          <button className="button button-dark" disabled={busy} onClick={() => void approveAndDownload()}>Aprobar y descargar copia limpia ↓</button>
        </div>}
      </>}
    </>}
    {error && <div className="alert alert-error" role="alert">{error}</div>}
    {notice && <div className="alert alert-success" role="status">{notice}</div>}
  </section>
}
