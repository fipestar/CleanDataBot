import { useEffect, useState } from 'react'
import { ApplyResult, ModuleProps, get, post, valueText } from './api'
import type { AutoConfig, AutoEvent, AutoPlan, AutoReport, ColumnRule } from './autoTypes'

const ruleLabels: Record<string, string> = {
  normalize_date: 'Normalizar fecha a ISO', normalize_text: 'Normalizar espacios', canonical_variant: 'Variante a canónico',
  exact_duplicate_before: 'Duplicado exacto inicial',
  exact_duplicate_after_standardization: 'Duplicado exacto tras estandarizar',
  exact_duplicate_after_merge: 'Duplicado exacto tras completar campos',
  fill_empty_field: 'Completar campo vacío', client_exact_contact_and_name: 'Nombre y contacto sin conflictos',
  manual_keep_all: 'Decisión manual: conservar todos', manual_exception_removal: 'Eliminación manual de excepción',
}

export default function AutomaticCleanup({ analysis, run, applied }: ModuleProps) {
  const [config, setConfig] = useState<AutoConfig | null>(null)
  const [loadError, setLoadError] = useState('')
  const [suggestionWarnings, setSuggestionWarnings] = useState<string[]>([])
  const [retry, setRetry] = useState(0)
  const [preview, setPreview] = useState<AutoPlan | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    setLoadError('')
    void get<{ config: AutoConfig; warnings: string[] }>(`/api/analyses/${analysis.analysis_id}/auto-cleanup/config`, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) { setConfig(result.config); setSuggestionWarnings(result.warnings) }
      }).catch((reason) => { if (!controller.signal.aborted) setLoadError(reason instanceof Error ? reason.message : 'No se pudo cargar la configuración.') })
    return () => controller.abort()
  }, [analysis.analysis_id, retry])

  const activePreview = preview?.revision === analysis.revision ? preview : null
  const report = analysis.automatic_report
  function changeConfig(update: Partial<AutoConfig>) {
    setConfig((current) => current ? { ...current, ...update } : current)
    setPreview(null)
  }
  function changeRule(column: string, rule: ColumnRule | null) {
    if (!config) return
    changeConfig({ column_rules: [...config.column_rules.filter((item) => item.column !== column), ...(rule ? [rule] : [])] })
  }
  function generatePreview() {
    if (!config) return
    setPreview(null)
    run(async (signal) => {
      const result = await post<AutoPlan>(analysis.analysis_id, 'auto-cleanup/preview', { ...config, all_columns: true, revision: analysis.revision }, signal)
      if (!signal.aborted) setPreview(result)
    })
  }
  function apply() {
    if (!activePreview) return
    run(async (signal) => {
      const result = await post<ApplyResult>(analysis.analysis_id, 'auto-cleanup/apply', { plan_id: activePreview.plan_id, revision: activePreview.revision }, signal)
      if (!signal.aborted) { setPreview(null); applied(result) }
    })
  }
  function cleanAll() {
    if (!config) return
    setPreview(null)
    run(async (signal) => {
      const plan = await post<AutoPlan>(analysis.analysis_id, 'auto-cleanup/preview', { ...config, all_columns: true, revision: analysis.revision }, signal)
      if (signal.aborted) return
      const result = await post<ApplyResult>(analysis.analysis_id, 'auto-cleanup/apply', { plan_id: plan.plan_id, revision: plan.revision }, signal)
      if (!signal.aborted) applied(result)
    })
  }
  const mapped = config ? [config.fields.name, config.fields.email, config.fields.phone, ...config.fields.identifiers].filter(Boolean) : []
  return <section className="match-panel automatic-panel" aria-labelledby="automatic-heading">
    <div className="step-label">LIMPIEZA AUTOMÁTICA</div>
    <h3 id="automatic-heading">Limpiar todas las columnas automáticamente</h3>
    <p className="section-copy">Se limpian espacios en todas las columnas de texto, se aplican los canónicos configurados y se normalizan las fechas reconocibles. Se eliminan duplicados exactos y solo se fusionan clientes con evidencia suficiente. Los casos dudosos se conservan sin solicitar revisión por grupos. El original permanece intacto.</p>
    {loadError && <div className="alert alert-error" role="alert">{loadError} <button className="text-button" onClick={() => setRetry((current) => current + 1)}>Reintentar cargar configuración</button></div>}
    {!config && !loadError && <p role="status">Cargando asociaciones de columnas…</p>}
    {config && <form onSubmit={(event) => { event.preventDefault(); generatePreview() }}>
      <details className="automatic-settings">
        <summary>Opciones de fechas, asociaciones y valores canónicos</summary>
        {suggestionWarnings.map((warning) => <p className="section-copy" key={warning}>{warning}</p>)}
        <div className="automatic-mappings">
          {(['name', 'email', 'phone'] as const).map((role) => <label className="control-group" key={role}>
            <span>{({ name: 'Campo de nombre', email: 'Campo de correo', phone: 'Campo de teléfono' })[role]}</span>
            <select value={config.fields[role] ?? ''} onChange={(event) => changeConfig({ fields: { ...config.fields, [role]: event.target.value || null } })}>
              <option value="">Sin asociar</option>
              {analysis.columns.map((column) => <option key={column} value={column} disabled={mapped.includes(column) && config.fields[role] !== column}>{column}</option>)}
            </select>
          </label>)}
        </div>
        <fieldset className="cleanup-options"><legend>Identificadores del cliente: cualquier contradicción bloquea la fusión</legend>
          <div className="cleanup-columns">{analysis.columns.map((column) => <label key={column}><input type="checkbox" checked={config.fields.identifiers.includes(column)} disabled={[config.fields.name, config.fields.email, config.fields.phone].includes(column) || config.ignored_columns.includes(column)} onChange={(event) => changeConfig({ fields: { ...config.fields, identifiers: event.target.checked ? [...config.fields.identifiers, column] : config.fields.identifiers.filter((name) => name !== column) } })} />{column}</label>)}</div>
        </fieldset>
        <p className="section-copy">Asociaciones como full_name → nombre y email → correo se sugieren por encabezado. Si falta nombre o contacto, se omite la fusión automática y se explica en el resultado. Un ID técnico distinto también bloquea la fusión hasta configurarlo explícitamente.</p>
        <div className="automatic-mappings">
          <label className="control-group"><span><input type="checkbox" checked={config.merge_clients} onChange={(event) => changeConfig({ merge_clients: event.target.checked })} /> Resolver clientes con evidencia suficiente</span></label>
          <label className="control-group"><span>Parecido mínimo de nombre para fusión (%)</span><input type="number" min="90" max="100" step="0.1" required value={config.name_threshold} onChange={(event) => changeConfig({ name_threshold: Number(event.target.value) })} /></label>
        </div>
        <p className="section-copy">Los porcentajes son parecido textual, no probabilidad de identidad. Correo y teléfono se comparan exactamente tras quitar espacios exteriores; dos vacíos nunca son evidencia. Cualquier otro campo no vacío distinto bloquea la fusión y conserva los registros.</p>
        <details><summary>Columnas técnicas que pueden diferir sin bloquear (opcional)</summary><p className="section-copy">Solo para datos que sabes que no identifican al cliente, por ejemplo un número interno de fila. Se conserva su valor en el primer registro. No permite ignorar campos asociados a nombre, contacto o identificadores.</p>
          <div className="cleanup-columns">{analysis.columns.map((column) => <label key={column}><input type="checkbox" checked={config.ignored_columns.includes(column)} disabled={mapped.includes(column)} onChange={(event) => changeConfig({ ignored_columns: event.target.checked ? [...config.ignored_columns, column] : config.ignored_columns.filter((name) => name !== column) })} />{column}</label>)}</div>
        </details>
        <h4>Fechas</h4>
        <label><input type="checkbox" checked={config.normalize_dates} onChange={(event) => changeConfig({ normalize_dates: event.target.checked })} /> Normalizar fechas reconocibles a ISO 8601</label>
        <label className="control-group"><span>Orden de fechas con el año al final</span><select value={config.date_order} onChange={(event) => changeConfig({ date_order: event.target.value as AutoConfig['date_order'] })}>
          <option value="auto">Automático: conservar fechas ambiguas</option><option value="dmy">Día / mes / año</option><option value="mdy">Mes / día / año</option>
        </select></label>
        <p className="section-copy">Salida: AAAA-MM-DD. Se conservan horas y zonas horarias si existen. En automático, 03/04/2026 se conserva hasta elegir un orden. Los números y códigos no se interpretan como fechas.</p>
        <h4>Valores canónicos por columna</h4>
        <p className="section-copy">Los reemplazos son explícitos y solo afectan esta columna. Se incorporan inicialmente las equivalencias ya aprobadas en este análisis. No se inventan valores canónicos por parecido difuso.</p>
        <div className="automatic-column-rules">{analysis.text_columns.map((column) => <ColumnOptions key={column} column={column} rule={config.column_rules.find((rule) => rule.column === column) ?? { column, trim: true, collapse_spaces: true, replacements: [] }} change={(rule) => changeRule(column, rule)} />)}</div>
      </details>
      <div className="upload-actions"><button className="button button-primary" type="button" onClick={cleanAll}>Limpiar automáticamente todas las columnas</button>
        <button className="button button-secondary" type="submit">Previsualizar cambios (opcional)</button></div>
    </form>}
    {activePreview && <div className="automatic-preview">
      <h4>Resultado propuesto sobre el trabajo actual</h4>
      <AutoSummary report={activePreview} />
      <AuditTrail title="Cambios propuestos y reglas" events={activePreview.events} />
      <p className="section-copy">Al aplicar se ejecutan todos los cambios seguros del plan. Los registros dudosos se conservan sin fusionarlos. Se conserva el primer registro por orden original y solo se completan sus campos vacíos con datos compatibles.</p>
      <button className="button button-dark" onClick={apply}>Aplicar limpieza automática</button>
    </div>}
    {report && <div className="automatic-result">
      <h4>Última ejecución aplicada</h4>
      <AutoSummary report={report} />
      {!report.is_current && <p role="status" className="alert alert-error">El trabajo cambió después de esta ejecución. Estos resultados son históricos: ejecuta la limpieza para actualizar el resultado.</p>}
    </div>}
    {!!analysis.automatic_audit.length && <AuditTrail title="Registro de cambios automáticos y decisiones del análisis" events={analysis.automatic_audit} />}
  </section>
}

