import { describe, expect, it } from 'vitest'
import { convertBase, groupBinary, hexToNumberRows, numberToHex } from '@/utils/numconv'

describe('utils/numconv', () => {
  it('进制不超过 36 时大小写等价，输出大写', () => {
    expect(convertBase('10100101', 2, 16)).toBe('A5')
    expect(convertBase('A5', 16, 10)).toBe('165')
    expect(convertBase('a5', 16, 16)).toBe('A5')
    expect(convertBase('192654', 10, 8)).toBe('570216')
    expect(convertBase('42540766411283223938465490632011909384', 10, 16)).toBe('20010DB8000085A300000000AC1F8908')
  })

  it('二进制每 4 位插入空格', () => {
    expect(groupBinary('1100011')).toBe('110 0011')
    expect(groupBinary('11000110')).toBe('1100 0110')
    expect(groupBinary('1010')).toBe('1010')
    expect(groupBinary('0')).toBe('0')
  })

  it('37–64 进制区分大小写', () => {
    expect(convertBase('zz', 64, 10)).toBe('2275')
    expect(convertBase('a', 64, 10)).not.toBe(convertBase('A', 64, 10))
    expect(() => convertBase('-1', 10, 16)).toThrow(/不属于/)
  })

  it('数字转 HEX：范围、补码和浮点', () => {
    expect(numberToHex('-1', 'int8')).toMatchObject({ be: 'FF', le: 'FF' })
    expect(numberToHex('1', 'uint16')).toMatchObject({ be: '00 01', le: '01 00' })
    expect(numberToHex('-1', 'int24').be).toBe('FF FF FF')
    expect(numberToHex('128', 'int8').error).toMatch(/范围/)
    expect(numberToHex('-1', 'uint16').error).toMatch(/范围/)
    expect(numberToHex('1.5', 'int16').error).toMatch(/整数/)
    expect(numberToHex('1', 'float')).toMatchObject({ be: '3F 80 00 00', le: '00 00 80 3F' })
    expect(numberToHex('-0', 'float').be).toBe('80 00 00 00')
    expect(numberToHex('1.5e-3', 'double').error).toBeUndefined()
    expect(numberToHex('NaN', 'float').error).toBeTruthy()
    expect(numberToHex('Infinity', 'double').error).toBeTruthy()
  })

  it('HEX 转数字：只取前面的字节，不够再补零', () => {
    const rows = hexToNumberRows('AA BB', { padTail: true, endian: 'be' }).rows
    expect(rows.find(row => row.type === 'int8')).toMatchObject({ result: '-86', be: 'AA', le: 'AA' })
    expect(rows.find(row => row.type === 'uint16')).toMatchObject({ result: '43707', be: 'AA BB', le: 'BB AA' })
    const le = hexToNumberRows('AA BB', { padTail: true, endian: 'le' }).rows.find(row => row.type === 'uint16')
    expect(le).toMatchObject({ result: '48042', be: 'AA BB', le: 'BB AA' })
    const short = hexToNumberRows('01', { padTail: true, endian: 'be' }).rows.find(row => row.type === 'uint16')
    expect(short).toMatchObject({ result: '256', be: '01 00', le: '00 01' })
    const head = hexToNumberRows('01', { padTail: false, endian: 'be' }).rows.find(row => row.type === 'uint16')
    expect(head).toMatchObject({ result: '1', be: '00 01', le: '01 00' })
    expect(hexToNumberRows('01 02 03 04 05 06 07 08 09').error).toBe('超过8字节')
    const f = hexToNumberRows('3F 80 00 00', { padTail: true, endian: 'be' }).rows.find(row => row.type === 'float')
    expect(f.result).toBe('1')
  })
})
