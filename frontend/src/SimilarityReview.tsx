import { useState } from 'react'
import { ApplyResult, ModuleProps, post, valueText } from './api'

type Variant = { value: string; count: number; relation: 'normalized' | 'approximate'; similarity: number }
type Group = { id: string; column: string; canonical: string; kind: 'normalized' | 'approximate'; variants: Variant[]; changed_values: number }
type Groups = { proposal_id: string; revision: number; groups: Group[] }
type Match = { id: string; target_row: number; reference_row: number; current_value: string; suggested_value: string; similarity: number }
type Matches = { proposal_id: string; revision: number; matches: Match[] }
export default function SimilarityReview({ analysis, run, applied }: ModuleProps) {
  const [column, setColumn] = useState(analysis.text_columns.includes('ciudad') ? 'ciudad' : analysis.text_columns[0] ?? '')
  const [threshold, setThreshold] = useState(85)
  const [groups, setGroups] = useState<Groups | null>(null)
  const [matches, setMatches] = useState<Matches | null>(null)
  const [decisions, setDecisions] = useState<Record<string, 'approved' | 'rejected'>>({})
  const approved = matches?.matches.filter((match) => decisions[match.id] === 'approved').map((match) => match.id) ?? []
  function reset() { setGroups(null); setMatches(null); setDecisions({}) }
  function searchGroups() {
    setGroups(null)
    run(async (signal) => { const result = await post<Groups>(analysis.analysis_id, 'groups/search', { column, threshold }, signal); if (!signal.aborted) setGroups(result) })
  }
  function searchMatches() {
    setMatches(null); setDecisions({})
    run(async (signal) => { const result = await post<Matches>(analysis.analysis_id, 'matches', { column, threshold }, signal); if (!signal.aborted) setMatches(result) })
  }
  function applyMatches() {
    if (!matches) return
    run(async (signal) => {
      const result = await post<ApplyResult>(analysis.analysis_id, 'matches/apply', { proposal_id: matches.proposal_id, revision: matches.revision, approved_match_ids: approved }, signal)
      if (!signal.aborted) applied(result)
    })
  }
  return <section className="match-panel" aria-labelledby="similarity-heading"><div className="step-label"><span>04</span> ESTANDARIZACIÓN DE VALORES</div><h3 id="similarity-heading">Corregir variantes por grupos o individualmente</h3>
    <p className="section-copy">Las equivalencias por tildes, espacios y mayúsculas se distinguen de las propuestas aproximadas. El porcentaje es parecido textual; no determina si dos registros representan a la misma persona. Ninguna corrección de este módulo elimina filas.</p>
    <div className="match-controls"><label className="control-group"><span>Columna de comparación</span><select value={column} onChange={(event) => { setColumn(event.target.value); reset() }} disabled={!analysis.text_columns.length}>{analysis.text_columns.map((name) => <option key={name} value={name}>{name}</option>)}</select></label>
      <label className="control-group threshold-control"><span>Umbral de parecido textual <b>{threshold}%</b></span><input type="range" min="60" max="100" value={threshold} onChange={(event) => { setThreshold(Number(event.target.value)); reset() }} /></label>
      <div className="cleanup-columns"><button className="button button-primary" disabled={!column} onClick={searchGroups}>Buscar grupos de variantes</button><button className="button button-secondary" disabled={!column} onClick={searchMatches}>Buscar similitudes individuales</button></div>
    </div>
    {groups && <><div className="results-heading"><h3>{groups.groups.length} grupos propuestos en {column}</h3></div>
      {!groups.groups.length && <p role="status">No hay grupos con estos criterios.</p>}
      <div className="duplicate-list">{groups.groups.map((group) => <GroupCard key={`${groups.proposal_id}:${group.id}`} group={group} approve={(variants, canonical) => {
        run(async (signal) => {
          const result = await post<ApplyResult>(analysis.analysis_id, 'groups/apply', { proposal_id: groups.proposal_id, revision: groups.revision, group_id: group.id, variants, canonical }, signal)
          if (!signal.aborted) applied(result)
        })
      }} />)}</div></>}
    {matches && <><div className="results-heading"><div><h3>Sugerencias individuales</h3><p>{matches.matches.length} propuestas · {approved.length} aprobadas</p></div></div>
      {!matches.matches.length && <p role="status">No se encontraron sugerencias.</p>}
      <div className="suggestion-list">{matches.matches.map((match) => <article className={`suggestion ${decisions[match.id] ?? ''}`} key={match.id}>
        <div className="match-score"><strong>{match.similarity}%</strong><span>parecido textual</span></div><div className="match-values"><div><span>Registro {match.target_row}</span><strong>{valueText(match.current_value)}</strong></div><span>→</span><div><span>Propuesta · registro {match.reference_row}</span><strong>{valueText(match.suggested_value)}</strong></div></div>
        <div className="decision-actions"><button className="approve-button" aria-pressed={decisions[match.id] === 'approved'} onClick={() => setDecisions((current) => ({ ...current, [match.id]: 'approved' }))}>Aprobar</button><button className="reject-button" aria-pressed={decisions[match.id] === 'rejected'} onClick={() => setDecisions((current) => ({ ...current, [match.id]: 'rejected' }))}>Rechazar</button><button className="undo-button" onClick={() => setDecisions((current) => { const next = { ...current }; delete next[match.id]; return next })}>Deshacer</button></div>
      </article>)}</div><div className="export-row"><p className="section-copy">Solo se aplicarán las propuestas aprobadas.</p><button className="button button-dark" disabled={!approved.length} onClick={applyMatches}>Aplicar cambios aprobados</button></div>
    </>}
  </section>
}
function GroupCard({ group, approve }: { group: Group; approve: (variants: string[], canonical: string) => void }) {
  const [canonical, setCanonical] = useState(group.canonical)
  const [manual, setManual] = useState(false)
  // Approximate variants require explicit inclusion. Normalized equivalences are
  // preselected but the whole operation still requires the approval button.
  const [selected, setSelected] = useState(group.variants.filter((variant) => variant.relation === 'normalized').map((variant) => variant.value))
  const changed = group.variants.reduce((count, variant) => count + (selected.includes(variant.value) && variant.value !== canonical ? variant.count : 0), 0)
  return <article className="duplicate-pair" aria-label={`Grupo de ${group.column}`}><div className="results-heading"><h3>Columna: {group.column}</h3><span className="review-count">{group.kind === 'normalized' ? 'Equivalentes por normalización' : 'Propuesta aproximada: revisar'}</span></div>
    <p className="section-copy">Ancla propuesta: {valueText(group.canonical)}. Cada variante aproximada se compara directamente con esta ancla; no se agrupan cadenas transitivas. Excluye cualquier variante que no deba corregirse.</p>
    <div className="table-wrap"><table aria-label={`Variantes de ${group.column}`}><thead><tr><th>Incluir</th><th>Variante original</th><th>Apariciones</th><th>Relación con el ancla</th></tr></thead><tbody>{group.variants.map((variant) => <tr key={variant.value}><td><input type="checkbox" aria-label={`Incluir variante ${variant.value}`} checked={selected.includes(variant.value)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, variant.value] : current.filter((value) => value !== variant.value))} /></td><td><code className="cleanup-value">{valueText(variant.value)}</code></td><td>{variant.count}</td><td>{variant.relation === 'normalized' ? 'Equivalente por normalización' : `Aproximada · ${variant.similarity}% parecido textual`}</td></tr>)}</tbody></table></div>
    <div className="duplicate-decisions"><label className="control-group"><span>Valor canónico entre las variantes</span><select value={manual ? '' : canonical} onChange={(event) => { if (event.target.value) { setManual(false); setCanonical(event.target.value) } }}><option value="" disabled>Seleccionar una variante</option>{group.variants.map((variant) => <option key={variant.value} value={variant.value}>{valueText(variant.value)}</option>)}</select></label>
      <label className="control-group"><span>O escribir un valor canónico manualmente</span><input type="text" value={canonical} onChange={(event) => { setManual(true); setCanonical(event.target.value) }} /></label>
    </div><div className="export-row"><p className="section-copy" role="status">Cambiarán {changed} celdas de {group.column}. Los valores que ya coinciden y las variantes excluidas permanecerán iguales. No se eliminarán filas.</p><button className="button button-dark" disabled={!changed || !canonical.trim()} onClick={() => approve(selected, canonical)}>Aprobar y aplicar grupo</button></div>
  </article>
}
