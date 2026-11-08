// Sesión con el servicio local: entrar, seguir su estado, analizar, elevar permisos y salir.

import {
  GatewayError,
  type HoneyCheckGateway,
} from '../../ports/HoneyCheckGateway'
import type { SessionUseCases } from './session.types'

const hasCode = (error: unknown, code: string) =>
  error instanceof GatewayError && error.code === code

export function createSessionUseCases({
  gateway,
}: {
  gateway: HoneyCheckGateway
}): SessionUseCases {
  return {
    async start() {
      const { appVersion } = await gateway.session()
      return { appVersion, status: await gateway.status() }
    },

    async readStatus() {
      try {
        return { ok: true, status: await gateway.status() }
      } catch (error) {
        const lost = error instanceof GatewayError && error.status === 401
        return { ok: false, reason: lost ? 'session_lost' : 'service_stopped' }
      }
    },

    async startScan() {
      try {
        await gateway.startScan()
        return { ok: true }
      } catch (error) {
        return {
          ok: false,
          reason: hasCode(error, 'scan_already_running')
            ? 'already_running'
            : 'failed',
        }
      }
    },

    cancelScan: () => gateway.cancelScan(),

    async elevate() {
      try {
        await gateway.elevate()
        return { ok: true }
      } catch (error) {
        return {
          ok: false,
          reason: hasCode(error, 'elevation_cancelled')
            ? 'cancelled'
            : 'failed',
        }
      }
    },

    exit: () => gateway.exit(),
    openFolder: (path?: string) => gateway.openFolder(path),
  }
}
