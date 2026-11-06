/* QA 独立验证脚本 · 只读，不修改 src
 * 用法: node docs/redesign/_qa_verify.mjs
 */
import fs from 'node:fs'
import path from 'node:path'

const ROOT = path.resolve('G:/MDCX/MDCX-Desktop')
const SRC = path.join(ROOT, 'src')

function read(p) {
  return fs.readFileSync(p, 'utf8')
}

/* ---------- 路由解析 ---------- */
function parseRoutes(src) {
  // 粗粒度：把 /^\s*\{ ... \}/ 拆成块，逐字段抓取
  const lines = src.split('\n')
  const out = []
  let depth = 0
  let stack = []       // 每层: {path, name, isChild}
  let cur = null

  for (const raw of lines) {
    const line = raw.replace(/\/\/.*$/, '')
    const open = (line.match(/\{/g) || []).length
    const close = (line.match(/\}/g) || []).length

    const p = line.match(/path:\s*'([^']*)'/)
    const n = line.match(/name:\s*'([^']*)'/)
    const r = line.match(/redirect:\s*'([^']*)'/)
    const c = line.match(/component:\s*(?:\(\)\s*=>\s*)?import\('([^']+)'\)/) ||
              line.match(/component:\s*([A-Za-z_$][\w$]*)/)

    if (open > close || p || n || r) {
      // 新对象开始（可能同一行）
    }
    if (p || n || r || c) {
      if (!cur || open > 0) cur = cur || {}
      if (p) cur.path = p[1]
      if (n) cur.name = n[1]
      if (r) cur.redirect = r[1]
      if (c) cur.component = c[1]
    }
    if (close > 0 && cur) {
      if (cur.path !== undefined) out.push(cur)
      cur = null
    }
  }
  return out
}

/* 更稳的方案：用 acorn? 没装。改用逐字符扫描 + 只抓 path/name/redirect/component */
function parseRoutes2(src) {
  const start = src.indexOf('export const routes')
  const body = src.slice(start)
  // 用大括号配对切出所有最内层/任意层对象
  const objs = []
  const stack = []
  for (let i = 0; i < body.length; i++) {
    const ch = body[i]
    if (ch === '{') {
      stack.push(i)
    } else if (ch === '}') {
      const s = stack.pop()
      if (s !== undefined) objs.push(body.slice(s, i + 1))
    }
  }
  const routeObjs = []
  for (const o of objs) {
    const p = o.match(/path:\s*'([^']*)'/)
    if (!p) continue
    // 只保留浅层对象（不含嵌套 path: 的）
    if ((o.match(/path:\s*'/g) || []).length > 1) continue
    const rec = { path: p[1] }
    const n = o.match(/name:\s*'([^']*)'/)
    if (n) rec.name = n[1]
    const r = o.match(/redirect:\s*'([^']*)'/)
    if (r) rec.redirect = r[1]
    const c = o.match(/component:\s*(?:\(\)\s*=>\s*)?import\('([^']+)'\)/)
    if (c) rec.component = c[1]
    routeObjs.push(rec)
  }
  return routeObjs
}

const curSrc = read(path.join(SRC, 'router/routes.web.js'))
const headSrc = read('G:/MDCX/docs/redesign/_routes_head.js')
const cur = parseRoutes2(curSrc)
const head = parseRoutes2(headSrc)

/* 组装绝对路径：'/' 根 + children + 非 '/' 顶级 */
function absPaths(list) {
  const set = new Map()
  let parent = null
  // 顺序扫描：遇到 path:'/' 且无 name 视为父
  for (const r of list) {
    if (r.path === '' && !r.name) continue
    let abs
    if (r.path.startsWith('/')) {
      abs = r.path
      parent = r.path
    } else {
      abs = '/' + r.path
    }
    set.set(abs, r)
  }
  return set
}

const curSet = absPaths(cur)
const headSet = absPaths(head)

