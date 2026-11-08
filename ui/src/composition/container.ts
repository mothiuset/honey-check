// Raíz de composición: elige el adaptador HTTP y construye los casos de uso que recibe el store.

import {
  createComparisonUseCases,
  createDeviceUseCases,
  createInventoryUseCases,
  createSessionUseCases,
  createSupportUseCases,
  type AppUseCases,
} from '@/application/use-cases'
import { ApiClient } from '@/infrastructure/http/client/ApiClient'
import { HttpHoneyCheckGateway } from '@/infrastructure/http/honey-check/adapters/HttpHoneyCheckGateway'

export interface AppContainer {
  readonly useCases: AppUseCases
}

export function buildContainer(): AppContainer {
  const gateway = new HttpHoneyCheckGateway(new ApiClient())
  return {
    useCases: {
      session: createSessionUseCases({ gateway }),
      inventories: createInventoryUseCases({ gateway }),
      devices: createDeviceUseCases({ gateway }),
      comparison: createComparisonUseCases({ gateway }),
      support: createSupportUseCases({ gateway }),
    },
  }
}
