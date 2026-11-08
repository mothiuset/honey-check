import type { ToolDefinition } from '@/application'
import type { RootState } from '../store.types'

export const selectSupportCatalog = (state: RootState) => state.support.catalog
export const selectSupportCatalogFailed = (state: RootState) =>
  state.support.catalogFailed
export const selectSupportPlan = (state: RootState) => state.support.plan
export const selectSupportPreparing = (state: RootState) =>
  state.support.preparing
export const selectSupportNotice = (state: RootState) => state.support.notice
export const selectSupportRun = (state: RootState) => state.support.run
export const selectSupportHistory = (state: RootState) => state.support.history
export const selectProcedures = (state: RootState) => state.support.procedures
export const selectProcedureRuns = (state: RootState) =>
  state.support.procedureRuns
export const selectProcedureVersions = (slug: string) => (state: RootState) =>
  state.support.versions[slug]
export const selectProcedureMessage = (state: RootState) =>
  state.support.procedureMessage

export const selectToolById =
  (toolId: string) =>
  (state: RootState): ToolDefinition | undefined =>
    state.support.catalog?.find((tool) => tool.id === toolId)
export const selectSupportSource = (name: string) => (state: RootState) =>
  state.support.sources[name]
export const selectToolVersions = (tool: string) => (state: RootState) =>
  state.support.toolVersions[tool]
export const selectPreviousRun = (state: RootState) => state.support.previous
export const selectSupportStale = (state: RootState) => state.support.stale
