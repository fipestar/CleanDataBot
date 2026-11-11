import { ChangeEvent, useEffect, useState } from 'react'
import TextCleanup from './TextCleanup'
import DuplicateReview from './DuplicateReview'
import SimilarityReview from './SimilarityReview'
import { API, Analysis, ApplyResult, Row, checked, downloadBlob, get, valueText } from './api'
import { useOperation } from './useOperation'

export default function App() {
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const { busy, error, run } = useOperation()
  function analyzeFile(file: File) {
    run(async (signal) => {
      const body = new FormData(); body.append('file', file)
      const response = await checked(await fetch(`${API}/api/analyze`, { method: 'POST', body, signal }))
      const result = await response.json()
      if (!signal.aborted) setAnalysis(result)
    })
  }
  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (file) analyzeFile(file)
    event.target.value = ''
  }
  function loadExample(filename: string) {
    run(async (signal) => {
      const response = await checked(await fetch(`/${filename}`, { signal }))
      const body = new FormData()
      body.append('file', new File([await response.blob()], filename, { type: 'text/csv' }))
      const result = await (await checked(await fetch(`${API}/api/analyze`, { method: 'POST', body, signal }))).json()
      if (!signal.aborted) setAnalysis(result)
    })
  }
  return <main className="page-shell">
    <header className="topbar"><a className="brand" href="#top"><span className="brand-mark">C</span><span>CleanData<span className="brand-light">Bot</span></span></a><span className="demo-pill">Prototipo académico</span></header>
    <section className="hero" id="top"><div className="eyebrow">CALIDAD DE DATOS, CON CONTROL HUMANO</div>
      <h1>Datos más confiables,<br /><span>decisiones más claras.</span></h1>
      <p className="hero-copy">Revisa y aplica correcciones a una versión de trabajo. Combina todos los cambios y descarga un único CSV. El original permanece intacto.</p>
    </section>
    {analysis ? <Workspace key={analysis.analysis_id} initial={analysis} changeFile={() => setAnalysis(null)} /> : <section className="workspace-card">
      <h2>Comienza con un dataset</h2><div className="upload-zone"><div className="upload-icon">↑</div><strong>Selecciona tu archivo CSV o Excel</strong><span>Máximo 10 MB y 2.000 filas.</span>
        <div className="upload-actions"><label className="button button-primary file-button">Elegir archivo<input type="file" accept=".csv,.xlsx,.xls" onChange={chooseFile} disabled={busy} /></label>
          <button className="button button-secondary" disabled={busy} onClick={() => loadExample('clientes_demo.csv')}>Ejemplo de 50 registros</button>
          <button className="button button-secondary" disabled={busy} onClick={() => loadExample('grupos_demo.csv')}>Ejemplo de grupos</button>
        </div></div>
      {busy && <p role="status">Analizando archivo…</p>}{error && <div className="alert alert-error" role="alert">{error}</div>}
    </section>}
    <footer className="page-footer"><span>CleanDataBot · Demo de calidad de datos</span><span>Analizar → Revisar → Aplicar → Descargar</span></footer>
  </main>
}

