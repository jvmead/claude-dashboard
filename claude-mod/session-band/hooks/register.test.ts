import { expect, test } from 'claude-code/testing'

import { ago, waitingFrom } from './register'

const snap = (sessions: object[], error: string | null = null) => JSON.stringify({ error, sessions })

test('keeps other sessions that need you, drops self and busy ones', () => {
  const out = waitingFrom(snap([
    { session_id: 'a', name: 'api', state: 'approval', idle_s: 5 },
    { session_id: 'me', name: 'self', state: 'your_turn', idle_s: 5 },
    { session_id: 'b', name: 'nb', state: 'working', idle_s: 0 },
    { session_id: 'c', name: 'unity', state: 'your_turn', idle_s: 200 },
  ]), 'me')
  expect(out.map(w => w.name)).toEqual(['api', 'unity'])
})

test('a discovery error is raised, not hidden', () => {
  expect(() => waitingFrom(snap([], 'no sessions dir'), 'me')).toThrow('no sessions dir')
})

test('ago buckets', () => {
  expect([ago(5), ago(200), ago(7300)]).toEqual(['now', '3m', '2h'])
})
