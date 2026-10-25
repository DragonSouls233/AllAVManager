<template>
  <!--
    EntityHero —— 实体资料卡（演员/厂牌/系列/标签共用的一块）

    统一的不是「长得一样」，而是资料页那一块信息的**分层**：
      ① 大位（头像）  ② 身份：名字 + 元信息一行 + 外链  ③ 资料表（右栏）
      ④ 卡底附注带（同台演员）
    此前每个模块的演员页各写一套（7 份重复、各自硬编码 #999/#409eff），
    改一个间距要改 7 处。这里把分层与几何定死，字段由页面传进来 ——
    有值才显示那一行，没有就不占位，所以缺资料的演员不会留一屏空洞。

    不统一的：字段有哪些（jav 有三围、pornhub 只有国籍）、卡下面接什么内容区。
    那部分由页面自己排，组件只交出这一块卡。
  -->
  <section class="entity-hero" aria-label="资料">
    <div class="eh-profile" :class="{ 'eh-has-facts': facts.length }">
      <!-- ① 大位：页面要自己挂「点击换头像」之类的东西时填 portrait 槽，否则用默认头像 -->
      <div class="eh-portrait-wrap">
        <slot name="portrait">
          <div class="eh-portrait" :class="`eh-portrait--${shape}`">
            <img
              v-if="avatarSrc && !avatarFailed"
              :src="avatarSrc"
              :alt="name"
              loading="lazy"
              referrerpolicy="no-referrer"
              @error="avatarFailed = true"
            >
            <span v-else class="eh-initial">{{ initial }}</span>
          </div>
        </slot>
      </div>

      <!-- ② 身份 -->
      <div class="eh-identity">
        <!-- 标题：页面要给名字挂交互（双击复制之类）时填 title 槽，否则用默认那一行 -->
        <div class="eh-title">
          <slot name="title"><h2>{{ name }}</h2></slot>
          <span v-if="kindLabel" class="eh-kind">{{ kindLabel }}</span>
          <slot name="title-extra" />
        </div>

        <div v-if="meta.length" class="eh-meta">
          <component
            :is="item.action ? 'button' : 'span'"
            v-for="(item, i) in meta"
            :key="i"
            class="eh-meta-item"
            :class="{ 'eh-meta-item--action': item.action }"
            :title="item.title || item.text"
            :type="item.action ? 'button' : undefined"
            @click="item.action && emit('pick-meta', item)"
          >
            <HeroGlyph v-if="item.icon" :name="item.icon" />
            <b v-if="item.strong">{{ item.value }}</b>
            <span v-else>{{ item.value }}</span>
            <span v-if="item.text" class="eh-meta-text">{{ item.text }}</span>
          </component>
        </div>

        <div v-if="links.length" class="eh-links">
          <a
            v-for="(link, i) in links"
            :key="i"
            class="eh-link"
            :class="{ 'eh-link--icon': !link.label }"
            :href="link.url || undefined"
            :title="link.title || link.label || ''"
            :aria-label="link.title || link.label || ''"
            target="_blank"
            rel="noreferrer"
            @click="link.action && emit('pick-link', link)"
          >
            <span class="eh-link-icon"><HeroGlyph :name="link.icon || 'globe'" /></span>
            <span v-if="link.label" class="eh-link-label">{{ link.label }}</span>
          </a>
        </div>

        <slot name="identity-extra" />
      </div>

      <!-- ③ 资料表：内容区够宽时排右栏，窄了掉到身份下面（见样式里的断点） -->
      <dl v-if="facts.length" class="eh-facts">
        <template v-for="row in facts" :key="row.label">
          <dt>
            <HeroGlyph v-if="row.icon" :name="row.icon" />
            <span>{{ row.label }}</span>
          </dt>
          <dd :class="{ 'eh-fact--clip': row.clip, 'eh-fact--tags': row.tags }" :title="row.title || row.value">
            <template v-if="row.tags">
              <span v-for="t in row.tags" :key="t" class="eh-tag">{{ t }}</span>
            </template>
            <template v-else>{{ row.value }}</template>
          </dd>
        </template>
      </dl>
    </div>

    <!-- ④ 卡底：同台演员（没有就整条不渲染，不留空带） -->
    <div v-if="related.length" class="eh-foot">
      <span class="eh-foot-label">{{ relatedLabel }}</span>
      <div class="eh-related">
        <button
          v-for="p in related"
          :key="p.id || p.name"
          type="button"
          class="eh-related-item"
          :title="p.movie_count ? `${p.name} · 共演 ${p.movie_count} 部` : p.name"
          @click="emit('pick-related', p)"
        >
          <span class="eh-ring">
            <span class="eh-ring-initial">{{ firstChar(p.name) }}</span>
            <img
              v-if="p.avatar"
              :src="p.avatar"
              :alt="p.name"
              loading="lazy"
              referrerpolicy="no-referrer"
              @error="onRelatedError(p, $event)"
            >
          </span>
          <span class="eh-related-name">{{ p.name }}</span>
        </button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import HeroGlyph from './HeroGlyph.vue'

