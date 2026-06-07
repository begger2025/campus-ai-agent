import http from './http'

export async function fetchPosts(page = 1, pageSize = 20) {
  const data = await http.get('/posts', {
    params: { page, page_size: pageSize },
  })

  if (Array.isArray(data?.items)) {
    return data
  }

  throw new Error('Invalid posts API response')
}

export async function checkHealth() {
  return http.get('/ping')
}
