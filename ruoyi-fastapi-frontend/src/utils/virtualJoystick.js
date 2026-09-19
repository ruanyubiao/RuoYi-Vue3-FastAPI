/**
 * 虚拟摇杆：游戏手柄式圆限幅 + 径向死区，映射方位/俯仰角速度。
 * 屏幕坐标原点在盘心，x 向右、y 向下。
 * 右 → 方位>0，左 → 方位<0，上 → 俯仰>0，下 → 俯仰<0。
 */
export const JOYSTICK_PAD = 400
export const JOYSTICK_KNOB = 108
/** 中心圆可移动半径，对齐 400 底盘外圈。 */
export const JOYSTICK_MAX_THROW = (JOYSTICK_PAD - JOYSTICK_KNOB) / 2
export const JOYSTICK_DEADZONE = 0.12
export const JOYSTICK_MAX_SPEED = 10
export const JOYSTICK_HZ = 20
export const JOYSTICK_INTERVAL_MS = 1000 / JOYSTICK_HZ

export function quantizeSpeed(v, maxSpeed = JOYSTICK_MAX_SPEED) {
  const n = Math.round(Number(v) * 1000) / 1000
  if (!Number.isFinite(n)) return 0
  const cap = Number(maxSpeed)
  const lim = Number.isFinite(cap) && cap > 0 ? cap : JOYSTICK_MAX_SPEED
  if (n > lim) return lim
  if (n < -lim) return -lim
  return n === 0 ? 0 : n
}

export function clampStick(dx, dy, maxThrow = JOYSTICK_MAX_THROW) {
  const limit = Number(maxThrow) > 0 ? Number(maxThrow) : JOYSTICK_MAX_THROW
  const mag = Math.hypot(dx, dy)
  if (!Number.isFinite(mag) || mag <= limit || mag === 0) {
    return { x: Number(dx) || 0, y: Number(dy) || 0 }
  }
  const s = limit / mag
  return { x: dx * s, y: dy * s }
}

/**
 * 指针位移 → 角速度。死区内输出 0；出死区后按剩余行程线性到满量程。
 * @returns {{ x: number, y: number, az: number, el: number }}
 */
export function pointerToSpeed(
  dx,
  dy,
  {
    maxThrow = JOYSTICK_MAX_THROW,
    deadzone = JOYSTICK_DEADZONE,
    maxSpeed = JOYSTICK_MAX_SPEED
  } = {}
) {
  const pos = clampStick(dx, dy, maxThrow)
  const mag = Math.hypot(pos.x, pos.y)
  const dz = Math.max(0, Math.min(0.9, Number(deadzone) || 0)) * maxThrow
  if (mag <= dz) {
    return { x: pos.x, y: pos.y, az: 0, el: 0 }
  }
  const usable = maxThrow - dz
  const scale = usable > 0 ? Math.min(1, (mag - dz) / usable) : 0
  const ux = (pos.x / mag) * scale
  const uy = (pos.y / mag) * scale
  return {
    x: pos.x,
    y: pos.y,
    az: quantizeSpeed(ux * maxSpeed, maxSpeed),
    el: quantizeSpeed(-uy * maxSpeed, maxSpeed)
  }
}

/** 角速度 → 旋钮像素位移（不走死区，便于手动输入回显）。 */
export function speedToStick(
  az,
  el,
  { maxThrow = JOYSTICK_MAX_THROW, maxSpeed = JOYSTICK_MAX_SPEED } = {}
) {
  const cap = Number(maxSpeed) > 0 ? Number(maxSpeed) : JOYSTICK_MAX_SPEED
  let nx = quantizeSpeed(az, cap) / cap
  let ny = -quantizeSpeed(el, cap) / cap
  const mag = Math.hypot(nx, ny)
  if (mag > 1) {
    nx /= mag
    ny /= mag
  }
  return { x: nx * maxThrow, y: ny * maxThrow }
}
