import { api } from './index'

/** 获取无码影片列表 */
export async function getUncensoredMovies(params = {}) {
  return api.get('/uncensored/movies', { params })
}

/** 获取无码影片详情 */
export async function getUncensoredMovie(id) {
  return api.get(`/uncensored/movies/${id}`)
}
