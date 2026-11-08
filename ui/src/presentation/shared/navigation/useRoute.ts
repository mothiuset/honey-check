import { useSyncExternalStore } from 'react'
import { currentRoute, subscribeRoute, type Route } from './hashRoute'

export function useRoute(): Route {
  return useSyncExternalStore(subscribeRoute, currentRoute)
}
