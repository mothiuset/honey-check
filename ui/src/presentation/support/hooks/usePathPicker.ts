import { useState } from 'react'
import { pickPath, useAppDispatch } from '@/presentation/store'

/** Elegir una carpeta o un archivo con el diálogo de Windows (el servicio corre en este equipo). */
export function usePathPicker() {
  const dispatch = useAppDispatch()
  const [open, setOpen] = useState(false)
  return {
    open,
    pick: async (
      kind: 'folder' | 'file',
      title: string,
      filter: string | null = null,
    ): Promise<string | null> => {
      setOpen(true)
      try {
        return await dispatch(pickPath({ kind, title, filter })).unwrap()
      } finally {
        setOpen(false)
      }
    },
  }
}
