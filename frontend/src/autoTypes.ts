import type { Row } from './api'

export type ColumnRule = {
  column: string; trim: boolean; collapse_spaces: boolean
  replacements: { variant: string; canonical: string }[]
}
export type AutoFields = { name: string | null; email: string | null; phone: string | null; identifiers: string[] }
export type AutoConfig = {
  all_columns: boolean; normalize_dates: boolean; date_order: 'auto' | 'dmy' | 'mdy'
  normalize_countries: boolean; country_format: 'es' | 'en' | 'iso2' | 'iso3'; country_columns: string[] | null
  revision: number; column_rules: ColumnRule[]; fields: AutoFields
  merge_clients: boolean; name_threshold: number; review_threshold: number; ignored_columns: string[]
}
export type AutoEvent = {
  rule: string; row?: number; column?: string; before?: unknown; after?: unknown
  kept_row?: number; source_row?: number; evidence?: string[]; name_similarity?: number
  threshold?: number; ignored_columns?: string[]
  rows?: number[]; removed_rows?: number[]; revision?: number; run_id?: string
}
export type PendingGroup = {
  id: string; records: { row: number; values: Row }[]
  reasons: string[]; conflicting_columns: string[]; related_pairs?: number
}
export type AutoPlan = {
  plan_id: string; revision: number; rows_before: number; rows_after: number
  fields: AutoFields; warnings: string[]; events: AutoEvent[]; pending_groups: PendingGroup[]
  date_issues?: { row: number; column: string; value: unknown; reason: string }[]
  country_issues?: { row: number; column: string; value: unknown; reason: string }[]
  counts: {
    normalized_cells: number; standardized_cells: number; exact_duplicates_removed: number
    clients_merged: number; filled_cells: number; duplicates_removed: number; pending_groups: number
    previously_separated_groups: number
    dates_normalized?: number; dates_skipped?: number
    countries_normalized?: number; countries_skipped?: number
  }
}
export type AutoReport = AutoPlan & {
  run_id: string; source_revision: number; is_current: boolean; manual_rows_removed: number
}
