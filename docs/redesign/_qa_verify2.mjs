/* QA 第二轮：API 导出交叉校验 + 模板根节点 + 静态扫描 */
import fs from 'node:fs'
import path from 'node:path'

const ROOT = 'G:/MDCX/MDCX-Desktop'
const SRC = path.join(ROOT, 'src')
const read = (p) => fs.readFileSync(p, 'utf8')

/* ---------- 收集 api 模块的导出符号 ---------- */
function exportsOf(file) {
  if (!fs.existsSync(file)) return null
  const t = read(file)
  const names = new Set()
  // export const X / export function X / export async function X
  for (const m of t.matchAll(/export\s+(?:async\s+)?(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)/g)) names.add(m[1])
  // export { a, b as c }
  for (const m of t.matchAll(/export\s*\{([^}]+)\}/g)) {
    for (const part of m[1].split(',')) {
      const seg = part.trim()
      if (!seg) continue
      const as = seg.split(/\s+as\s+/)
      names.add((as[1] || as[0]).trim())
    }
  }
  // export * from './x' 先不展开（下面单独处理）
  return names
}

const apiIndex = path.join(SRC, 'api/index.js')
const idxExports = exportsOf(apiIndex)
// 处理 index.js 里的 export * from
const idxText = read(apiIndex)
const starFrom = [...idxText.matchAll(/export\s*\*\s*from\s*'([^']+)'/g)].map((m) => m[1])
for (const s of starFrom) {
  const abs = s.startsWith('@/') ? path.join(SRC, s.slice(2)) : path.resolve(path.join(SRC, 'api'), s)
  const ex = exportsOf(abs.endsWith('.js') ? abs : abs + '.js')
  if (ex) ex.forEach((n) => idxExports.add(n))
}

console.log('=== [6] API 导出交叉校验 ===')
console.log(`@/api 导出符号数: ${idxExports.size} （含 export * from: ${starFrom.join(', ') || '无'}）`)

const TARGET_DIRS = ['components/dashboard', 'components/shell', 'layouts', 'views/tools', 'stores', 'config']
const FILES = []
function walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const fp = path.join(d, e.name)
    if (e.isDirectory()) walk(fp)
    else if (/\.(vue|js)$/.test(e.name)) FILES.push(fp)
  }
}
for (const d of TARGET_DIRS) {
  const abs = path.join(SRC, d)
  if (fs.existsSync(abs)) walk(abs)
}
FILES.push(path.join(SRC, 'views/Home.vue'))

const problems = []
const usage = new Map()   // fn -> [files]
for (const f of FILES) {
  const t = read(f)
  const re = /import\s*\{([^}]+)\}\s*from\s*'(@\/api(?:\/[\w-]+)?)'/g
  let m
  while ((m = re.exec(t))) {
    const spec = m[2]
    const list = m[1].split(',').map((s) => s.trim().split(/\s+as\s+/)[0].trim()).filter(Boolean)
    const target = spec === '@/api' ? apiIndex : path.join(SRC, spec.slice(2)) + (spec.endsWith('.js') ? '' : '.js')
    const ex = spec === '@/api' ? idxExports : exportsOf(fs.existsSync(target) ? target : target + '.js')
    for (const n of list) {
      if (!ex || !ex.has(n)) problems.push(`${path.relative(ROOT, f)}  <-  ${spec} 缺少导出: ${n}`)
      const arr = usage.get(n) || []
      arr.push(path.relative(SRC, f))
      usage.set(n, arr)
    }
  }
  // 默认导入 '@/api/modules' 等
  const dre = /import\s+([A-Za-z_$][\w$]*)\s+from\s*'(@\/api[\w/-]*)'/g
  while ((m = dre.exec(t))) {
    const target = path.join(SRC, m[2].slice(2))
    const p = fs.existsSync(target) ? target : target + '.js'
    if (!fs.existsSync(p)) problems.push(`${path.relative(ROOT, f)}  <-  默认导入目标不存在: ${m[2]}`)
  }
}
console.log('被引用的 api 函数:')
for (const [fn, files] of [...usage].sort()) {
  console.log(`  ${fn}  <-  ${[...new Set(files)].join(', ')}`)
}
console.log('\n缺失导出:', problems.length ? problems : '无 ✅')

/* ---------- [7] 模板根节点分析 ---------- */
console.log('\n=== [7] 模板根节点（是否单根 / 是否嵌套 PageShell 造成 24px 翻倍）===')
function templateRoots(file) {
  const t = read(file)
  const s = t.indexOf('<template>')
  if (s < 0) return null
  // 找配对 </template>（考虑嵌套）
  let depth = 0
  let i = s
  let end = -1
  const re = /<template\b[^>]*>|<\/template>/g
  re.lastIndex = s
  let m
  while ((m = re.exec(t))) {
    if (m[0].startsWith('</')) { depth--; if (depth === 0) { end = m.index; break } }
    else depth++
  }
  if (end < 0) return null
  let body = t.slice(s + '<template>'.length, end)
  // 去掉注释
  body = body.replace(/<!--[\s\S]*?-->/g, '')
  // 顶层标签扫描
  const roots = []
  let d = 0
  const tagRe = /<\/?([A-Za-z][\w.-]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/?)>/g
  let mm
  while ((mm = tagRe.exec(body))) {
    const isClose = mm[0].startsWith('</')
    const selfClose = mm[3] === '/'
    const name = mm[1]
    if (d === 0 && !isClose) roots.push(name)
    if (isClose) d--
    else if (!selfClose && !['br', 'hr', 'img', 'input', 'meta', 'link'].includes(name.toLowerCase())) d++
  }
  return roots
}