const props = defineProps({
  /** 主名（大标题） */
  name: { type: String, default: '' },
  /** 实体类型标签，如「演员」「厂牌」。不传则不显示 */
  kindLabel: { type: String, default: '' },
  /** 头像 URL；空或加载失败时退到首字母 */
  avatar: { type: String, default: '' },
  /** 圆头像（人）/ 方头像（厂牌、系列） */
  shape: { type: String, default: 'round' },
  /**
   * 元信息一行：[{ icon, value, text, strong, title, action }]
   * strong → 数字用正文色强调；action → 渲染成可点按钮，点击抛 pick-meta。
   */
  meta: { type: Array, default: () => [] },
  /**
   * 资料表：[{ label, icon, value, tags, clip, title }]
   * tags 有值时渲染成一排药丸；clip → 单行省略，全文进 title。
   */
  facts: { type: Array, default: () => [] },
  /** 外链：[{ label, url, icon, title, action }]；label 为空则只画图标（正方形按钮） */
  links: { type: Array, default: () => [] },
  /** 卡底附注带：[{ id, name, avatar, movie_count }] */
  related: { type: Array, default: () => [] },
  relatedLabel: { type: String, default: '同台演员' },
})

const emit = defineEmits(['pick-meta', 'pick-link', 'pick-related'])

const avatarSrc = computed(() => props.avatar || '')
const avatarFailed = ref(false)
watch(avatarSrc, () => { avatarFailed.value = false })

/** 取首个字符（中文/日文多为单码点，emoji 之类也不会被拆成半个字符） */
function firstChar(s) {
  const t = String(s || '?').trim()
  return Array.from(t)[0] || '?'
}
const initial = computed(() => firstChar(props.name))

/** 同台演员头像裂了就把 img 摘掉，露出底下那枚首字母圆底 */
function onRelatedError(person, event) {
  const el = event?.target
  if (el && el.parentNode) el.parentNode.removeChild(el)
}
</script>

<style scoped>
/* ── 卡 ──
 * 一块 16px 圆角的卡，底带贴着卡的下边缘，靠 overflow:hidden 让它的直角被圆角裁掉。 */
