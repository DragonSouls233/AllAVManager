import fs from 'node:fs'
const tc = fs.readFileSync('G:/MDCX/MDCX-Desktop/src/config/toolComponents.js', 'utf8')
const nav = fs.readFileSync('G:/MDCX/MDCX-Desktop/src/config/nav.js', 'utf8')
const keys = [...tc.matchAll(/^\s{2}([A-Za-z][\w]*):\s*lazy\(/gm)].map((m) => m[1])
const used = new Set([...nav.matchAll(/tool:\s*'([^']+)'/g)].map((m) => m[1]))
console.log('TOOL_COMPONENTS 映射数:', keys.length)
console.log('nav 引用 tool 键数:', used.size)
console.log('mapped 但 nav 未用:', keys.filter((k) => !used.has(k)))
console.log('nav 用了但未映射:', [...used].filter((k) => !keys.includes(k)))
