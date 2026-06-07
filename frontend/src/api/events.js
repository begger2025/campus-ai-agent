import http from './http'
import { mockPublishedEvents } from '@/mock/events'

export async function fetchPublishedEvents() {
  try {
    const data = await http.get('/events', {
      params: { status: 'published', page: 1, page_size: 100 },
    })

    if (Array.isArray(data)) {
      return data
    }
    if (Array.isArray(data?.items)) {
      return data.items
    }

    throw new Error('Invalid events API response')
  } catch {
    console.warn('[api/events] backend unavailable, using mock data')
    return [...mockPublishedEvents]
  }
}
