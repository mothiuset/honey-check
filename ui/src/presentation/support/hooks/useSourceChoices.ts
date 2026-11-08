import { useEffect } from 'react'
import {
  loadSource,
  selectSupportSource,
  useAppDispatch,
  useAppSelector,
} from '@/presentation/store'

/** Opciones en vivo de un parámetro; se vuelven a leer al abrir la herramienta y al pedirlo. */
export function useSourceChoices(source: string) {
  const dispatch = useAppDispatch()
  const choices = useAppSelector(selectSupportSource(source))
  useEffect(() => {
    void dispatch(loadSource(source))
  }, [dispatch, source])
  return {
    choices: choices === 'failed' ? null : (choices ?? null),
    failed: choices === 'failed',
    reload: () => void dispatch(loadSource(source)),
  }
}