const curPaths = [...curSet.keys()].sort()
const headPaths = [...headSet.keys()].sort()

const removed = headPaths.filter((p) => !curSet.has(p))
const added = curPaths.filter((p) => !headSet.has(p))

console.log('=== [2] 路由完整性 ===')
console.log(`HEAD 路由数: ${headPaths.length} | 当前路由数: ${curPaths.length}`)
console.log(`删除路径 (${removed.length}):`, removed.length ? removed : '无 ✅')
console.log(`新增路径 (${added.length}):`)
added.forEach((p) => console.log('   +', p, '|', curSet.get(p).name || '(no name)', '|', curSet.get(p).component || '(no component)'))

console.log('\n-- 2b 新增恰好 7 条 /tools* --')
const addedTools = added.filter((p) => p === '/tools' || p.startsWith('/tools/'))
console.log('新增 /tools* 条数:', addedTools.length, addedTools.length === 7 ? '✅' : '❌')
const addedOther = added.filter((p) => !(p === '/tools' || p.startsWith('/tools/')))
console.log('新增的非 /tools 路径:', addedOther.length ? addedOther : '无 ✅')

console.log('\n-- 2c /uncensored redirect --')
const unc = curSet.get('/uncensored')
console.log('  /uncensored =', JSON.stringify(unc), unc && unc.redirect === '/uncensored/movies' ? '✅' : '❌')

console.log('\n-- 2d name 唯一性 --')
const names = cur.filter((r) => r.name).map((r) => r.name)
const dupNames = names.filter((n, i) => names.indexOf(n) !== i)
const uniqDup = [...new Set(dupNames)]
console.log(`name 总数: ${names.length} | 重复:`, uniqDup.length ? uniqDup : '无 ✅')

/* ---------- [3] 死链检查 ---------- */
console.log('\n=== [3] 死链检查（import 目标是否存在）===')
const importRe = /import\(\s*'(@\/[^']+)'\s*\)/g
const staticImportRe = /^\s*import\s+\w+\s+from\s+'(@\/[^']+)'/gm
const missing = []
const checked = new Set()
for (const src of [curSrc]) {
  let m
  while ((m = importRe.exec(src))) checked.add(m[1])
  while ((m = staticImportRe.exec(src))) checked.add(m[1])
}
for (const spec of [...checked].sort()) {
  const rel = spec.replace(/^@\//, '')
  const abs = path.join(SRC, rel)
  let ok = fs.existsSync(abs)
  if (!ok) {
    for (const ext of ['.js', '.vue', '.ts', '/index.js', '/index.vue']) {
      if (fs.existsSync(abs + ext)) { ok = true; break }
    }
  }
  if (!ok) missing.push(spec)
}
console.log(`被引用模块数: ${checked.size}`)
console.log('缺失目标:', missing.length ? missing : '无 ✅')

/* ---------- 全项目 vue 引用交叉检查（含深层组件内部 import） ---------- */
console.log('\n-- 3b 全 src 死链扫描（.vue/.js 内所有 @/ import）--')
const allMissing = []
function walk(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const fp = path.join(dir, e.name)
    if (e.isDirectory()) { if (e.name !== 'node_modules') walk(fp) }
    else if (/\.(vue|js|ts)$/.test(e.name)) {
      const txt = read(fp)
      const re = /from\s+'(@\/[^']+)'|import\(\s*'(@\/[^']+)'\s*\)/g
      let m
      while ((m = re.exec(txt))) {
        const spec = m[1] || m[2]
        const rel = spec.replace(/^@\//, '')
        const abs = path.join(SRC, rel)
        let ok = fs.existsSync(abs)
        if (!ok) for (const ext of ['.js', '.vue', '.ts', '/index.js', '/index.vue']) {
          if (fs.existsSync(abs + ext)) { ok = true; break }
        }
        if (!ok) allMissing.push(`${path.relative(ROOT, fp)} -> ${spec}`)
      }
    }
  }
}
walk(SRC)
console.log('全量缺失:', allMissing.length ? [...new Set(allMissing)] : '无 ✅')

