import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createEventParser } from '../src/api.js'

test('SSE parser preserves split frames, Chinese text and CRLF', () => {
  const events = []
  const parser = createEventParser((event) => events.push(event))
  parser.push('event: delta\r\ndata: {"type":"delta","data":{"content":"你')
  assert.equal(events.length, 0)
  parser.push('好"}}\r\n\r')
  parser.push('\nevent: result\ndata: {"type":"result","data":\ndata: {"content":"你好"}}\n\n')
  assert.deepEqual(
    events.map((event) => event.type),
    ['delta', 'result'],
  )
  assert.equal(events[0].data.content, '你好')
})

test('SSE comments do not produce application events', () => {
  const events = []
  const parser = createEventParser((event) => events.push(event))
  parser.push(': heartbeat\n\nevent: error\ndata: {"type":"error","data":{"message":"失败"}}\n\n')
  assert.equal(events.length, 1)
  assert.equal(events[0].type, 'error')
})
