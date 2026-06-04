/**
 * api/posts.js — 帖子相关接口
 * 对应后端 GET /api/posts?page=1&page_size=20
 */
import http from '@/api/http'

/**
 * 获取帖子列表
 * @param {number} page       - 页码，从 1 开始
 * @param {number} pageSize   - 每页条数，最大 100
 * @returns {Promise<{ items: Array, total: number, page: number, page_size: number }>}
 */
export async function fetchPosts(page = 1, pageSize = 20) {
  return http.get('/posts', {
    params: { page, page_size: pageSize },
  })
}

/**
 * 健康检查（走 /api/ping）
 */
export async function checkHealth() {
  return http.get('/ping')
}