function ColumnOptions({ column, rule, change }: { column: string; rule: ColumnRule | null; change: (rule: ColumnRule | null) => void }) {
  return <details className="automatic-column"><summary>{column} · valores canónicos</summary>
    {rule && <>
      <div className="table-wrap"><table aria-label={`Reemplazos automáticos de ${column}`}><thead><tr><th>Variante exacta</th><th>Valor canónico</th><th>Acción</th></tr></thead><tbody>
        {rule.replacements.map((replacement, index) => <tr key={index}><td><input type="text" aria-label={`Variante ${index + 1} de ${column}`} value={replacement.variant} required onChange={(event) => change({ ...rule, replacements: rule.replacements.map((value, position) => position === index ? { ...value, variant: event.target.value } : value) })} /></td><td><input type="text" aria-label={`Canónico ${index + 1} de ${column}`} value={replacement.canonical} required onChange={(event) => change({ ...rule, replacements: rule.replacements.map((value, position) => position === index ? { ...value, canonical: event.target.value } : value) })} /></td><td><button className="text-button" type="button" onClick={() => change({ ...rule, replacements: rule.replacements.filter((_, position) => position !== index) })}>Quitar reemplazo</button></td></tr>)}
        {!rule.replacements.length && <tr><td colSpan={3}>No hay reemplazos configurados en esta columna.</td></tr>}
      </tbody></table></div>
      <button className="text-button" type="button" onClick={() => change({ ...rule, replacements: [...rule.replacements, { variant: '', canonical: '' }] })}>Agregar reemplazo en {column}</button>
    </>}
  </details>
}

