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
