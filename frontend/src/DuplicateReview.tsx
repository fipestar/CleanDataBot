import { useState } from 'react'
import { ApplyResult, ModuleProps, post, valueText } from './api'

type Action = 'keep_left' | 'keep_right' | 'different'
type Pair = { id: string; left_row: number; right_row: number; left: Record<string, unknown>; right: Record<string, unknown>; differences: string[]; kind: 'exact' | 'similar'; similarity: number }
type Review = { review_id: string; revision: number; pairs: Pair[] }
export default function DuplicateReview({ analysis, run, applied }: ModuleProps) {
  const [column, setColumn] = useState(analysis.text_columns[0] ?? '')
  const [threshold, setThreshold] = useState(85)
  const [review, setReview] = useState<Review | null>(null)
  const [drafts, setDrafts] = useState<Record<string, Action | ''>>({})
  const [confirmed, setConfirmed] = useState<Record<string, Action>>({})
  const [removed, setRemoved] = useState<number[]>([])
  function reset() { setReview(null); setDrafts({}); setConfirmed({}); setRemoved([]) }
  function actionLabel(pair: Pair, action: Action) {
    if (action === 'different') return 'Son registros diferentes: conservar ambos'
    return `Conservar registro ${action === 'keep_left' ? pair.left_row : pair.right_row} y eliminar registro ${action === 'keep_left' ? pair.right_row : pair.left_row}`
  }
  function search() {
    reset()
    run(async (signal) => {
      const result = await post<Review>(analysis.analysis_id, 'duplicates/search', { column: column || null, threshold }, signal)
      if (!signal.aborted) setReview(result)
    })
  }
  function confirm(pairId: string, action: Action | 'pending') {
    if (!review) return
    run(async (signal) => {
      const result = await post<{ decisions: Record<string, Action>; removed_rows: number[] }>(analysis.analysis_id, 'duplicates/decision', { review_id: review.review_id, revision: review.revision, pair_id: pairId, action }, signal)
      if (!signal.aborted) {
        setConfirmed(result.decisions); setRemoved(result.removed_rows)
        if (action === 'pending') setDrafts((current) => ({ ...current, [pairId]: '' }))
      }
    })
  }
  function apply() {
    if (!review) return
    run(async (signal) => {
      const result = await post<ApplyResult>(analysis.analysis_id, 'duplicates/apply', { review_id: review.review_id, revision: review.revision }, signal)
      if (!signal.aborted) applied(result)
    })
  }
  return <section className="match-panel duplicate-panel" aria-labelledby="duplicates-heading">
    <div className="step-label"><span>03</span> COMPARACIÓN DE REGISTROS</div><h3 id="duplicates-heading">Revisar duplicados y registros similares</h3>
    <p className="section-copy">Se incluyen duplicados exactos y la mejor coincidencia anterior de cada registro según la columna elegida. El porcentaje indica parecido textual, no probabilidad de identidad. Corregir valores no elimina filas.</p>
    <div className="match-controls">
      <label className="control-group"><span>Columna para buscar similares</span><select value={column} onChange={(event) => { setColumn(event.target.value); reset() }}><option value="">Solo duplicados exactos</option>{analysis.text_columns.map((name) => <option key={name} value={name}>{name}</option>)}</select></label>
      <label className="control-group threshold-control"><span>Umbral de parecido textual <b>{threshold}%</b></span><input type="range" min="60" max="100" value={threshold} disabled={!column} onChange={(event) => { setThreshold(Number(event.target.value)); reset() }} /></label>
      <button className="button button-primary" onClick={search}>Buscar duplicados</button>
    </div>
    <p className="section-copy">Una nueva búsqueda descarta las decisiones pendientes. Confirma cada decisión y luego aplícala al dataset de trabajo.</p>
    {review && <>
      <div className="results-heading"><div><h3>{review.pairs.length} pares para revisar</h3><p>{Object.keys(confirmed).length} decisiones confirmadas · {removed.length} filas se eliminarán al aplicar</p></div></div>
      {review.pairs.length === 0 && <p role="status">No se encontraron duplicados o similares.</p>}
      <div className="duplicate-list">{review.pairs.map((pair) => {
        const draft = drafts[pair.id] ?? confirmed[pair.id] ?? ''
        return <article className="duplicate-pair" key={pair.id} aria-label={`Comparación de registros ${pair.left_row} y ${pair.right_row}`}>
          <div className="results-heading"><h3>Registros originales {pair.left_row} y {pair.right_row}</h3><span className="review-count">{pair.kind === 'exact' ? 'Duplicados exactos' : `${pair.similarity}% parecido textual`}</span></div>
          <p className="section-copy">{pair.differences.length ? `${pair.differences.length} campos diferentes resaltados.` : 'Todos los campos son iguales.'}</p>
          <div className="table-wrap"><table aria-label={`Diferencias entre registros ${pair.left_row} y ${pair.right_row}`}><thead><tr><th>Campo</th><th>Registro {pair.left_row}</th><th>Registro {pair.right_row}</th></tr></thead><tbody>
            {analysis.columns.map((name) => <tr key={name} className={pair.differences.includes(name) ? 'field-difference' : ''}><td>{name}{pair.differences.includes(name) && <span className="difference-tag">Diferente</span>}</td><td><code className="cleanup-value">{valueText(pair.left[name])}</code></td><td><code className="cleanup-value">{valueText(pair.right[name])}</code></td></tr>)}
          </tbody></table></div>
          <div className="duplicate-decisions"><label className="control-group"><span>Decisión propuesta</span><select value={draft} onChange={(event) => setDrafts((current) => ({ ...current, [pair.id]: event.target.value as Action | '' }))}><option value="">Pendiente: elegir una decisión</option><option value="keep_left">{actionLabel(pair, 'keep_left')}</option><option value="keep_right">{actionLabel(pair, 'keep_right')}</option><option value="different">{actionLabel(pair, 'different')}</option></select></label>
            <button className="button button-secondary" disabled={!draft || draft === confirmed[pair.id]} onClick={() => { if (draft) confirm(pair.id, draft) }}>Confirmar decisión</button>
            {confirmed[pair.id] && <button className="text-button" onClick={() => confirm(pair.id, 'pending')}>Deshacer decisión</button>}
          </div>
          <p className="section-copy" role="status">{confirmed[pair.id] ? `Confirmado: ${actionLabel(pair, confirmed[pair.id])}.` : 'Sin decisión confirmada.'}{draft && draft !== confirmed[pair.id] ? ' La selección nueva aún no está confirmada.' : ''}</p>
        </article>
      })}</div>
      <div className="export-row"><p className="section-copy">Al aplicar quedarán {analysis.rows - removed.length} registros. Los pares pendientes no ordenan eliminar filas. Conservar ambos protege las dos filas dentro de esta revisión.</p><button className="button button-dark" disabled={!Object.keys(confirmed).length} onClick={apply}>Aplicar decisiones confirmadas</button></div>
    </>}
  </section>
}
