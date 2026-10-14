/** A memory shown beside an error and still waiting for its outcome. */
export type Pending = { id: number; shownAt: number }

declare module 'claude-code' {
  interface PluginState {
    'rfm-live': {
      /** Condition classes the bridge knows; empty until session.start. */
      classes: readonly string[]
      /** Classes that fired in this session's Bash output. */
      fired: readonly string[]
      /** Memories shown this session, decided or not (shown once each). */
      shown: readonly number[]
      /** Shown memories whose first acted-on command has not run yet. */
      pending: readonly Pending[]
      /** Session start, in seconds (the ledger's clock). */
      sessionStart: number
    }
  }
}
