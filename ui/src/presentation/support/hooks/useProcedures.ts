import { useEffect, useState } from 'react'
import type { Procedure } from '@/application'
import {
  loadProcedureVersions,
  loadProcedures,
  removeProcedure,
  saveProcedure,
  selectProcedureMessage,
  selectProcedureRuns,
  selectProcedures,
  supportActions,
  useAppDispatch,
  useAppSelector,
} from '@/presentation/store'

export const NEW_PROCEDURE = {
  slug: 'mi-proceso',
  name: 'Mi proceso',
  description: 'Qué deja listo este proceso.',
  steps: [
    {
      id: 'instalar',
      kind: 'install',
      title: 'Instalar el programa',
      params: { file: 'programa.msi', args: '' },
    },
    {
      id: 'comprobar',
      kind: 'verify_program',
      title: 'Comprobar que quedó instalado',
      params: { name: 'Programa' },
    },
    { id: 'revisar', kind: 'manual', title: 'Abrir el programa y revisarlo' },
  ],
}

/** Lo que se edita: la definición sin los campos que pone el servicio (versión, fecha, plantilla). */
function editable(procedure: Procedure): string {
  const { slug, name, description, steps } = procedure
  return JSON.stringify({ slug, name, description, steps }, null, 2)
}

/** Procesos de instalación: catálogo, ejecuciones recientes, versiones y edición en JSON. */
export function useProcedures() {
  const dispatch = useAppDispatch()
  const procedures = useAppSelector(selectProcedures)
  const runs = useAppSelector(selectProcedureRuns)
  const message = useAppSelector(selectProcedureMessage)
  const [editing, setEditing] = useState<string | null>(null)

  useEffect(() => {
    void dispatch(loadProcedures())
    return () => {
      dispatch(supportActions.procedureMessageShown(null))
    }
  }, [dispatch])

  return {
    procedures,
    runs,
    message,
    editing,
    setEditing,
    edit: (procedure: Procedure) => {
      dispatch(supportActions.procedureMessageShown(null))
      setEditing(editable(procedure))
    },
    create: () => {
      dispatch(supportActions.procedureMessageShown(null))
      setEditing(JSON.stringify(NEW_PROCEDURE, null, 2))
    },
    save: async () => {
      if (editing === null) return
      const saved = await dispatch(saveProcedure(editing)).unwrap()
      if (saved) setEditing(null)
    },
    remove: (procedure: Procedure) =>
      void dispatch(
        removeProcedure({ slug: procedure.slug, name: procedure.name }),
      ),
    loadVersions: (slug: string) => void dispatch(loadProcedureVersions(slug)),
  }
}
