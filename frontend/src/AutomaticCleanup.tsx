import { useEffect, useState } from 'react'
import { ApplyResult, ModuleProps, get, post, valueText } from './api'
import type { AutoConfig, AutoEvent, AutoPlan, AutoReport, ColumnRule, PendingGroup } from './autoTypes'

const ruleLabels: Record<string, string> = {
  normalize_text: 'Normalizar espacios', canonical_variant: 'Variante a canónico',
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
      const result = await post<AutoPlan>(analysis.analysis_id, 'auto-cleanup/preview', { ...config, revision: analysis.revision }, signal)
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
  function decide(group: PendingGroup, action: 'keep_all' | 'remove_selected', keepRow?: number, removeRows: number[] = []) {
    if (!report) return
    run(async (signal) => {
      const result = await post<ApplyResult>(analysis.analysis_id, 'auto-cleanup/review', {
        revision: analysis.revision, run_id: report.run_id, group_id: group.id,
        action, keep_row: keepRow ?? null, remove_rows: removeRows,
      }, signal)
      if (!signal.aborted) { setPreview(null); applied(result) }
    })
  }
  const mapped = config ? [config.fields.name, config.fields.email, config.fields.phone, ...config.fields.identifiers].filter(Boolean) : []
  return <section className="match-panel automatic-panel" aria-labelledby="automatic-heading">
    <div className="step-label">LIMPIEZA AUTOMÁTICA</div>
    <h3 id="automatic-heading">Limpiar automáticamente y revisar solo las excepciones</h3>
    <p className="section-copy">Revisa las reglas una vez: se aplican al trabajo acumulado y el archivo original se conserva. Se eliminan duplicados exactos antes y después de estandarizar. Los demás clientes requieren nombre muy similar y correo o teléfono exacto no vacío, sin campos contradictorios.</p>
    {loadError && <div className="alert alert-error" role="alert">{loadError} <button className="text-button" onClick={() => setRetry((current) => current + 1)}>Reintentar cargar configuración</button></div>}
    {!config && !loadError && <p role="status">Cargando asociaciones de columnas…</p>}
    {config && <form onSubmit={(event) => { event.preventDefault(); generatePreview() }}>
      <details className="automatic-settings" open>
        <summary>Asociar campos y configurar reglas</summary>
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
          <label className="control-group"><span>Parecido de nombre para revisión (%)</span><input type="number" min="60" max={config.name_threshold} step="0.1" required value={config.review_threshold} onChange={(event) => changeConfig({ review_threshold: Number(event.target.value) })} /></label>
        </div>
        <p className="section-copy">Los porcentajes son parecido textual, no probabilidad de identidad. Correo y teléfono se comparan exactamente tras quitar espacios exteriores; dos vacíos nunca son evidencia. Cualquier otro campo no vacío distinto también envía el caso a revisión.</p>
        <details><summary>Columnas técnicas que pueden diferir sin bloquear (opcional)</summary><p className="section-copy">Solo para datos que sabes que no identifican al cliente, por ejemplo un número interno de fila. Se conserva su valor en el primer registro. No permite ignorar campos asociados a nombre, contacto o identificadores.</p>
          <div className="cleanup-columns">{analysis.columns.map((column) => <label key={column}><input type="checkbox" checked={config.ignored_columns.includes(column)} disabled={mapped.includes(column)} onChange={(event) => changeConfig({ ignored_columns: event.target.checked ? [...config.ignored_columns, column] : config.ignored_columns.filter((name) => name !== column) })} />{column}</label>)}</div>
        </details>
        <h4>Normalización y valores canónicos por columna</h4>
        <p className="section-copy">Los reemplazos son explícitos y solo afectan esta columna. Se incorporan inicialmente las equivalencias ya aprobadas en este análisis. No se inventan valores canónicos por parecido difuso.</p>
        <div className="automatic-column-rules">{analysis.text_columns.map((column) => <ColumnOptions key={column} column={column} rule={config.column_rules.find((rule) => rule.column === column) ?? null} change={(rule) => changeRule(column, rule)} />)}</div>
      </details>
      <button className="button button-primary" type="submit">Previsualizar limpieza automática</button>
    </form>}
    {activePreview && <div className="automatic-preview">
      <h4>Resultado propuesto sobre el trabajo actual</h4>
      <AutoSummary report={activePreview} />
      <AuditTrail title="Cambios propuestos y reglas" events={activePreview.events} />
      <p className="section-copy">Al aplicar se ejecutan los casos seguros del plan. Los grupos pendientes conservan sus registros para revisión. Se conserva el primer registro por orden original y solo se completan sus campos vacíos con datos compatibles.</p>
      <button className="button button-dark" onClick={apply}>Aplicar limpieza automática</button>
    </div>}
    {report && <div className="automatic-result">
      <h4>Última ejecución aplicada</h4>
      <AutoSummary report={report} />
      {!report.is_current && <p role="status" className="alert alert-error">El trabajo cambió después de esta ejecución. Estos resultados son históricos: genera una nueva limpieza para revisar excepciones vigentes.</p>}
      {report.is_current && <>
        <h4>Excepciones agrupadas para revisión</h4>
        <p className="section-copy">Cada registro aparece una vez, dentro de un grupo de candidatos. Una conexión transitiva no demuestra que todos sean la misma persona. Revisa los valores y selecciona únicamente las filas que decidas eliminar. La eliminación manual no completa ni sobrescribe campos.</p>
        {!report.pending_groups.length && <p role="status">No hay grupos pendientes de esta ejecución.</p>}
        <div className="duplicate-list">{report.pending_groups.map((group) => <ExceptionGroup key={`${report.run_id}:${group.id}`} group={group} columns={analysis.columns} decide={(action, keepRow, removeRows) => decide(group, action, keepRow, removeRows)} />)}</div>
      </>}
    </div>}
    {!!analysis.automatic_audit.length && <AuditTrail title="Registro de cambios automáticos y decisiones del análisis" events={analysis.automatic_audit} />}
  </section>
}

