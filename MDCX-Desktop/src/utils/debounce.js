/**
 * 通用防抖工具。
 * 返回的函数在最后一次调用后 wait 毫秒才真正执行；多次调用会重置计时器。
 * 附带 .cancel() 可主动取消挂起的调用。
 */
export function debounce(fn, wait = 300) {
  let timer = null
  const debounced = function (...args) {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      timer = null
      fn.apply(this, args)
    }, wait)
  }
  debounced.cancel = () => {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }
  return debounced
}
