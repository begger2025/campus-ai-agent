/**
 * api/posts.js — 帖子相关接口
 * 对应后端 GET /posts?page=1&page_size=20
 */
import axios from 'axios'

const http = axios.create({
  baseURL: '/',
  timeout: 5000,
})

/**
 * 获取帖子列表
 * @param {number} page       - 页码，从 1 开始
 * @param {number} pageSize   - 每页条数，最大 100
 * @returns {Promise<{ items: Array, total: number }>}
 */
export async function fetchPosts(page = 1, pageSize = 20) {
  const resp = await http.get('/posts', {
    params: { page, page_size: pageSize },
  })
  // 后端返回格式: { code: 0, data: { items: [], total: N } }
  const { data } = resp
  if (data?.code === 0 && data?.data) {
    return data.data
  }
  // 兼容直接返回 items 的格式
  if (Array.isArray(data?.items)) {
    return data
  }
  throw new Error('接口返回格式异常')
}

/**
 * 健康检查
 */
export async function checkHealth() {
  const resp = await http.get('/health')
  return resp.data
}