/* ---------- [4] NAV 一致性 ---------- */
console.log('\n=== [4] NAV 一致性 ===')
const navMod = await import('file:///G:/MDCX/docs/redesign/_nav_copy.mjs')
const { NAV, TOOL_GROUPS, EXTRA_TITLES, flattenNav } = navMod
console.log('NAV 一级组数:', NAV.length, NAV.length === 5 ? '✅' : '❌', '->', NAV.map((n) => n.key).join(', '))

const toolsGroup = NAV.find((n) => n.key === 'tools')
console.log('工具中心组: to =', toolsGroup?.to, toolsGroup?.to === '/tools' ? '✅' : '❌')
const toolsChildren = (toolsGroup?.children || []).filter((c) => c && !c.divider)
console.log('工具中心组子项(非divider):', toolsChildren.map((c) => `${c.key}->${c.to}`).join(', '))
const expectedGroups = ['/tools/scrape', '/tools/fix', '/tools/organize', '/tools/health', '/tools/download', '/tools/system']
const missingGroups = expectedGroups.filter((p) => !toolsChildren.some((c) => c.to === p))
console.log('缺失组页:', missingGroups.length ? missingGroups : '无 ✅')
console.log('是否有 /tools 总览直连:', toolsChildren.some((c) => c.to === '/tools') ? '✅' : '❌')

const leaves = flattenNav()
console.log('flattenNav 叶子数:', leaves.length)
const badTo = leaves.filter((l) => {
  const t = (l.to || '').split('?')[0]
  if (!t) return true
  if (curSet.has(t)) return false
  if (EXTRA_TITLES[t]) return false
  // 带 :id 的父路径也算可用
  return true
})
console.log('nav 中 routes 找不到的 to:')
if (!badTo.length) console.log('  无 ✅')
else badTo.forEach((b) => console.log(`  ❌ ${b.groupLabel || '(top)'} / ${b.key} -> ${b.to}`))

console.log('\n-- 4b 各分组子项计数 --')
for (const n of NAV) {
  if (n.kind !== 'group') continue
  const cs = (n.children || []).filter((c) => c && !c.divider)
  console.log(`  ${n.key}(${n.label}): ${cs.length} 项`)
}

console.log('\n-- 4c TOOL_GROUPS 统计 --')
let totalTools = 0
for (const g of TOOL_GROUPS) {
  console.log(`  ${g.key}(${g.label}) -> ${g.to}: ${g.tools.length} 个工具`)
  totalTools += g.tools.length
}
console.log('工具总数:', totalTools)
console.log('TOOL_GROUPS 数:', TOOL_GROUPS.length, TOOL_GROUPS.length === 6 ? '✅' : '❌')

// tool key 是否都能在 toolComponents 找到
const tcSrc = read(path.join(SRC, 'config/toolComponents.js'))
const missingToolComp = []
for (const g of TOOL_GROUPS) for (const t of g.tools) {
  const re = new RegExp(`(^|[\\s,{])${t.tool}\\s*:`, 'm')
  if (!re.test(tcSrc)) missingToolComp.push(`${g.key}/${t.key} (tool=${t.tool})`)
}
console.log('toolComponents 缺键:', missingToolComp.length ? missingToolComp : '无 ✅')

/* ---------- 4d nav legacy 路径是否仍是有效路由（用于提示，不算失败） ---------- */
const legacyNotRoute = []
for (const g of TOOL_GROUPS) for (const t of g.tools) {
  for (const lg of t.legacy || []) {
    if (!curSet.has(lg)) legacyNotRoute.push(`${t.key}: ${lg}`)
  }
}
console.log('\n-- 4d TOOL_GROUPS.legacy 指向的不存在路由（仅提示）--')
console.log(legacyNotRoute.length ? legacyNotRoute : '无 ✅')

console.log('\n=== 汇总数据已输出 ===')