.entity-hero {
  display: flex;
  flex-direction: column;
  min-width: 0;
  max-width: 100%;
  margin: 0 0 20px;
  overflow: hidden;
  border: 1px solid var(--border-color, #ebeef5);
  border-radius: 16px;
  background: var(--bg-card, #fff);
  color: var(--text-primary, #303133);
  font-size: 14px;
  line-height: 22px;
}

/* ── 主体：头像 / 身份 / 资料表 ──
 * 头像尺寸按「这一页有几行」定：外链与资料表都在时放到 160px，其余 120px。
 * 取百分比会成一个圈（列宽 → 折行 → 行高 → 头像宽），所以钉死两档。 */
.eh-profile {
  --portrait-size: 120px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 20px;
  min-width: 0;
  padding: 20px;
}
.eh-profile:has(.eh-links) {
  --portrait-size: 160px;
}
.eh-profile.eh-has-facts {
  grid-template-columns: auto minmax(0, 1fr) minmax(280px, 360px);
}

/* ── 头像 ── */
.eh-portrait-wrap {
  display: flex;
  align-items: center;
  align-self: stretch;
  width: max-content;
  max-width: 100%;
  /* 身份列被很多行撑高时，头像不再跟着居中往下坠，至多离卡顶 32px */
  max-height: calc(var(--portrait-size) + 64px);
}
.eh-portrait {
  position: relative;
  display: grid;
  place-items: center;
  width: var(--portrait-size);
  height: var(--portrait-size);
  overflow: hidden;
  border-radius: 50%;
  background: var(--bg-hover, #f3f4f6);
  color: var(--text-secondary, #6b7280);
  font-size: 30px;
}
.eh-portrait--square {
  border-radius: 12px;
}
.eh-portrait > span {
  grid-area: 1 / 1;
}
.eh-portrait img {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: block;
  width: 100%;
  height: 100%;
  max-width: none;
  object-fit: cover;
}
/* 竖长头像偏上取景：脸多在画面上半截 */
.eh-portrait--round img {
  object-position: 50% 25%;
}

/* ── 身份 ── */
.eh-identity {
  min-width: 0;
  max-width: 100%;
}
.eh-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  margin: 0 0 9px;
}
.eh-title h2 {
  margin: 0;
  overflow-wrap: anywhere;
  font-size: 24px;
  font-weight: 500;
  line-height: 32px;
}
.eh-kind {
  flex: none;
  padding: 0 8px;
  border: 1px solid var(--border-color, #ebeef5);
  border-radius: 999px;
  color: var(--text-secondary, #6b7280);
  font-size: 12px;
  line-height: 20px;
}

/* 元信息一行：编号、作品数、事务所…… 装不下整项换行，不挤成一团 */
.eh-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 18px;
  color: var(--text-secondary, #6b7280);
  font-size: 14px;
  line-height: 20px;
  overflow-wrap: anywhere;
}
.eh-meta-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
}
.eh-meta-item b {
  color: var(--text-primary, #303133);
  font-weight: 500;
}
.eh-meta-item--action {
  cursor: pointer;
}
.eh-meta-item--action:hover {
  color: var(--primary-color, #409eff);
}

/* ── 外链 ──
 * 一行 36px 高、10px 圆角的次级按钮：它们是「去哪」的入口，不是标签，所以不画成药丸。 */
.eh-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  max-width: 100%;
  margin-top: 14px;
}
.eh-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  box-sizing: border-box;
  min-width: 0;
  max-width: 100%;
  height: 36px;
  padding: 0 12px 0 8px;
  overflow: hidden;
  border: 1px solid var(--border-color, #ebeef5);
  border-radius: 10px;
  color: var(--text-primary, #303133);
  font-size: 13px;
  text-decoration: none;
}
.eh-link:hover {
  background: var(--bg-hover, #f3f4f6);
  text-decoration: none;
}
/* 只有图标的链接收成正方形 */
.eh-link--icon {
  justify-content: center;
  gap: 0;
  width: 36px;
  padding: 0;
}
.eh-link-icon {
  display: grid;
  flex: none;
  place-items: center;
  width: 20px;
  height: 20px;
}
.eh-link-label {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

/* ── 资料表 ── */
.eh-facts {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-content: center;
  gap: 10px 16px;
  min-width: 0;
  margin: 0;
  padding: 2px 0 2px 24px;
  border-left: 1px solid var(--border-color, #ebeef5);
  font-size: 13px;
  line-height: 22px;
  text-align: left;
}
.eh-facts dt {
  display: flex;
  align-items: center;
  align-self: start;
  gap: 6px;
  color: var(--text-secondary, #6b7280);
  white-space: nowrap;
}
.eh-facts dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
}
.eh-fact--clip {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.eh-fact--tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.eh-tag {
  box-sizing: border-box;
  max-width: 100%;
  overflow: hidden;
  padding: 0 8px;
  border: 1px solid var(--border-color, #ebeef5);
  border-radius: 999px;
  background: var(--bg-hover, #f3f4f6);
  color: var(--text-regular, #606266);
  font-size: 12px;
  line-height: 20px;
  white-space: nowrap;
  text-overflow: ellipsis;
}

/* ── 卡底：同台演员 ── */
.eh-foot {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
  padding: 12px 20px;
  border-top: 1px solid var(--border-color, #ebeef5);
}
.eh-foot-label {
  flex: none;
  color: var(--text-secondary, #6b7280);
  font-size: 12px;
  line-height: 20px;
}
/* 横滚的一条轨道：能滚，但鼠标没有够得着的入口，所以留着滚轮/触控板横向滚动 */
.eh-related {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 4px;
  min-width: 0;
  overflow-x: auto;
  overscroll-behavior-inline: contain;
  scrollbar-width: none;
}
.eh-related::-webkit-scrollbar {
  display: none;
}
.eh-related-item {
  display: flex;
  flex: none;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  width: 76px;
  padding: 6px 4px;
  border: 0;
  border-radius: 12px;
  background: transparent;
  color: var(--text-secondary, #6b7280);
  font: inherit;
  text-align: center;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 0.2s ease-out, color 0.2s ease-out;
}
.eh-related-item:hover {
  background: var(--bg-hover, #f3f4f6);
  color: var(--text-primary, #303133);
}
.eh-ring {
  position: relative;
  display: block;
  flex: none;
  width: 48px;
  height: 48px;
  overflow: hidden;
  border-radius: 50%;
  background: var(--bg-hover, #f3f4f6);
  color: var(--text-secondary, #6b7280);
  font-size: 18px;
  font-weight: 600;
  line-height: 24px;
}
.eh-ring-initial {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font: inherit;
}
.eh-ring img {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  max-width: none;
  object-fit: cover;
}
.eh-related-name {
  display: block;
  max-width: 100%;
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
}

/* ── 窄屏 ──
 * 内容区放不下三栏时资料表掉到底下、分隔线转横；更窄时整块单列居中。 */
@media (max-width: 1180px) {
  .eh-profile.eh-has-facts {
    grid-template-columns: auto minmax(0, 1fr);
  }
  .eh-facts {
    grid-column: 1 / -1;
    padding: 14px 0 0;
    border-top: 1px solid var(--border-color, #ebeef5);
    border-left: 0;
  }
}
@media (max-width: 760px) {
  .eh-profile {
    grid-template-columns: minmax(0, 1fr);
    justify-items: center;
    gap: 12px;
    padding: 16px;
    text-align: center;
  }
  .eh-portrait-wrap {
    --portrait-size: 96px;
  }
  .eh-portrait {
    width: 96px;
  }
  .eh-identity {
    width: 100%;
  }
  .eh-title {
    justify-content: center;
  }
  .eh-meta {
    justify-content: center;
  }
  /* 外链窄屏下横滚，不换行：装不下时贴左，溢出的那几条才滑得到 */
  .eh-links {
    flex-wrap: nowrap;
    justify-content: safe center;
    max-width: none;
    margin: 9px -16px -4px;
    padding: 4px 16px;
    overflow-x: auto;
    overflow-y: hidden;
    scrollbar-width: none;
  }
  .eh-links::-webkit-scrollbar {
    display: none;
  }
  .eh-link {
    flex: none;
  }
  .eh-foot {
    padding: 10px 16px;
  }
}
</style>
