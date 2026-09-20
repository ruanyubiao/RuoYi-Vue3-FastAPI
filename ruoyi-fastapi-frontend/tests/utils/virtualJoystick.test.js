import { describe, expect, it } from 'vitest'
import {
  JOYSTICK_MAX_SPEED,
  JOYSTICK_MAX_THROW,
  JOYSTICK_TRAVEL_CIRCLE,
  JOYSTICK_TRAVEL_SQUARE,
  clampStick,
  pointerToSpeed,
  quantizeSpeed,
  speedToStick
} from '@/utils/virtualJoystick'

const square = { travel: JOYSTICK_TRAVEL_SQUARE }
const circle = { travel: JOYSTICK_TRAVEL_CIRCLE }

describe('virtualJoystick', () => {
  it('quantizeSpeed 按 0.001 收口并限幅', () => {
    expect(quantizeSpeed(1.23456)).toBe(1.235)
    expect(quantizeSpeed(99)).toBe(JOYSTICK_MAX_SPEED)
    expect(quantizeSpeed(-99)).toBe(-JOYSTICK_MAX_SPEED)
    expect(quantizeSpeed('nope')).toBe(0)
  })

  it('clampStick 方形限幅，对角可同时满轴', () => {
    const p = clampStick(300, 0, 100, JOYSTICK_TRAVEL_SQUARE)
    expect(p.x).toBe(100)
    expect(p.y).toBe(0)
    const d = clampStick(80, 80, 100, JOYSTICK_TRAVEL_SQUARE)
    expect(d).toEqual({ x: 80, y: 80 })
    const corner = clampStick(300, -300, 100, JOYSTICK_TRAVEL_SQUARE)
    expect(corner).toEqual({ x: 100, y: -100 })
  })

  it('clampStick 圆形限幅，对角压到圆周', () => {
    const p = clampStick(300, 0, 100, JOYSTICK_TRAVEL_CIRCLE)
    expect(p.x).toBe(100)
    expect(p.y).toBe(0)
    const inside = clampStick(60, 60, 100, JOYSTICK_TRAVEL_CIRCLE)
    expect(inside).toEqual({ x: 60, y: 60 })
    const rim = clampStick(300, -300, 100, JOYSTICK_TRAVEL_CIRCLE)
    expect(Math.hypot(rim.x, rim.y)).toBeCloseTo(100)
    expect(rim.x).toBeCloseTo(100 / Math.SQRT2)
    expect(rim.y).toBeCloseTo(-100 / Math.SQRT2)
  })

  it('右正方位、上正俯仰、中心死区为 0', () => {
    const z = pointerToSpeed(0, 0, square)
    expect(z.az).toBe(0)
    expect(z.el).toBe(0)
    expect(pointerToSpeed(8, 0, square).az).toBe(0)
    expect(pointerToSpeed(8, 0, circle).az).toBe(0)
    const r = pointerToSpeed(JOYSTICK_MAX_THROW, 0, square)
    expect(r.az).toBe(JOYSTICK_MAX_SPEED)
    expect(r.el).toBe(0)
    const l = pointerToSpeed(-JOYSTICK_MAX_THROW, 0, square)
    expect(l.az).toBe(-JOYSTICK_MAX_SPEED)
    const u = pointerToSpeed(0, -JOYSTICK_MAX_THROW, square)
    expect(u.el).toBe(JOYSTICK_MAX_SPEED)
    expect(u.az).toBe(0)
    const dn = pointerToSpeed(0, JOYSTICK_MAX_THROW, square)
    expect(dn.el).toBe(-JOYSTICK_MAX_SPEED)
  })

  it('方形斜向满行程同时给出方位 10 和俯仰 10', () => {
    const p = pointerToSpeed(JOYSTICK_MAX_THROW, -JOYSTICK_MAX_THROW, square)
    expect(p.az).toBe(JOYSTICK_MAX_SPEED)
    expect(p.el).toBe(JOYSTICK_MAX_SPEED)
  })

  it('圆形斜向满行程约 0.707 满量程', () => {
    const p = pointerToSpeed(JOYSTICK_MAX_THROW, -JOYSTICK_MAX_THROW, circle)
    const half = JOYSTICK_MAX_SPEED / Math.SQRT2
    expect(p.az).toBeCloseTo(half, 2)
    expect(p.el).toBeCloseTo(half, 2)
    expect(Math.hypot(p.x, p.y)).toBeCloseTo(JOYSTICK_MAX_THROW)
  })

  it('speedToStick 方形与满行程互逆，含 (10,10) 角点', () => {
    const s = speedToStick(JOYSTICK_MAX_SPEED, 0, square)
    expect(s.x).toBeCloseTo(JOYSTICK_MAX_THROW)
    expect(s.y).toBeCloseTo(0)
    const up = speedToStick(0, JOYSTICK_MAX_SPEED, square)
    expect(up.y).toBeCloseTo(-JOYSTICK_MAX_THROW)
    const corner = speedToStick(JOYSTICK_MAX_SPEED, JOYSTICK_MAX_SPEED, square)
    expect(corner.x).toBeCloseTo(JOYSTICK_MAX_THROW)
    expect(corner.y).toBeCloseTo(-JOYSTICK_MAX_THROW)
    const back = pointerToSpeed(corner.x, corner.y, square)
    expect(back.az).toBe(JOYSTICK_MAX_SPEED)
    expect(back.el).toBe(JOYSTICK_MAX_SPEED)
  })

  it('speedToStick 圆形把 (10,10) 压到圆周', () => {
    const rim = speedToStick(JOYSTICK_MAX_SPEED, JOYSTICK_MAX_SPEED, circle)
    expect(Math.hypot(rim.x, rim.y)).toBeCloseTo(JOYSTICK_MAX_THROW)
    expect(rim.x).toBeCloseTo(JOYSTICK_MAX_THROW / Math.SQRT2)
    expect(rim.y).toBeCloseTo(-JOYSTICK_MAX_THROW / Math.SQRT2)
  })
})
