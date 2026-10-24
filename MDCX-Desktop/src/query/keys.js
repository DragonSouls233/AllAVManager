/* 全站查询键的唯一声明处。
 *
 * 键在这里集中定义的理由和 peach 一样：Application 层（store）和页面层必须读同一份缓存，
 * 谁都不许自己拼 key —— 一旦两处拼法不一致，失效就失效不掉，症状是「后台任务跑完了但页面还是旧数字」。
 *
 * 命名规则：第一个元素永远是模块名（pornhub / jav / system / …），
 * 这样 `queryKeys.pornhub.root` 就能一次性失效整个模块，不用逐个列举。 */

export const queryKeys = {
  pornhub: {
    root: ['pornhub'],
    /** 影片列表的**前缀**：失效它等于失效所有翻页/筛选组合。 */
    moviesRoot: ['pornhub', 'movies'],
    /** 影片列表。params 参与键的一部分：翻页/筛选/排序变了就是另一条查询。 */
    movies: (params) => ['pornhub', 'movies', params],
    /** 影片库统计（待刮削角标）。与列表分开，因为它要独立轮询，不能连带翻页列表一起重取。 */
    stats: ['pornhub', 'stats'],
    /** 演员列表的**前缀**。 */
    actorsRoot: ['pornhub', 'actors'],
    /** 演员列表。 */
    actors: (params) => ['pornhub', 'actors', params],
    /** 影片详情。 */
    movie: (id) => ['pornhub', 'movie', id],
    /** 演员详情。 */
    actor: (id) => ['pornhub', 'actor', id],
  },

  jav: {
    root: ['jav'],
    moviesRoot: ['jav', 'movies'],
    movies: (params) => ['jav', 'movies', params],
    stats: ['jav', 'stats'],
  },

  system: {
    root: ['system'],
    /** 后端版本 / 连通性。 */
    version: ['system', 'version'],
    /** 媒体来源（NAS 盘符）健康状态，对应后端 /health/sources。 */
    sourceHealth: ['system', 'source-health'],
  },
}
