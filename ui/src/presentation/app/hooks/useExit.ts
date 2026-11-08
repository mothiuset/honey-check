import { exitApp, useAppDispatch } from '@/presentation/store'

export function useExit() {
  const dispatch = useAppDispatch()
  return () => void dispatch(exitApp())
}
