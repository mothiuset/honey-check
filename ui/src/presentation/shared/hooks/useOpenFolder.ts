import { openFolder, useAppDispatch } from '@/presentation/store'

/** Abre en el Explorador la carpeta de datos o una carpeta dentro de ella. */
export function useOpenFolder() {
  const dispatch = useAppDispatch()
  return (path?: string) => void dispatch(openFolder(path))
}
