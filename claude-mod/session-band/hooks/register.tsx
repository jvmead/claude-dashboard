import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { Band, Waiting } from '../types'

// ~/projects/claude-dashboard: `python -m dashboard --json` prints the live sessions.
const PYTHON = '/home/jvmead/anaconda3/bin/python'
const DASHBOARD_DIR = '/home/jvmead/projects/claude-dashboard'
const POLL_MS = 5000
const NEEDS_YOU = new Set(['approval', 'your_turn'])

const band = atom({ plugin: 'session-band', key: 'band' } as const, { waiting: [], error: null })

type Row = { session_id: string; name: string; state: string; idle_s: number }

// Rows of other sessions that need you; throws on anything unexpected so the band shows it.
export function waitingFrom(stdout: string, selfId: string): Waiting[] {
  const snap = JSON.parse(stdout) as { error: string | null; sessions: Row[] }
  if (snap.error) throw new Error(snap.error)
  return snap.sessions
    .filter(r => NEEDS_YOU.has(r.state) && r.session_id !== selfId)
    .map(r => ({ name: r.name, state: r.state as Waiting['state'], idleS: r.idle_s }))
}

export function ago(s: number): string {
  if (s < 60) return 'now'
  if (s < 3600) return `${Math.floor(s / 60)}m`
  return `${Math.floor(s / 3600)}h`
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const selfId = await $.session.id()
    let inFlight = false
    const poll = async () => {
      if (inFlight) return
      inFlight = true
      let fresh: Band
      try {
        const { exitCode, stdout, stderr } = await $.process.run(
          [PYTHON, '-m', 'dashboard', '--json'],
          { cwd: DASHBOARD_DIR, timeoutMs: 15000 },
        )
        if (exitCode !== 0) throw new Error(stderr.trim().split('\n').pop() || `exit ${exitCode}`)
        fresh = { waiting: waitingFrom(stdout, selfId), error: null }
      } catch (err) {
        fresh = { waiting: [], error: String(err).slice(0, 120) }
      } finally {
        inFlight = false
      }
      await update($, band, () => fresh)
    }
    void poll()
    $.clock.every(POLL_MS, () => void poll())

    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const { waiting, error } = await read($, band)
    if (e.props.hasSurvey || (waiting.length === 0 && error === null)) return next(e)

    const { Box, Text } = $.ui.resolve(e)
    if (error !== null) {
      return (
        <Box>
          <Text dimColor>session-band: {error}</Text>
        </Box>
      )
    }
    return (
      <Box>
        {waiting.map((w, i) => (
          <Text key={w.name + i}>
            {i > 0 ? '  ·  ' : ''}
            {w.state === 'approval' ? '🟥 ' : '🟨 '}
            <Text bold={w.state === 'approval'}>{w.name}</Text>
            <Text dimColor>{w.state === 'approval' ? ' needs approval' : ` your turn ${ago(w.idleS)}`}</Text>
          </Text>
        ))}
      </Box>
    )
  })
}
