export type Waiting = { name: string; state: 'approval' | 'your_turn'; idleS: number }
export type Band = { waiting: Waiting[]; error: string | null }

declare module 'claude-code' {
  interface PluginState {
    'session-band': { band: Band }
  }
}
