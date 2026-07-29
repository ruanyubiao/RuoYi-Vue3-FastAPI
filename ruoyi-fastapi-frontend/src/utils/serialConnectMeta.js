/** @deprecated 请使用 @/utils/deviceSnapshotCache；此处保留兼容导出 */
export {
  prefetchDeviceSnapshot,
  takeDeviceSnapshot,
  saveDeviceSnapshot,
  invalidateDeviceSnapshot,
  prefetchSerialConnectMeta,
  takeSerialConnectMeta,
  setActiveDevice,
  getActiveDevice,
  clearActiveDevice,
  SNAPSHOT_TTL_MS,
  ACTIVE_DEVICE_TTL_MS
} from '@/utils/deviceSnapshotCache'