function ColumnOptions({ column, rule, change }: { column: string; rule: ColumnRule | null; change: (rule: ColumnRule | null) => void }) {
  return <details className="automatic-column"><summary>{column}{rule ? ' · reglas activas' : ' · sin reglas'}</summary>
    <label><input type="checkbox" checked={rule !== null} onChange={(event) => change(event.target.checked ? { column, trim: true, collapse_spaces: true, replacements: [] } : null)} />Configurar {column}</label>
    {rule && <>
      <div className="cleanup-columns"><label><input type="checkbox" checked={rule.trim} onChange={(event) => change({ ...rule, trim: event.target.checked })} />Recortar extremos en {column}</label><label><input type="checkbox" checked={rule.collapse_spaces} onChange={(event) => change({ ...rule, collapse_spaces: event.target.checked })} />Reducir espacios en {column}</label></div>
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
      ['Duplicados eliminados', counts.duplicates_removed], ['Grupos pendientes', counts.pending_groups],
      ['Campos vacíos completados', counts.filled_cells], ['Exactos eliminados', counts.exact_duplicates_removed],
      ['Clientes fusionados', counts.clients_merged], ['Grupos conservados por decisión previa', counts.previously_separated_groups],
    ].map(([label, count]) => <article className="metric-card" key={String(label)}><div className="metric-top">{label}</div><strong>{Number(count).toLocaleString('es-CO')}</strong></article>)}</div>
    <p className="section-copy">Los contadores describen pasos de esta ejecución; una celda puede normalizarse y luego estandarizarse. No se suman al contador neto de celdas del dataset. Las eliminaciones manuales de excepciones se contabilizan aparte en el estado actual.</p>
    {report.warnings.map((warning) => <p role="status" className="alert" key={warning}>{warning}</p>)}
  </>
}

function ExceptionGroup({ group, columns, decide }: { group: PendingGroup; columns: string[]; decide: (action: 'keep_all' | 'remove_selected', keepRow?: number, removeRows?: number[]) => void }) {
  const [keeper, setKeeper] = useState(group.records[0].row)
  const [remove, setRemove] = useState<number[]>([])
  return <article className="duplicate-pair" aria-label={`Excepción con registros ${group.records.map((row) => row.row).join(', ')}`}>
    <h4>{group.records.length} registros pendientes: {group.records.map((row) => row.row).join(', ')}</h4>
    <ul>{group.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
    <div className="table-wrap"><table aria-label="Registros de la excepción"><thead><tr><th>Eliminar al confirmar</th><th>Registro original</th>{columns.map((column) => <th key={column}>{column}{group.conflicting_columns.includes(column) && <small>Valores contradictorios</small>}</th>)}</tr></thead><tbody>
      {group.records.map((record) => <tr key={record.row}><td><input type="checkbox" aria-label={`Eliminar registro ${record.row} de esta excepción`} disabled={keeper === record.row} checked={remove.includes(record.row)} onChange={(event) => setRemove((current) => event.target.checked ? [...current, record.row] : current.filter((row) => row !== record.row))} /></td><td>{record.row}</td>{columns.map((column) => <td key={column} className={group.conflicting_columns.includes(column) ? 'automatic-conflict' : ''}><code className="cleanup-value">{valueText(record.values[column])}</code></td>)}</tr>)}
    </tbody></table></div>
    <div className="duplicate-decisions"><label className="control-group"><span>Registro que debe conservarse</span><select value={keeper} onChange={(event) => { const next = Number(event.target.value); setKeeper(next); setRemove((current) => current.filter((row) => row !== next)) }}>{group.records.map((row) => <option key={row.row} value={row.row}>Registro {row.row}</option>)}</select></label>
      <button className="button button-secondary" onClick={() => decide('keep_all')}>Son diferentes: conservar todos</button>
      <button className="button button-dark" disabled={!remove.length} onClick={() => decide('remove_selected', keeper, remove)}>Confirmar eliminación de {remove.length} registros seleccionados</button>
    </div>
  </article>
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
