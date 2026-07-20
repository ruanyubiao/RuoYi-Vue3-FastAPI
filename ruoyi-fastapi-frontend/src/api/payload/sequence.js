import request from '@/utils/request'

// 查询指令序列列表
export function listSequence(query) {
  return request({
    url: '/payload/sequence/list',
    method: 'get',
    params: query
  })
}

// 查询指令序列详细
export function getSequence(seqId) {
  return request({
    url: '/payload/sequence/' + seqId,
    method: 'get'
  })
}

// 新增指令序列
export function addSequence(data) {
  return request({
    url: '/payload/sequence',
    method: 'post',
    data: data
  })
}

// 修改指令序列
export function updateSequence(data) {
  return request({
    url: '/payload/sequence',
    method: 'put',
    data: data
  })
}

// 删除指令序列
export function delSequence(seqId) {
  return request({
    url: '/payload/sequence/' + seqId,
    method: 'delete'
  })
}

// 复制指令序列
export function copySequence(seqId) {
  return request({
    url: '/payload/sequence/' + seqId + '/copy',
    method: 'post'
  })
}

// 启动执行指令序列（异步，返回 runId）
export function runSequence(seqId, data) {
  return request({
    url: '/payload/sequence/' + seqId + '/run',
    method: 'post',
    data
  })
}

// 查询执行进度/详情
export function getSequenceRun(runId) {
  return request({
    url: '/payload/sequence/run/' + runId,
    method: 'get'
  })
}

// 查询序列执行历史
export function listSequenceRuns(seqId, limit = 30) {
  return request({
    url: '/payload/sequence/' + seqId + '/runs',
    method: 'get',
    params: { limit }
  })
}
