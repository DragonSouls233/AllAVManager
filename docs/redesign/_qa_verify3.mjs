/* QA 第三轮：CSS 变量定义完整性 + CommandPalette 焦点核查 */
import fs from 'node:fs'
import path from 'node:path'

const SRC = 'G:/MDCX/MDCX-Desktop/src'
const read = (p) => fs.readFileSync(p, 'utf8')

/* 收集所有 CSS 变量定义（--x: 形式） */
const defined = new Set()
const styleFiles = []
function walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const fp = path.join(d, e.name)
    if (e.isDirectory()) walk(fp)
    else if (/\.(css|vue|js)$/.test(e.name)) styleFiles.push(fp)
  }
}
walk(SRC)
// index.html 也可能有内联
const html = fs.existsSync('G:/MDCX/MDCX-Desktop/index.html') ? read('G:/MDCX/MDCX-Desktop/index.html') : ''
const all = styleFiles.map((f) => read(f)).join('\n') + html

for (const m of all.matchAll(/(--[A-Za-z][\w-]*)\s*:/g)) defined.add(m[1])
console.log('已定义的 CSS 变量数:', defined.size)

/* 新增/改动文件的 var() 使用 */
const TARGETS = []
for (const d of ['components/shell', 'components/dashboard', 'views/tools', 'layouts', 'styles', 'stores', 'config']) {
  const abs = path.join(SRC, d)
  if (!fs.existsSync(abs)) continue
  const rec = (p) => {
    for (const e of fs.readdirSync(p, { withFileTypes: true })) {
      const fp = path.join(p, e.name)
      if (e.isDirectory()) rec(fp)
      else TARGETS.push(fp)
    }
  }
  rec(abs)
}
TARGETS.push(path.join(SRC, 'views/Home.vue'))

console.log('\n=== var() 使用但未定义的变量 ===')
const undef = new Map()
for (const f of TARGETS) {
  const t = read(f)
  for (const m of t.matchAll(/var\(\s*(--[A-Za-z][\w-]*)/g)) {
    const v = m[1]
    if (!defined.has(v)) {
      const arr = undef.get(v) || []
      arr.push(path.relative(SRC, f))
      undef.set(v, arr)
    }
  }
}
if (!undef.size) console.log('  无 ✅')
else for (const [v, files] of undef) console.log(`  ⚠️ ${v}  <-  ${[...new Set(files)].join(', ')}`)

/* CommandPalette 焦点 */
console.log('\n=== CommandPalette 焦点处理 ===')
const cp = read(path.join(SRC, 'components/shell/CommandPalette.vue'))
const cpLines = cp.split('\n')
cpLines.forEach((ln, i) => {
  if (/outline|focus-within|focus-visible|box-shadow/.test(ln)) console.log(`  ${i + 1}: ${ln.trim()}`)
})

/* 全局快捷键监听 */
console.log('\n=== CommandPalette 键盘监听 ===')
for (const m of cp.matchAll(/.{0,60}(keydown|addEventListener|key ===|ctrlKey|metaKey).{0,80}/g)) {
  console.log('  ', m[0].replace(/\s+/g, ' ').trim())
}
