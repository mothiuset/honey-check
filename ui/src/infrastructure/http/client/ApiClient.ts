// Cliente de la API local. Toda petición que cambia algo lleva el token CSRF de la sesión, y los
// errores del servicio se traducen al error del puerto.

import { GatewayError } from '@/application/ports/HoneyCheckGateway'

const CSRF_HEADER = 'X-Honey-Check-CSRF'

type QueryValue = string | number | null | undefined

function field(data: unknown, name: string): string | null {
  if (typeof data !== 'object' || data === null) return null
  const value: unknown = (data as Record<string, unknown>)[name]
  return typeof value === 'string' ? value : null
}

export class ApiClient {
  private csrfToken: string | null = null

  constructor(
    private readonly request: typeof fetch = (...args) => fetch(...args),
  ) {}

  useCsrfToken(token: string): void {
    this.csrfToken = token
  }

  // El servicio es parte del mismo ejecutable y versiona su contrato junto con esta interfaz:
  // la respuesta se acepta con la forma que declara el llamador.
  async send<T>(
    path: string,
    options: { method?: 'GET' | 'POST'; body?: unknown } = {},
  ): Promise<T> {
    const method = options.method ?? 'GET'
    const headers: Record<string, string> = {}
    if (method !== 'GET' && this.csrfToken)
      headers[CSRF_HEADER] = this.csrfToken
    if (options.body !== undefined) headers['Content-Type'] = 'application/json'
    const init: RequestInit = { method, headers, credentials: 'same-origin' }
    if (options.body !== undefined) init.body = JSON.stringify(options.body)
    const response = await this.request(path, init)
    const isJson =
      response.headers.get('content-type')?.includes('application/json') ??
      false
    const data: unknown = isJson ? await response.json() : null
    if (!response.ok)
      throw new GatewayError(
        response.status,
        field(data, 'error'),
        field(data, 'reason'),
      )
    return data as T
  }
}

export function query(params: Readonly<Record<string, QueryValue>>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '')
      search.set(key, String(value))
  }
  return search.toString()
}