const VIEWS = []
function walkVue(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const fp = path.join(d, e.name)
    if (e.isDirectory()) walkVue(fp)
    else if (e.name.endsWith('.vue')) VIEWS.push(fp)
  }
}
walkVue(SRC)

const multi = []
const nestedShell = []
for (const f of VIEWS) {
  const roots = templateRoots(f)
  if (!roots) continue
  if (roots.length > 1) multi.push(`${path.relative(SRC, f)}  ->  ${roots.join(' + ')}`)
  const t = read(f)
  const isShellRoot = roots.length === 1 && /^PageShell$/.test(roots[0])
  if (!isShellRoot && (t.match(/<PageShell\b/) || /import\s+PageShell/.test(t))) {
    nestedShell.push(`${path.relative(SRC, f)}  (根=${roots.join('+')}) 内含 PageShell`)
  }
}
console.log(`.vue 文件总数: ${VIEWS.length}`)
console.log(`\n多根节点页面 (${multi.length})：`)
multi.slice(0, 40).forEach((x) => console.log('  ⚠️ ', x))
if (multi.length > 40) console.log(`  ... 其余 ${multi.length - 40} 个`)

console.log(`\n非 PageShell 根 但内部使用 PageShell（24px 叠加风险）(${nestedShell.length})：`)
nestedShell.forEach((x) => console.log('  ⚠️ ', x))
if (!nestedShell.length) console.log('  无 ✅')

/* ---------- [8] 静态扫描 ---------- */
console.log('\n=== [8] 静态扫描（新增文件）===')
const NEW_DIRS = ['components/shell', 'components/dashboard', 'views/tools', 'layouts', 'stores', 'config', 'styles']
const NEW_FILES = new Set()
for (const d of NEW_DIRS) {
  const abs = path.join(SRC, d)
  if (!fs.existsSync(abs)) continue
  const rec = (p) => {
    for (const e of fs.readdirSync(p, { withFileTypes: true })) {
      const fp = path.join(p, e.name)
      if (e.isDirectory()) rec(fp)
      else NEW_FILES.add(fp)
    }
  }
  rec(abs)
}
NEW_FILES.add(path.join(SRC, 'views/Home.vue'))
NEW_FILES.add(path.join(SRC, 'components/base/PageShell.vue'))
NEW_FILES.add(path.join(SRC, 'views/Crawlers.vue'))
NEW_FILES.add(path.join(SRC, 'router/routes.web.js'))
NEW_FILES.add(path.join(SRC, 'main.js'))

const patterns = [
  { key: 'transition: all', re: /transition:\s*all\b/g },
  { key: '裸 outline: none', re: /outline:\s*none\s*;/g },
  { key: 'console.log', re: /console\.log\s*\(/g },
  { key: 'console.warn', re: /console\.warn\s*\(/g },
  { key: 'console.error', re: /console\.error\s*\(/g },
  { key: 'debugger', re: /\bdebugger\b/g },
  { key: 'TODO/FIXME', re: /\b(TODO|FIXME|XXX)\b/g },
]
for (const p of patterns) {
  const hits = []
  for (const f of NEW_FILES) {
    const t = read(f)
    const lines = t.split('\n')
    lines.forEach((ln, i) => { if (new RegExp(p.re.source).test(ln)) hits.push(`${path.relative(SRC, f)}:${i + 1}  ${ln.trim().slice(0, 110)}`) })
  }
  console.log(`\n-- ${p.key} (${hits.length}) --`)
  hits.slice(0, 15).forEach((h) => console.log('   ', h))
  if (hits.length > 15) console.log(`    ... 其余 ${hits.length - 15} 条`)
}

/* outline:none 是否配了 focus-visible 替代 */
console.log('\n-- outline:none 上下文核查（是否紧邻 focus-visible / box-shadow）--')
for (const f of NEW_FILES) {
  const t = read(f)
  const lines = t.split('\n')
  lines.forEach((ln, i) => {
    if (/outline:\s*none/.test(ln)) {
      const ctx = lines.slice(Math.max(0, i - 6), i + 4).join(' | ')
      console.log(`   ${path.relative(SRC, f)}:${i + 1}  ctx: ${ctx.replace(/\s+/g, ' ').slice(0, 200)}`)
    }
  })
}