function AutoSummary({ report }: { report: AutoPlan | AutoReport }) {
  const counts = report.counts
  return <>
    <div className="metrics-grid automatic-metrics">{[
      ['Celdas normalizadas', counts.normalized_cells], ['Variantes estandarizadas (celdas)', counts.standardized_cells],
      ['Duplicados eliminados', counts.duplicates_removed], ['Fechas normalizadas', counts.dates_normalized ?? 0],
      ['Campos vacíos completados', counts.filled_cells], ['Exactos eliminados', counts.exact_duplicates_removed],
      ['Clientes fusionados', counts.clients_merged], ['Fechas conservadas sin interpretar', counts.dates_skipped ?? 0],
    ].map(([label, count]) => <article className="metric-card" key={String(label)}><div className="metric-top">{label}</div><strong>{Number(count).toLocaleString('es-CO')}</strong></article>)}</div>
    <p className="section-copy">Los contadores describen pasos de esta ejecución; una celda puede normalizarse y luego estandarizarse. No se suman al contador neto de celdas del dataset. Puedes descargar el resultado acumulado desde la acción principal.</p>
    {report.warnings.map((warning) => <p role="status" className="alert" key={warning}>{warning}</p>)}
    {!!report.date_issues?.length && <details><summary>Fechas conservadas sin interpretar</summary><ul>{report.date_issues.map((issue) => <li key={`${issue.column}:${issue.row}`}>Registro {issue.row}, {issue.column}: {valueText(issue.value)}. {issue.reason}</li>)}</ul></details>}
  </>
}

function AuditTrail({ title, events }: { title: string; events: AutoEvent[] }) {
  const [open, setOpen] = useState(false)
  return <details className="automatic-audit" onToggle={(event) => setOpen(event.currentTarget.open)}><summary>{title} ({events.length})</summary>
    {open && <div className="table-wrap"><table aria-label={title}><thead><tr><th>Regla</th><th>Registros</th><th>Columna</th><th>Antes</th><th>Después / evidencia</th></tr></thead><tbody>{events.map((event, index) => <tr key={index}>
      <td>{ruleLabels[event.rule] ?? event.rule}</td><td>{event.row ?? event.rows?.join(', ')}{event.kept_row ? ` → conserva ${event.kept_row}` : ''}{event.source_row ? ` desde ${event.source_row}` : ''}</td><td>{event.column ?? '—'}</td>
      <td><code className="cleanup-value">{'before' in event ? valueText(event.before) : '—'}</code></td><td><code className="cleanup-value">{'after' in event ? valueText(event.after) : event.evidence ? `Coincidencia exacta: ${event.evidence.join(', ')}; nombre ${event.name_similarity}% (umbral ${event.threshold}%); columnas técnicas ignoradas: ${event.ignored_columns?.join(', ') || 'ninguna'}` : event.rule === 'manual_keep_all' ? 'Se conservan todos los registros del grupo' : event.removed_rows?.length ? `Eliminados: ${event.removed_rows.join(', ')}` : 'Se conserva el primer registro'}</code></td>
    </tr>)}</tbody></table></div>}
  </details>
}
