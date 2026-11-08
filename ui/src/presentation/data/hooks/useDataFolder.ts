import { useState } from 'react'
import { specText } from '@/presentation/shared/formatters'
import { useCurrentInventory } from '@/presentation/shared/hooks/useCurrentInventory'
import { useLinks } from '@/presentation/shared/hooks/useLinks'
import { useOpenFolder } from '@/presentation/shared/hooks/useOpenFolder'
import {
  exportPending,
  selectStatus,
  useAppDispatch,
  useAppSelector,
} from '@/presentation/store'
import { exportRejection, workspaceState } from '../formatters/dataFolderText'

/** Estado de la carpeta de datos y el guardado alternativo de un análisis pendiente. */
export function useDataFolder() {
  const dispatch = useAppDispatch()
  const status = useAppSelector(selectStatus)
  const { inventory, inventoryId } = useCurrentInventory()
  const links = useLinks()
  const openFolder = useOpenFolder()
  const [directory, setDirectory] = useState('')
  const [feedback, setFeedback] = useState<string | null>(null)

  const workspace = status?.workspace ?? null
  const last = status?.lastSaved

  async function save(): Promise<void> {
    setFeedback('Guardando.')
    const result = await dispatch(exportPending(directory)).unwrap()
    setFeedback(result.ok ? 'Guardado.' : exportRejection(result.reason))
  }

  return {
    pending: status?.exportFailure != null,
    directory,
    setDirectory,
    feedback,
    save: () => void save(),
    rows: [
      specText('Carpeta de datos', workspace?.directory),
      specText('Estado', workspaceState(workspace)),
      specText(
        'Último archivo guardado',
        last ? `${last.directory}\\${last.fileName}` : null,
      ),
      specText('Versión del esquema', inventory?.schema.version),
    ],
    openDataFolder: () => {
      openFolder()
    },
    pendingDownloadUrl: links.pendingDownload(),
    currentDownloadUrl: inventoryId ? links.download(inventoryId) : null,
  }
}
