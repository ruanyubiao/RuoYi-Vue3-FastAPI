import { describe, expect, it } from 'vitest'
import {
  JOYSTICK_MAX_SPEED,
  JOYSTICK_MAX_THROW,
  clampStick,
  pointerToSpeed,
  quantizeSpeed,
  speedToStick
} from '@/utils/virtualJoystick'

describe('virtualJoystick', () => {
  it('quantizeSpeed 按 0.001 收口并限幅', () => {
    expect(quantizeSpeed(1.23456)).toBe(1.235)
    expect(quantizeSpeed(99)).toBe(JOYSTICK_MAX_SPEED)
    expect(quantizeSpeed(-99)).toBe(-JOYSTICK_MAX_SPEED)
    expect(quantizeSpeed('nope')).toBe(0)
  })

  it('clampStick 圆限幅', () => {
    const p = clampStick(300, 0, 100)
    expect(p.x).toBeCloseTo(100)
    expect(p.y).toBeCloseTo(0)
    const d = clampStick(80, 80, 100)
    expect(Math.hypot(d.x, d.y)).toBeCloseTo(100)
  })

  it('右正方位、上正俯仰、中心死区为 0', () => {
    const z = pointerToSpeed(0, 0)
    expect(z.az).toBe(0)
    expect(z.el).toBe(0)
    expect(pointerToSpeed(8, 0).az).toBe(0)
    const r = pointerToSpeed(JOYSTICK_MAX_THROW, 0)
    expect(r.az).toBe(JOYSTICK_MAX_SPEED)
    expect(r.el).toBe(0)
    const l = pointerToSpeed(-JOYSTICK_MAX_THROW, 0)
    expect(l.az).toBe(-JOYSTICK_MAX_SPEED)
    const u = pointerToSpeed(0, -JOYSTICK_MAX_THROW)
    expect(u.el).toBe(JOYSTICK_MAX_SPEED)
    expect(u.az).toBe(0)
    const dn = pointerToSpeed(0, JOYSTICK_MAX_THROW)
    expect(dn.el).toBe(-JOYSTICK_MAX_SPEED)
  })

  it('斜向同时给出方位和俯仰', () => {
    const p = pointerToSpeed(JOYSTICK_MAX_THROW, -JOYSTICK_MAX_THROW)
    expect(p.az).toBeGreaterThan(0)
    expect(p.el).toBeGreaterThan(0)
    expect(Math.abs(p.az - p.el)).toBeLessThan(0.002)
  })

  it('speedToStick 与满行程互逆', () => {
    const s = speedToStick(JOYSTICK_MAX_SPEED, 0)
    expect(s.x).toBeCloseTo(JOYSTICK_MAX_THROW)
    expect(s.y).toBeCloseTo(0)
    const up = speedToStick(0, JOYSTICK_MAX_SPEED)
    expect(up.y).toBeCloseTo(-JOYSTICK_MAX_THROW)
  })
})
