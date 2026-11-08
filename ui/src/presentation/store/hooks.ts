// Único punto de enlace entre React y Redux: los hooks de cada capacidad usan estos dos.

import { useDispatch, useSelector } from 'react-redux'
import type { AppDispatch, RootState } from './store.types'

export const useAppDispatch = useDispatch.withTypes<AppDispatch>()
export const useAppSelector = useSelector.withTypes<RootState>()
