import { isScanActive } from '@/application'
import { createAppThunk } from '../createAppThunk'
import { openCurrentDevice } from '../inventory/inventory.thunks'
import { SESSION_MESSAGES } from './session.messages'
import { cancelPoll, schedulePoll } from './session.poller'
import { selectCurrentDeviceKey } from './session.selectors'
import { sessionActions } from './sessionSlice'

/** Lee el estado; al terminar un análisis o identificarse el equipo, abre su último inventario. */
export const pollStatus = createAppThunk(
  'session/poll',
  async (_: undefined, { dispatch, getState, extra }) => {
    const before = getState()
    const result = await extra.useCases.session.readStatus()
    if (!result.ok) {
      cancelPoll()
      dispatch(
        sessionActions.stopped(
          result.reason === 'session_lost'
            ? SESSION_MESSAGES.sessionLost
            : SESSION_MESSAGES.serviceStopped,
        ),
      )
      return
    }
    dispatch(sessionActions.statusReceived(result.status))
    const finished =
      result.status.scan.state === 'finished' &&
      before.session.status?.scan.state !== 'finished'
    if (
      finished ||
      selectCurrentDeviceKey(before) !== selectCurrentDeviceKey(getState())
    )
      await dispatch(openCurrentDevice())
  },
)

export const watchStatus = createAppThunk(
  'session/watch',
  async (_: undefined, { dispatch, getState }) => {
    await dispatch(pollStatus())
    const { session } = getState()
    if (!session.stopped) {
      schedulePoll(
        isScanActive(session.status?.scan),
        () => void dispatch(watchStatus()),
      )
    }
  },
)

let sessionStarted = false

// Una sola vez por pestaña, aunque React monte dos veces en desarrollo.
export const startSession = createAppThunk(
  'session/start',
  async (_: undefined, { dispatch, extra }) => {
    sessionStarted = true
    try {
      dispatch(sessionActions.started(await extra.useCases.session.start()))
      await dispatch(openCurrentDevice())
    } catch {
      dispatch(sessionActions.stopped(SESSION_MESSAGES.startFailed))
      return
    }
    dispatch(sessionActions.ready())
    await dispatch(watchStatus())
  },
  { condition: () => !sessionStarted },
)

export const startScan = createAppThunk(
  'session/startScan',
  async (_: undefined, { dispatch, extra }) => {
    const result = await extra.useCases.session.startScan()
    const message = result.ok
      ? null
      : result.reason === 'already_running'
        ? SESSION_MESSAGES.scanAlreadyRunning
        : SESSION_MESSAGES.scanFailed
    dispatch(sessionActions.messageShown(message))
    await dispatch(watchStatus())
  },
)

export const cancelScan = createAppThunk(
  'session/cancelScan',
  async (_: undefined, { dispatch, extra }) => {
    await extra.useCases.session.cancelScan()
    await dispatch(pollStatus())
  },
)

export const elevate = createAppThunk(
  'session/elevate',
  async (_: undefined, { dispatch, extra }) => {
    dispatch(sessionActions.messageShown(SESSION_MESSAGES.confirmElevation))
    const result = await extra.useCases.session.elevate()
    if (!result.ok) {
      dispatch(
        sessionActions.messageShown(
          result.reason === 'cancelled'
            ? SESSION_MESSAGES.elevationCancelled
            : SESSION_MESSAGES.elevationFailed,
        ),
      )
      return
    }
    cancelPoll()
    dispatch(sessionActions.messageShown(null))
    dispatch(sessionActions.stopped(SESSION_MESSAGES.restartingElevated))
  },
)

export const exitApp = createAppThunk(
  'session/exit',
  async (_: undefined, { dispatch, extra }) => {
    await extra.useCases.session.exit()
    cancelPoll()
    dispatch(sessionActions.stopped(SESSION_MESSAGES.serviceStopped))
  },
)

export const openFolder = createAppThunk(
  'session/openFolder',
  async (path: string | undefined, { extra }) => {
    await extra.useCases.session.openFolder(path)
  },
)
