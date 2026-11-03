import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createEventParser } from '../src/api.js'

test('SSE parser preserves split frames, Chinese text, CRLF and event ids', () => {
  const frames = []
  const parser = createEventParser((frame) => frames.push(frame))
  parser.push('id: 3\r\nevent: delta\r\ndata: {"seq":3,"type":"delta","data":{"content":"你')
  assert.equal(frames.length, 0)
  parser.push('好"}}\r\n\r')
  parser.push(
    '\nid: 4\nevent: result\ndata: {"seq":4,"type":"result","data":\ndata: {"content":"你好"}}\n\n',
  )
  assert.deepEqual(
    frames.map((frame) => frame.event),
    ['delta', 'result'],
  )
  assert.deepEqual(
    frames.map((frame) => frame.id),
    ['3', '4'],
  )
  assert.equal(frames[0].data.seq, 3)
  assert.equal(frames[0].data.data.content, '你好')
})

test('SSE comments do not produce application events', () => {
  const frames = []
  const parser = createEventParser((frame) => frames.push(frame))
  parser.push(
    ': heartbeat\n\nevent: error\ndata: {"type":"error","data":{"message":"失败"}}\n\n',
  )
  assert.equal(frames.length, 1)
  assert.equal(frames[0].event, 'error')
  assert.equal(frames[0].id, null)
  assert.equal(frames[0].data.data.message, '失败')
})
