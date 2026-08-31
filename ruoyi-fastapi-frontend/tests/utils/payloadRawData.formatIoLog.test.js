import { describe, expect, it } from 'vitest'
import { formatIoLogParts } from '@/utils/payloadRawData'

describe('payloadRawData formatIoLogParts', () => {
  it('默认 HEX 行', () => {
    const { header, body, dir } = formatIoLogParts({
      ts: '12:00:00',
      dir: 'recv',
      hex: 'aa bb'
    })
    expect(dir).toBe('RECV')
    expect(header).toContain('RECV')
    expect(header).toContain('HEX/2')
    expect(body).toBe('AA BB')
  })

  it('带 peer 与 frameId', () => {
    const { header, body } = formatIoLogParts(
      { ts: '1', dir: 'send', hex: '01', peer: '192.168.1.1:9000', frameIdHex: '18FF00' },
      { style: 'udp' }
    )
    expect(header).toContain('to 192.168.1.1:9000')
    expect(body).toContain('18 FF 00 : 01')
  })
})
