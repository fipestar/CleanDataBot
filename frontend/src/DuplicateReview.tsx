import { useEffect, useRef, useState } from 'react'

type Action = 'keep_left' | 'keep_right' | 'different'
type Pair = {
  id: string; left_row: number; right_row: number
  left: Record<string, unknown>; right: Record<string, unknown>
  differences: string[]; kind: 'exact' | 'similar'; similarity: number
}
type Review = { review_id: string; pairs: Pair[] }

function valueText(value: unknown) {
  return value === null || value === undefined ? '— (vacío)' : typeof value === 'string' ? JSON.stringify(value) : String(value)
}

export default function DuplicateReview({ analysisId, filename, columns, textColumns, rowCount, api }: {
  analysisId: string; filename: string; columns: string[]; textColumns: string[]; rowCount: number; api: string
}) {
  const [column, setColumn] = useState(textColumns[0] ?? '')
  const [threshold, setThreshold] = useState(85)
  const [review, setReview] = useState<Review | null>(null)
  const [drafts, setDrafts] = useState<Record<string, Action | ''>>({})
  const [confirmed, setConfirmed] = useState<Record<string, Action>>({})
  const [removed, setRemoved] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])

  function resetReview() {
    setReview(null); setDrafts({}); setConfirmed({}); setRemoved([]); setError(''); setNotice('')
  }

  function actionLabel(pair: Pair, action: Action) {
    if (action === 'different') return 'Son registros diferentes: conservar ambos'
    const keep = action === 'keep_left' ? pair.left_row : pair.right_row
    const discard = action === 'keep_left' ? pair.right_row : pair.left_row
    return `Conservar registro ${keep} y eliminar registro ${discard} de la copia`
  }

  async function run(operation: (signal: AbortSignal) => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    const controller = new AbortController()
    request.current = controller
    try { await operation(controller.signal) }
    catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Error de conexión.')
    } finally { if (!controller.signal.aborted) setBusy(false) }
  }

  async function post(path: string, body: unknown, signal: AbortSignal) {
    const response = await fetch(`${api}/api/analyses/${analysisId}/duplicates/${path}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
    })
    if (!response.ok) {
      const payload = await response.json()
      throw new Error(payload.detail ?? 'No se pudo completar la operación.')
    }
    return response
  }

  function search() {
    resetReview()
    void run(async (signal) => {
      const response = await post('search', { column: column || null, threshold }, signal)
      const payload = await response.json()
      if (!signal.aborted) setReview(payload)
    })
  }

  function confirm(pairId: string, action: Action | 'pending') {
    if (!review) return
    void run(async (signal) => {
      const response = await post('decision', { review_id: review.review_id, pair_id: pairId, action }, signal)
      const payload = await response.json()
      if (!signal.aborted) {
        setConfirmed(payload.decisions); setRemoved(payload.removed_rows)
        if (action === 'pending') setDrafts((current) => ({ ...current, [pairId]: '' }))
        setNotice(action === 'pending' ? 'Decisión deshecha.' : 'Decisión confirmada para la exportación.')
      }
    })
  }

  function download() {
    if (!review) return
    void run(async (signal) => {
      const response = await post('export', { review_id: review.review_id }, signal)
      const blob = await response.blob()
      if (signal.aborted) return
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url; link.download = `${filename.replace(/\.[^.]+$/, '')}_revisado.csv`; link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      setNotice(`Copia descargada con ${rowCount - removed.length} registros. Se omitieron ${removed.length} registros según las decisiones confirmadas.`)
    })
  }

  return <section className="match-panel duplicate-panel" aria-labelledby="duplicates-heading">
    <div className="step-label"><span>03</span> COMPARACIÓN DE REGISTROS</div>
    <h3 id="duplicates-heading">Revisar duplicados y registros similares</h3>
    <p className="section-copy">Se incluyen duplicados exactos y la mejor coincidencia anterior de cada registro según la columna elegida. Compara todos los campos y confirma qué conservar. Los pares pendientes conservan ambos registros salvo una eliminación confirmada en otro par.</p>
    <div className="match-controls">
      <label className="control-group"><span>Columna para buscar similares</span>
        <select value={column} disabled={busy} onChange={(event) => { setColumn(event.target.value); resetReview() }}>
          <option value="">Solo duplicados exactos</option>
          {textColumns.map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
      </label>
      <label className="control-group threshold-control"><span>Umbral de similitud <b>{threshold}%</b></span>
        <input type="range" min="60" max="100" value={threshold} disabled={busy || !column} onChange={(event) => { setThreshold(Number(event.target.value)); resetReview() }} />
      </label>
      <button className="button button-primary" disabled={busy} onClick={search}>Buscar duplicados</button>
    </div>
    <p className="section-copy">Cambiar la búsqueda inicia una nueva revisión. La exportación de esta sección contiene las decisiones sobre registros completos.</p>
    {busy && <p role="status" className="section-copy">Procesando…</p>}
    {review && <>
      <div className="results-heading"><div><h3>{review.pairs.length} pares para revisar</h3><p>{Object.keys(confirmed).length} decisiones confirmadas · {removed.length} registros se eliminarán de la copia</p></div></div>
      {review.pairs.length === 0 && <p role="status" className="section-copy">No se encontraron duplicados o similares con estos criterios.</p>}
      <div className="duplicate-list">{review.pairs.map((pair) => {
        const draft = drafts[pair.id] ?? confirmed[pair.id] ?? ''
        return <article className="duplicate-pair" key={pair.id} aria-label={`Comparación de registros ${pair.left_row} y ${pair.right_row}`}>
          <div className="results-heading"><h3>Registros {pair.left_row} y {pair.right_row}</h3><span className="review-count">{pair.kind === 'exact' ? 'Duplicados exactos' : `${pair.similarity}% de similitud`}</span></div>
          <p className="section-copy">{pair.differences.length === 0 ? 'Todos los campos son iguales.' : `${pair.differences.length} campos diferentes resaltados.`}</p>
          <div className="table-wrap"><table aria-label={`Diferencias entre registros ${pair.left_row} y ${pair.right_row}`}>
            <thead><tr><th>Campo</th><th>Registro {pair.left_row}</th><th>Registro {pair.right_row}</th></tr></thead>
            <tbody>{columns.map((name) => <tr key={name} className={pair.differences.includes(name) ? 'field-difference' : ''}>
              <td>{name}{pair.differences.includes(name) && <span className="difference-tag">Diferente</span>}</td>
              <td><code className="cleanup-value">{valueText(pair.left[name])}</code></td><td><code className="cleanup-value">{valueText(pair.right[name])}</code></td>
            </tr>)}</tbody>
          </table></div>
          <div className="duplicate-decisions">
            <label className="control-group"><span>Decisión propuesta</span>
              <select value={draft} disabled={busy} onChange={(event) => setDrafts((current) => ({ ...current, [pair.id]: event.target.value as Action | '' }))}>
                <option value="">Pendiente: elegir una decisión</option>
                <option value="keep_left">{actionLabel(pair, 'keep_left')}</option><option value="keep_right">{actionLabel(pair, 'keep_right')}</option><option value="different">{actionLabel(pair, 'different')}</option>
              </select>
            </label>
            <button className="button button-secondary" disabled={busy || !draft || draft === confirmed[pair.id]} onClick={() => { if (draft) confirm(pair.id, draft) }}>Confirmar decisión</button>
            {confirmed[pair.id] && <button className="text-button" disabled={busy} onClick={() => confirm(pair.id, 'pending')}>Deshacer decisión</button>}
          </div>
          <p className="section-copy" role="status">{confirmed[pair.id] ? `Confirmado: ${actionLabel(pair, confirmed[pair.id])}.` : 'Sin decisión confirmada.'}{draft && draft !== confirmed[pair.id] ? ' La selección propuesta aún no está confirmada.' : ''}</p>
        </article>
      })}</div>
      <div className="export-row"><p className="section-copy">La copia tendrá {rowCount - removed.length} registros. El original se conserva. Las selecciones sin confirmar no cambian la exportación.</p>
        <button className="button button-dark" disabled={busy} onClick={download}>Exportar decisiones confirmadas ↓</button>
      </div>
    </>}
    {error && <div className="alert alert-error" role="alert">{error}</div>}
    {notice && <div className="alert alert-success" role="status">{notice}</div>}
  </section>
}
