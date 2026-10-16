import { ChangeEvent, useEffect, useMemo, useState } from 'react'
import TextCleanup from './TextCleanup'
import DuplicateReview from './DuplicateReview'

type PreviewRow = Record<string, string | number | boolean | null>
type Analysis = {
  analysis_id: string
  filename: string
  columns: string[]
  text_columns: string[]
  rows: number
  column_count: number
  null_count: number
  exact_duplicate_count: number
  nulls_by_column: Record<string, number>
  column_profiles: { name: string; data_type: string; empty_count: number; completeness: number; unique_count: number }[]
  preview: PreviewRow[]
  preview_limit: number
}
type Match = {
  id: string
  target_row: number
  reference_row: number
  current_value: string
  suggested_value: string
  similarity: number
}
type Decision = 'approved' | 'rejected' | 'pending'

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

function display(value: unknown) {
  if (value === null || value === undefined || value === '') return '—'
  return String(value)
}

export default function App() {
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [column, setColumn] = useState('')
  const [threshold, setThreshold] = useState(85)
  const [matches, setMatches] = useState<Match[]>([])
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [emptyColumn, setEmptyColumn] = useState<string | null>(null)
  const [filteredRows, setFilteredRows] = useState<{
    analysisId: string; column: string; rows: PreviewRow[]; row_numbers: number[]; total: number
  } | null>(null)
  const [filterError, setFilterError] = useState('')

  useEffect(() => {
    setFilterError('')
    if (!analysis || emptyColumn === null) return
    const controller = new AbortController()
    const analysisId = analysis.analysis_id
    const selectedColumn = emptyColumn
    async function loadEmptyRows() {
      try {
        const response = await fetch(`${API}/api/analyses/${analysisId}/empty-rows?column=${encodeURIComponent(selectedColumn)}`, { signal: controller.signal })
        const payload = await response.json()
        if (!response.ok) throw new Error(payload.detail ?? 'No se pudieron cargar los registros con valores vacíos.')
        if (!controller.signal.aborted) setFilteredRows({ ...payload, analysisId, column: selectedColumn })
      } catch (reason) {
        if (!controller.signal.aborted) setFilterError(reason instanceof Error ? reason.message : 'Error al filtrar los registros.')
      }
    }
    void loadEmptyRows()
    return () => controller.abort()
  }, [analysis, emptyColumn])

  const activeRows = filteredRows?.analysisId === analysis?.analysis_id && filteredRows?.column === emptyColumn ? filteredRows : null
  const visibleRows = emptyColumn === null ? analysis?.preview ?? [] : activeRows?.rows ?? []

  const approvedIds = useMemo(
    () => matches.filter((match) => decisions[match.id] === 'approved').map((match) => match.id),
    [matches, decisions],
  )

  async function analyzeFile(selectedFile: File) {
    setAnalysis(null)
    setEmptyColumn(null)
    setFilteredRows(null)
    setMatches([])
    setDecisions({})
    setError('')
    setNotice('')
    setLoading(true)
    try {
      const body = new FormData()
      body.append('file', selectedFile)
      const response = await fetch(`${API}/api/analyze`, { method: 'POST', body })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail ?? 'No se pudo analizar el archivo.')
      const result = payload as Analysis
      setAnalysis(result)
      setColumn(result.text_columns[0] ?? '')
      if (result.text_columns.length === 0) {
        setNotice('El archivo se analizó, pero no se encontraron columnas de texto para buscar similitudes.')
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Error de conexión con el servicio de análisis.')
    } finally {
      setLoading(false)
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const selectedFile = event.target.files?.[0]
    if (selectedFile) void analyzeFile(selectedFile)
    event.target.value = ''
  }

  async function loadExample() {
    setError('')
    setNotice('')
    try {
      const response = await fetch('/clientes_demo.csv')
      if (!response.ok) throw new Error('No se encontró el archivo de ejemplo.')
      const blob = await response.blob()
      await analyzeFile(new File([blob], 'clientes_demo.csv', { type: 'text/csv' }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'No se pudo cargar el ejemplo.')
    }
  }

  async function searchMatches() {
    if (!analysis || !column) return
    setLoading(true)
    setError('')
    setNotice('')
    setMatches([])
    setDecisions({})
    try {
      const response = await fetch(`${API}/api/analyses/${analysis.analysis_id}/matches`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ column, threshold }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail ?? 'No se pudieron buscar similitudes.')
      const found = payload.matches as Match[]
      setMatches(found)
      setDecisions(Object.fromEntries(found.map((match) => [match.id, 'pending'])))
      if (found.length === 0) setNotice('No se encontraron sugerencias con ese umbral. Puedes bajarlo y volver a intentar.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Error buscando similitudes.')
    } finally {
      setLoading(false)
    }
  }

  async function downloadCorrectedCopy() {
    if (!analysis) return
    setLoading(true)
    setError('')
    try {
      const response = await fetch(`${API}/api/analyses/${analysis.analysis_id}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved_match_ids: approvedIds }),
      })
      if (!response.ok) {
        const payload = await response.json()
        throw new Error(payload.detail ?? 'No se pudo generar la copia corregida.')
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${analysis.filename.replace(/\.[^.]+$/, '')}_corregido.csv`
      link.click()
      URL.revokeObjectURL(url)
      setNotice(`Copia descargada. Se aplicaron ${approvedIds.length} corrección(es); el archivo original se conservó.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'No se pudo descargar la copia corregida.')
    } finally {
      setLoading(false)
    }
  }

  function setDecision(matchId: string, decision: Decision) {
    setDecisions((current) => ({ ...current, [matchId]: decision }))
  }

  return (
    <main className="page-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="CleanDataBot inicio">
          <span className="brand-mark">C</span>
          <span>CleanData<span className="brand-light">Bot</span></span>
        </a>
        <span className="demo-pill"><span className="live-dot" /> Prototipo académico</span>
      </header>

      <section className="hero" id="top">
        <div className="eyebrow"><span className="eyebrow-line" /> CALIDAD DE DATOS, CON CONTROL HUMANO</div>
        <h1>Datos más confiables,<br /><span>decisiones más claras.</span></h1>
        <p className="hero-copy">Analiza un archivo, revisa posibles inconsistencias y decide qué sugerencias aplicar. Tu archivo original permanece intacto.</p>
      </section>

      <section className="workspace-card">
        <div className="section-heading">
          <div>
            <div className="step-label"><span>01</span> CARGA Y ANÁLISIS</div>
            <h2>Comienza con un dataset</h2>
          </div>
          {analysis && <span className="file-chip"><span className="file-icon">▤</span>{analysis.filename}</span>}
        </div>

        {!analysis ? (
          <div className="upload-zone">
            <div className="upload-icon">↑</div>
            <strong>Selecciona tu archivo CSV o Excel</strong>
            <span>Para la demostración: máximo 10 MB y 2.000 filas.</span>
            <div className="upload-actions">
              <label className="button button-primary file-button">
                {loading ? 'Analizando…' : 'Elegir archivo'}
                <input type="file" accept=".csv,.xlsx,.xls" onChange={handleFileChange} disabled={loading} />
              </label>
              <button className="button button-secondary" onClick={() => void loadExample()} disabled={loading}>
                Usar dataset de ejemplo
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="metrics-grid">
              <Metric label="Registros" value={analysis.rows} icon="▤" />
              <Metric label="Columnas" value={analysis.column_count} icon="▥" />
              <Metric label="Valores vacíos" value={analysis.null_count} icon="◌" warning={analysis.null_count > 0} />
              <Metric label="Duplicados exactos" value={analysis.exact_duplicate_count} icon="⧉" warning={analysis.exact_duplicate_count > 0} />
            </div>

            <div className="table-heading">
              <div>
                <h3>Perfil de columnas</h3>
                <p>Calculado sobre los {analysis.rows} registros. Los valores únicos excluyen vacíos; los vacíos incluyen nulos y celdas con solo espacios.</p>
              </div>
              <button className="text-button" onClick={() => { setAnalysis(null); setEmptyColumn(null); setFilteredRows(null); setMatches([]); setNotice('') }}>
                Cambiar archivo
              </button>
            </div>
            <div className="table-wrap profile-table">
              <table aria-label="Perfil de columnas">
                <thead><tr><th>Columna</th><th>Tipo de dato</th><th>Valores vacíos</th><th>Completitud</th><th>Valores únicos</th><th>Acciones</th></tr></thead>
                <tbody>
                  {analysis.column_profiles.map((profile) => (
                    <tr key={profile.name} className={emptyColumn === profile.name ? 'selected-column' : ''}>
                      <td>{profile.name}</td><td>{profile.data_type}</td><td>{profile.empty_count}</td>
                      <td>{profile.completeness.toLocaleString('es-CO', { maximumFractionDigits: 2 })}%</td><td>{profile.unique_count}</td>
                      <td><button className="text-button" aria-label={`Ver valores vacíos en ${profile.name}`} aria-pressed={emptyColumn === profile.name} onClick={() => setEmptyColumn(profile.name)}>Ver valores vacíos</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="table-heading">
              <div>
                <h3>{emptyColumn === null ? 'Vista previa' : `Valores vacíos en «${emptyColumn}»`}</h3>
                <p role="status">{emptyColumn === null ? `Primeros ${analysis.preview_limit} registros del archivo` : activeRows ? `${activeRows.total} registros afectados de ${analysis.rows}` : filterError ? 'No se pudo aplicar el filtro.' : 'Cargando registros afectados…'}</p>
              </div>
              {emptyColumn !== null && <button className="text-button" onClick={() => setEmptyColumn(null)}>Quitar filtro</button>}
            </div>
            {emptyColumn !== null && filterError && <div className="alert alert-error" role="alert">{filterError}</div>}
            <div className="table-wrap">
              <table aria-label="Registros del archivo">
                <thead><tr><th>Registro</th>{analysis.columns.map((name) => <th key={name}>{name}<small>{analysis.nulls_by_column[name] ?? 0} vacíos</small></th>)}</tr></thead>
                <tbody>
                  {visibleRows.map((row, index) => (
                    <tr key={index}><td>{emptyColumn === null ? index + 1 : activeRows?.row_numbers[index]}</td>{analysis.columns.map((name) => <td key={name}>{display(row[name])}</td>)}</tr>
                  ))}
                  {emptyColumn !== null && activeRows?.total === 0 && <tr><td colSpan={analysis.column_count + 1}>No hay valores vacíos en esta columna.</td></tr>}
                </tbody>
              </table>
            </div>

            <TextCleanup key={analysis.analysis_id} analysisId={analysis.analysis_id} filename={analysis.filename} columns={analysis.text_columns} api={API} />

            <DuplicateReview key={`duplicates:${analysis.analysis_id}`} analysisId={analysis.analysis_id} filename={analysis.filename} columns={analysis.columns} textColumns={analysis.text_columns} rowCount={analysis.rows} api={API} />

            <div className="match-panel">
              <div className="step-label"><span>04</span> ESTANDARIZACIÓN DE VALORES SIMILARES</div>
              <h3>Buscar posibles registros relacionados</h3>
              <p className="section-copy">El sistema compara valores de una columna y propone una estandarización. Tú decides si se aplica.</p>
              <div className="match-controls">
                <label className="control-group">
                  <span>Columna de comparación</span>
                  <select value={column} onChange={(event) => { setColumn(event.target.value); setMatches([]); setDecisions({}) }} disabled={analysis.text_columns.length === 0}>
                    {analysis.text_columns.map((name) => <option key={name} value={name}>{name}</option>)}
                  </select>
                </label>
                <label className="control-group threshold-control">
                  <span>Umbral de similitud <b>{threshold}%</b></span>
                  <input type="range" min="60" max="100" step="1" value={threshold} onChange={(event) => { setThreshold(Number(event.target.value)); setMatches([]); setDecisions({}) }} />
                </label>
                <button className="button button-primary search-button" onClick={() => void searchMatches()} disabled={loading || !column}>
                  {loading ? 'Analizando…' : 'Buscar similitudes'} <span>→</span>
                </button>
              </div>

              {matches.length > 0 && (
                <>
                  <div className="results-heading">
                    <div><h3>Sugerencias para revisar</h3><p>{matches.length} posible(s) coincidencia(s) encontrada(s)</p></div>
                    <span className="review-count">{approvedIds.length} aprobada(s)</span>
                  </div>
                  <div className="suggestion-list">
                    {matches.map((match) => {
                      const decision = decisions[match.id] ?? 'pending'
                      return (
                        <article className={`suggestion ${decision}`} key={match.id}>
                          <div className="match-score"><strong>{match.similarity}%</strong><span>similitud</span></div>
                          <div className="match-values">
                            <div><span>Fila {match.target_row}</span><strong>{match.current_value}</strong></div>
                            <span className="match-arrow">→</span>
                            <div><span>Sugerencia · fila {match.reference_row}</span><strong>{match.suggested_value}</strong></div>
                          </div>
                          <div className="decision-actions">
                            {decision === 'pending' ? <>
                              <button className="approve-button" onClick={() => setDecision(match.id, 'approved')}>Aprobar</button>
                              <button className="reject-button" onClick={() => setDecision(match.id, 'rejected')}>Rechazar</button>
                            </> : <>
                              <span className={`decision-label ${decision}`}>{decision === 'approved' ? '✓ Aprobada' : '× Rechazada'}</span>
                              <button className="undo-button" onClick={() => setDecision(match.id, 'pending')}>Deshacer</button>
                            </>}
                          </div>
                        </article>
                      )
                    })}
                  </div>
                  <div className="export-row">
                    <div className="preserve-note"><span>✓</span><div><strong>El original está protegido</strong><small>Las sugerencias aprobadas se aplican a una copia nueva.</small></div></div>
                    <button className="button button-dark" onClick={() => void downloadCorrectedCopy()} disabled={loading || approvedIds.length === 0}>
                      Descargar copia corregida <span>↓</span>
                    </button>
                  </div>
                </>
              )}
            </div>
          </>
        )}

        {error && <div className="alert alert-error" role="alert">{error}</div>}
        {notice && <div className="alert alert-success" role="status">{notice}</div>}
      </section>

      <footer className="page-footer">
        <span>CleanDataBot · Demo de calidad de datos</span>
        <span>Detectar <b>→</b> Revisar <b>→</b> Aprobar <b>→</b> Exportar</span>
      </footer>
    </main>
  )
}

function Metric({ label, value, icon, warning = false }: { label: string; value: number; icon: string; warning?: boolean }) {
  return <article className={`metric-card ${warning ? 'metric-warning' : ''}`}>
    <div className="metric-top"><span>{label}</span><span className="metric-icon">{icon}</span></div>
    <strong>{value.toLocaleString('es-CO')}</strong>
    <span className="metric-caption">en el dataset</span>
  </article>
}
