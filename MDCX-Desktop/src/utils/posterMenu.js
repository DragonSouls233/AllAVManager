import { reactive } from 'vue'

/**
 * 海报右键上下文菜单的全局状态。
 * PosterCard 在右键时调用 showPosterMenu 写入当前影片；
 * CinemaLayout 中挂载唯一一个 <PosterContextMenu/> 读取本状态渲染菜单。
 * 这样无需在每个网格页里都写一遍菜单逻辑。
 */
export const posterMenuState = reactive({
  visible: false,
  x: 0,
  y: 0,
  movie: null,
  module: ''
})

export function showPosterMenu(e, movie, module) {
  posterMenuState.x = e.clientX
  posterMenuState.y = e.clientY
  posterMenuState.movie = movie
  posterMenuState.module = module || ''
  posterMenuState.visible = true
}

export function hidePosterMenu() {
  posterMenuState.visible = false
  posterMenuState.movie = null
}

export function togglePosterMenu(e, movie, module) {
  if (posterMenuState.visible && posterMenuState.movie === movie) {
    hidePosterMenu()
  } else {
    showPosterMenu(e, movie, module)
  }
}

/** 从影片对象推断所属模块（菜单里调用后端标记/播放用） */
export function moduleOf(movie, fallback = '') {
  return (movie && (movie.module_name || movie.module_type)) || fallback || ''
}
