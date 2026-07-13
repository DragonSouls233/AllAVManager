import { api } from './index'

/** 获取 PORNHub 影片列表 */
export async function getPornhubMovies(params = {}) {
  return api.get('/pornhub/movies', { params })
}

/** 获取 PORNHub 影片详情 */
export async function getPornhubMovie(id) {
  return api.get(`/pornhub/movies/${id}`)
}
