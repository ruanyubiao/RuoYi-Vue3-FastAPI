/**
 * 虚拟摇杆：方形 / 圆形两种行程。
 * 方形（square）：两轴独立限幅，对角可同时满量程，对齐云台方位/俯仰。
 * 圆形（circle）：圆限幅，对角满行程约 0.707，对齐实物游戏手柄。
 * 屏幕坐标原点在盘心，x 向右、y 向下。
 * 右 → 方位>0，左 → 方位<0，上 → 俯仰>0，下 → 俯仰<0。
 */
export const JOYSTICK_PAD = 400
export const JOYSTICK_KNOB = 108
/** 每轴最大位移，旋钮不越出 400 底盘。 */
export const JOYSTICK_MAX_THROW = (JOYSTICK_PAD - JOYSTICK_KNOB) / 2
export const JOYSTICK_DEADZONE = 0.12
export const JOYSTICK_MAX_SPEED = 10
export const JOYSTICK_HZ = 20
export const JOYSTICK_INTERVAL_MS = 1000 / JOYSTICK_HZ

export const JOYSTICK_TRAVEL_SQUARE = 'square'
export const JOYSTICK_TRAVEL_CIRCLE = 'circle'

export function normalizeTravel(travel) {
  return travel === JOYSTICK_TRAVEL_CIRCLE
    ? JOYSTICK_TRAVEL_CIRCLE
    : JOYSTICK_TRAVEL_SQUARE
}

export function quantizeSpeed(v, maxSpeed = JOYSTICK_MAX_SPEED) {
  const n = Math.round(Number(v) * 1000) / 1000
  if (!Number.isFinite(n)) return 0
  const cap = Number(maxSpeed)
  const lim = Number.isFinite(cap) && cap > 0 ? cap : JOYSTICK_MAX_SPEED
  if (n > lim) return lim
  if (n < -lim) return -lim
  return n === 0 ? 0 : n
}

export function clampAxis(v, maxThrow = JOYSTICK_MAX_THROW) {
  const limit = Number(maxThrow) > 0 ? Number(maxThrow) : JOYSTICK_MAX_THROW
  const n = Number(v) || 0
  if (n > limit) return limit
  if (n < -limit) return -limit
  return n
}

export function clampStick(
  dx,
  dy,
  maxThrow = JOYSTICK_MAX_THROW,
  travel = JOYSTICK_TRAVEL_SQUARE
) {
  const limit = Number(maxThrow) > 0 ? Number(maxThrow) : JOYSTICK_MAX_THROW
  const x = Number(dx) || 0
  const y = Number(dy) || 0
  if (normalizeTravel(travel) === JOYSTICK_TRAVEL_CIRCLE) {
    const h = Math.hypot(x, y)
    if (h <= limit || h === 0) return { x, y }
    const s = limit / h
    return { x: x * s, y: y * s }
  }
  return { x: clampAxis(x, limit), y: clampAxis(y, limit) }
}

function axisUnit(delta, maxThrow, deadzone) {
  const ad = Math.abs(delta)
  const dz = Math.max(0, Math.min(0.9, Number(deadzone) || 0)) * maxThrow
  if (ad <= dz) return 0
  const usable = maxThrow - dz
  if (usable <= 0) return 0
  const u = Math.min(1, (ad - dz) / usable)
  return delta < 0 ? -u : u
}

function radialUnit(pos, maxThrow, deadzone) {
  const h = Math.hypot(pos.x, pos.y)
  const dz = Math.max(0, Math.min(0.9, Number(deadzone) || 0)) * maxThrow
  if (h <= dz || h === 0) return { ux: 0, uy: 0 }
  const usable = maxThrow - dz
  if (usable <= 0) return { ux: 0, uy: 0 }
  const mag = Math.min(1, (h - dz) / usable)
  return { ux: (pos.x / h) * mag, uy: (pos.y / h) * mag }
}

/**
 * 指针位移 → 角速度。
 * @returns {{ x: number, y: number, az: number, el: number }}
 */
export function pointerToSpeed(
  dx,
  dy,
  {
    maxThrow = JOYSTICK_MAX_THROW,
    deadzone = JOYSTICK_DEADZONE,
    maxSpeed = JOYSTICK_MAX_SPEED,
    travel = JOYSTICK_TRAVEL_SQUARE
  } = {}
) {
  const gate = normalizeTravel(travel)
  const pos = clampStick(dx, dy, maxThrow, gate)
  let ux
  let uy
  if (gate === JOYSTICK_TRAVEL_CIRCLE) {
    const u = radialUnit(pos, maxThrow, deadzone)
    ux = u.ux
    uy = u.uy
  } else {
    ux = axisUnit(pos.x, maxThrow, deadzone)
    uy = axisUnit(pos.y, maxThrow, deadzone)
  }
  return {
    x: pos.x,
    y: pos.y,
    az: quantizeSpeed(ux * maxSpeed, maxSpeed),
    el: quantizeSpeed(-uy * maxSpeed, maxSpeed)
  }
}

/** 角速度 → 旋钮像素位移（不走死区）。 */
export function speedToStick(
  az,
  el,
  {
    maxThrow = JOYSTICK_MAX_THROW,
    maxSpeed = JOYSTICK_MAX_SPEED,
    travel = JOYSTICK_TRAVEL_SQUARE
  } = {}
) {
  const cap = Number(maxSpeed) > 0 ? Number(maxSpeed) : JOYSTICK_MAX_SPEED
  const nx = quantizeSpeed(az, cap) / cap
  const ny = -quantizeSpeed(el, cap) / cap
  return clampStick(nx * maxThrow, ny * maxThrow, maxThrow, travel)
}