type Filtered = { revision: number; rows: Row[]; row_numbers: number[]; total: number; column: string }
function Workspace({ initial, changeFile }: { initial: Analysis; changeFile: () => void }) {
  const [analysis, setAnalysis] = useState(initial)
  const [epoch, setEpoch] = useState(0)
  const [emptyColumn, setEmptyColumn] = useState<string | null>(null)
  const [filtered, setFiltered] = useState<Filtered | null>(null)
  const [filterError, setFilterError] = useState('')
  const { busy, error, notice, setNotice, run } = useOperation(async (signal) => {
    const current = await get<Analysis>(`/api/analyses/${analysis.analysis_id}`, signal)
    if (!signal.aborted) { setAnalysis(current); setEpoch((value) => value + 1) }
  })
  useEffect(() => {
    setFilterError('')
    if (emptyColumn === null) return
    const controller = new AbortController()
    void get<Filtered>(`/api/analyses/${analysis.analysis_id}/empty-rows?column=${encodeURIComponent(emptyColumn)}`, controller.signal)
      .then(async (result) => {
        if (controller.signal.aborted) return
        if (result.revision !== analysis.revision) {
          const current = await get<Analysis>(`/api/analyses/${analysis.analysis_id}`, controller.signal)
          if (!controller.signal.aborted) setAnalysis(current)
        } else setFiltered({ ...result, column: emptyColumn })
      }).catch((reason) => { if (!controller.signal.aborted) setFilterError(reason instanceof Error ? reason.message : 'Error al filtrar.') })
    return () => controller.abort()
  }, [analysis.analysis_id, analysis.revision, emptyColumn])
  const active = filtered?.revision === analysis.revision && filtered?.column === emptyColumn ? filtered : null
  const rows = emptyColumn === null ? analysis.preview : active?.rows ?? []
  const numbers = emptyColumn === null ? analysis.preview_row_numbers : active?.row_numbers ?? []
  function applied(result: ApplyResult) {
    setAnalysis(result.analysis)
    setEpoch((value) => value + 1)
    setNotice(`Cambios aplicados: ${result.changed_values} celdas modificadas y ${result.deleted_rows} filas eliminadas. Los indicadores están actualizados. Se descartaron las propuestas anteriores; genera una nueva búsqueda para continuar.`)
  }
  function download() {
    run(async (signal) => {
      const response = await checked(await fetch(`${API}/api/analyses/${analysis.analysis_id}/export`, { signal }))
      const blob = await response.blob()
      if (!signal.aborted) {
        downloadBlob(blob, `${analysis.filename.replace(/\.[^.]+$/, '')}_corregido.csv`)
        setNotice('Dataset de trabajo descargado. La descarga no aplica cambios adicionales.')
      }
    })
  }
  const moduleKey = `${analysis.revision}:${epoch}`
  return <section className="workspace-card" aria-busy={busy}>
    {busy && <div className="processing-status" role="status">Procesando… Espera a que termine la operación.</div>}
    {error && <div className="alert alert-error" role="alert">{error}</div>}
    {notice && <div className="alert alert-success" role="status">{notice}</div>}
    <fieldset className="workspace-controls" disabled={busy}>
      <legend className="sr-only">Herramientas del dataset de trabajo</legend>
      <div className="section-heading"><div><div className="step-label"><span>01</span> DATASET DE TRABAJO</div><h2>{analysis.filename}</h2></div>
        <div className="upload-actions"><button className="text-button" onClick={changeFile}>Cambiar archivo</button><button className="button button-dark" onClick={download}>Descargar dataset corregido ↓</button></div>
      </div>
      <div className="metrics-grid">
        <Metric label="Registros originales" value={analysis.original_rows} /><Metric label="Registros actuales" value={analysis.rows} />
        <Metric label="Celdas modificadas" value={analysis.modified_values} /><Metric label="Filas eliminadas" value={analysis.deleted_rows} />
        <Metric label="Valores vacíos actuales" value={analysis.null_count} /><Metric label="Duplicados exactos actuales" value={analysis.exact_duplicate_count} />
        <Metric label="Completitud actual (%)" value={analysis.completeness} /><Metric label="Columnas" value={analysis.column_count} />
      </div>
      <p className="section-copy">Las celdas modificadas cuentan diferencias frente al original en las filas que aún existen, una vez por celda. Las filas eliminadas se cuentan por separado. Completitud = celdas no vacías / celdas actuales. Los porcentajes pueden subir o bajar al eliminar filas.</p>
      <div className="table-heading"><div><h3>Perfil de columnas</h3><p>Sobre el estado actual. Vacíos: nulos y textos con solo espacios. Únicos: valores distintos no vacíos.</p></div></div>
      <div className="table-wrap profile-table"><table aria-label="Perfil de columnas"><thead><tr><th>Columna</th><th>Tipo de dato</th><th>Valores vacíos</th><th>Completitud</th><th>Valores únicos</th><th>Acciones</th></tr></thead><tbody>
        {analysis.column_profiles.map((profile) => <tr key={profile.name} className={emptyColumn === profile.name ? 'selected-column' : ''}><td>{profile.name}</td><td>{profile.data_type}</td><td>{profile.empty_count}</td><td>{profile.completeness}%</td><td>{profile.unique_count}</td><td><button className="text-button" aria-label={`Ver valores vacíos en ${profile.name}`} onClick={() => setEmptyColumn(profile.name)}>Ver valores vacíos</button></td></tr>)}
      </tbody></table></div>
      <div className="table-heading"><div><h3>{emptyColumn === null ? 'Vista previa' : `Valores vacíos en «${emptyColumn}»`}</h3><p>{emptyColumn === null ? `Primeros ${analysis.preview_limit} registros actuales` : active ? `${active.total} registros afectados` : filterError ? 'Error al filtrar' : 'Cargando…'}. La numeración identifica el registro original y permanece estable.</p></div>{emptyColumn !== null && <button className="text-button" onClick={() => setEmptyColumn(null)}>Quitar filtro</button>}</div>
      {filterError && <div className="alert alert-error" role="alert">{filterError}</div>}
      <div className="table-wrap"><table aria-label="Registros del archivo"><thead><tr><th>Registro original</th>{analysis.columns.map((name) => <th key={name}>{name}</th>)}</tr></thead><tbody>
        {rows.map((row, index) => <tr key={numbers[index]}><td>{numbers[index]}</td>{analysis.columns.map((name) => <td key={name}>{valueText(row[name])}</td>)}</tr>)}
        {rows.length === 0 && (emptyColumn === null || active) && <tr><td colSpan={analysis.column_count + 1}>No hay registros para mostrar.</td></tr>}
      </tbody></table></div>
      <TextCleanup key={`cleanup:${moduleKey}`} analysis={analysis} run={run} applied={applied} />
      <DuplicateReview key={`duplicates:${moduleKey}`} analysis={analysis} run={run} applied={applied} />
      <SimilarityReview key={`similarity:${moduleKey}`} analysis={analysis} run={run} applied={applied} />
      {analysis.equivalences.length > 0 && <details className="match-panel"><summary>Equivalencias aprobadas durante este análisis ({analysis.equivalences.length})</summary><ul>{analysis.equivalences.map((rule, index) => <li key={index}>{rule.column}: {rule.variants.map(valueText).join(', ')} → {valueText(rule.canonical)} ({rule.changed_values} celdas en esa operación)</li>)}</ul></details>}
    </fieldset>
  </section>
}
function Metric({ label, value }: { label: string; value: number }) {
  return <article className="metric-card"><div className="metric-top">{label}</div><strong>{value.toLocaleString('es-CO', { maximumFractionDigits: 2 })}</strong></article>
}
