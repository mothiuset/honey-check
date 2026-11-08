// Temporizador del seguimiento de estado: más frecuente mientras hay un análisis en curso.

const POLL_RUNNING_MS = 800
const POLL_IDLE_MS = 4000

let timer: ReturnType<typeof setTimeout> | null = null

export function schedulePoll(scanActive: boolean, poll: () => void): void {
  cancelPoll()
  timer = setTimeout(poll, scanActive ? POLL_RUNNING_MS : POLL_IDLE_MS)
}

export function cancelPoll(): void {
  if (timer) clearTimeout(timer)
  timer = null
}
