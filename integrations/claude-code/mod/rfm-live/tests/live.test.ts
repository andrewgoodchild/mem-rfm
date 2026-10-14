// The TypeScript side only: the bridge (mod_bridge.py) is answered here by a
// fake that keeps the bridge's contract; its own judgement is tested in
// integrations/claude-code/test_mod_bridge.py against a real store.
import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

const ERR = "ModuleNotFoundError: No module named 'pkg_resources'"
const FIX = 'PYTHONPATH=/tmp/shim python -m pytest'

type Req = { op: string; id?: number; command?: string; output?: string; fired?: string[] }

function fakeBridge(on: On, calls: Req[]) {
  on('process.run', ($, e) => {
    const req = JSON.parse(e.init?.stdin ?? '{}') as Req
    calls.push(req)
    const answer =
      req.op === 'classes' ? { classes: ['modulenotfounderror', 'pkg_resources'] }
      : req.op === 'match' ? {
          fired: ['modulenotfounderror', 'pkg_resources'],
          memories: [{ id: 1, content: `Use \`${FIX}\``, classes: ['pkg_resources'] }],
        }
      : req.command === FIX ? { acted: true, outcome: 1, recorded: true }
      : { acted: false, outcome: null, recorded: false }
    return { value: { exitCode: 0, stdout: JSON.stringify(answer), stderr: "", isStdoutTruncated: false, isStderrTruncated: false } }
  })
}

function fakeBash(on: On) {
  on('tool.call', { tool: 'Bash' }, ($, e) =>
    e.command === FIX
      ? { result: { stdout: '12 passed', stderr: '' }, text: '12 passed' }
      : e.command.startsWith('echo')
        ? { result: { stdout: 'hi', stderr: '' }, text: 'hi' }
        : { isError: true as const, result: undefined, text: ERR },
  )
}

test('error shows the memory once; the fix it drives is sent as an outcome', async ($, on) => {
  const calls: Req[] = []
  mock.clock(on)
  mock.env(on, {})
  fakeBridge(on, calls)
  fakeBash(on)

  const quiet = await $.tool.call({ tool: 'Bash', command: 'echo hi' })
  expect(quiet.context ?? []).toEqual([])
  expect(calls.some(c => c.op === 'match')).toBe(false)

  const failed = await $.tool.call({ tool: 'Bash', command: 'python -c "import xarray"' })
  expect((failed.context ?? []).join('\n')).toContain('#1:')

  const again = await $.tool.call({ tool: 'Bash', command: 'python -c "import xarray"' })
  expect(again.context ?? []).toEqual([])

  await $.tool.call({ tool: 'Bash', command: FIX })
  const sent = calls.filter(c => c.op === 'outcome')
  expect(sent.at(-1)?.command).toBe(FIX)
  expect(sent.at(-1)?.fired).toEqual(['modulenotfounderror', 'pkg_resources'])

  const after = calls.length
  await $.tool.call({ tool: 'Bash', command: FIX })
  expect(calls.slice(after).some(c => c.op === 'outcome')).toBe(false)
})
