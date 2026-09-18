/**
 * 相机页写死的遥测字段号。改号必须同步遥测配置，并由 cameraTmFieldIds.test.js 锁住。
 * v1.6 / v1.7 页面共用这些 id。
 */

/** D8 慢遥分辨率：开窗模式、缓存图像大小 */
export const D8_RES_FIELD_IDS = ['CAM036', 'CAM038']

/** D9 快遥分辨率：开窗模式、缓存图像大小 */
export const D9_RES_FIELD_IDS = ['CAMF037', 'CAMF034']

/** D8 统计区 / 质心：坐标、过阈值、饱和、灰度、光斑能量 */
export const D8_STATS_FIELDS = {
  x: 'CAM004',
  y: 'CAM005',
  overTh: 'CAM006',
  sat: 'CAM007',
  gray: 'CAM008',
  energy: 'CAM010'
}

/** D9 统计区 / 质心，与 D8 一一对应 */
export const D9_STATS_FIELDS = {
  x: 'CAMF004',
  y: 'CAMF005',
  overTh: 'CAMF006',
  sat: 'CAMF007',
  gray: 'CAMF008',
  energy: 'CAMF010'
}
