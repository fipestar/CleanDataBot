import { useState } from 'react'
import { ApplyResult, ModuleProps, post, valueText } from './api'

type Preview = { preview_id: string; revision: number; total: number; changes: { id: string; row: number; column: string; original: string; proposed: string }[] }
export default function TextCleanup({ analysis, run, applied }: ModuleProps) {
  const [selected, setSelected] = useState(analysis.text_columns.slice(0, 1))
  const [trim, setTrim] = useState(true)
  const [collapse, setCollapse] = useState(false)
  const [letterCase, setLetterCase] = useState('unchanged')
  const [preview, setPreview] = useState<Preview | null>(null)
  const [approved, setApproved] = useState<string[]>([])
  function invalidate() { setPreview(null); setApproved([]) }
  function generate() {
    invalidate()
    run(async (signal) => {
      const result = await post<Preview>(analysis.analysis_id, 'text-cleanup/preview', { columns: selected, trim, collapse_spaces: collapse, letter_case: letterCase }, signal)
      if (!signal.aborted) setPreview(result)
    })
  }
  function apply() {
    if (!preview) return
    run(async (signal) => {
      const result = await post<ApplyResult>(analysis.analysis_id, 'text-cleanup/apply', { preview_id: preview.preview_id, revision: preview.revision, approved_change_ids: approved }, signal)
      if (!signal.aborted) applied(result)
    })
  }
  return <section className="match-panel cleanup-panel" aria-labelledby="cleanup-heading">
    <div className="step-label"><span>02</span> LIMPIEZA DE TEXTO</div><h3 id="cleanup-heading">Previsualiza y aprueba la transformación</h3>
    <p className="section-copy">Orden: recortar extremos, reducir espacios repetidos y cambiar mayúsculas o minúsculas. Se modifica la versión de trabajo; después puedes continuar con otros módulos.</p>
    {analysis.text_columns.length === 0 ? <p>No hay columnas de texto.</p> : <>
      <form onSubmit={(event) => { event.preventDefault(); generate() }} onChange={invalidate}>
        <fieldset className="cleanup-options"><legend>Columnas de texto</legend><div className="cleanup-columns">{analysis.text_columns.map((name) => <label key={name}><input type="checkbox" checked={selected.includes(name)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, name] : current.filter((value) => value !== name))} />{name}</label>)}</div>
          <label><input type="checkbox" checked={trim} onChange={(event) => setTrim(event.target.checked)} />Eliminar espacios al inicio y al final</label>
          <label><input type="checkbox" checked={collapse} onChange={(event) => setCollapse(event.target.checked)} />Reducir espacios repetidos a uno</label>
          <label className="control-group"><span>Mayúsculas y minúsculas</span><select value={letterCase} onChange={(event) => setLetterCase(event.target.value)}><option value="unchanged">Conservar texto</option><option value="upper">Convertir a MAYÚSCULAS</option><option value="lower">Convertir a minúsculas</option></select></label>
          <button className="button button-secondary" type="submit" disabled={!selected.length || (!trim && !collapse && letterCase === 'unchanged')}>Previsualizar cambios</button>
        </fieldset>
      </form>
      {preview && <>
        <div className="results-heading"><div><h3>Original y propuesto</h3><p>{preview.total} cambios posibles · {approved.length} aprobados</p></div><button className="text-button" onClick={() => setApproved(approved.length === preview.changes.length ? [] : preview.changes.map((change) => change.id))}>{approved.length === preview.changes.length ? 'Desmarcar todos' : 'Aprobar todos los cambios de esta vista'}</button></div>
        <div className="table-wrap"><table aria-label="Comparación de limpieza de texto"><thead><tr><th>Aprobar</th><th>Registro original</th><th>Columna</th><th>Valor original</th><th>Valor propuesto</th></tr></thead><tbody>
          {preview.changes.map((change) => <tr key={change.id}><td><input type="checkbox" aria-label={`Aprobar limpieza de ${change.column} en registro ${change.row}`} checked={approved.includes(change.id)} onChange={(event) => setApproved((current) => event.target.checked ? [...current, change.id] : current.filter((id) => id !== change.id))} /></td><td>{change.row}</td><td>{change.column}</td><td><code className="cleanup-value">{valueText(change.original)}</code></td><td><code className="cleanup-value">{valueText(change.proposed)}</code></td></tr>)}
          {preview.total === 0 && <tr><td colSpan={5}>No hay cambios con estas opciones.</td></tr>}
        </tbody></table></div>
        <div className="export-row"><p className="section-copy">Solo se aplicarán los cambios aprobados. Las comillas hacen visibles los espacios.</p><button className="button button-dark" disabled={!approved.length} onClick={apply}>Aplicar cambios aprobados</button></div>
      </>}
    </>}
  </section>
}
