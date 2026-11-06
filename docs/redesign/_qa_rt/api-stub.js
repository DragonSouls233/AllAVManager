export const __calls = { health: 0, dashboard: 0, tasks: 0, version: 0 }
export let __healthImpl = async () => ({})
export function __setHealth(fn) { __healthImpl = fn }
export const getSystemHealth = (...a) => { __calls.health++; return __healthImpl(...a) }
export const getDashboardStats = async () => { __calls.dashboard++; return { movies: { total: 10 } } }
export const getTaskStats = async () => { __calls.tasks++; return { status_distribution: { running: 1, success: 2 } } }
export const getVersion = async () => { __calls.version++; return { version: '9.9.9' } }
