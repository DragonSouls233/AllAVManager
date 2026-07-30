const { chromium } = require('playwright');

const BASE_URL = 'http://192.168.10.110:8420';
const PASSWORD = 'ACx36O1i9eHXkGdbaV4uDA';

async function test() {
  console.log('=== MDCX 真实浏览器测试 ===\n');

  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    locale: 'zh-CN',
  });

  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', err => {
    consoleErrors.push(`PAGE ERROR: ${err.message}`);
  });

  try {
    // === 1. 访问首页并登录 ===
    console.log('1. 打开首页...');
    await page.goto(BASE_URL, { waitUntil: 'networkidle', timeout: 30000 });
    console.log(`   首页加载完成: ${page.url()}`);
    await page.screenshot({ path: 'test_screenshots/01-dashboard.png', fullPage: false });

    // 自动登录
    const pwInput = page.locator('input[type="password"]');
    if (await pwInput.isVisible({ timeout: 5000 }).catch(() => false)) {
      console.log('   检测到登录页，输入密码...');
      await pwInput.fill(PASSWORD);
      // 找登录按钮
      const submitBtn = page.locator('button:has-text("登录"), button:has-text("登入"), button[type="submit"]');
      if (await submitBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await submitBtn.click();
      } else {
        await pwInput.press('Enter');
      }
      await page.waitForTimeout(2000);
      console.log(`   登录后 URL: ${page.url()}`);
    } else {
      console.log('   跳过登录或已登录');
    }

    // 等待页面稳定
    await page.waitForTimeout(1000);
    await page.screenshot({ path: 'test_screenshots/01b-after-login.png', fullPage: false });

    // === 2. 检查左侧菜单 ===
    console.log('\n2. 检查左侧菜单...');
    // 截取整个页面看看布局
    await page.screenshot({ path: 'test_screenshots/02-layout.png', fullPage: true });

    const menuTexts = await page.locator('.el-menu-item, .el-sub-menu__title').allTextContents().catch(() => []);
    console.log(`   菜单项共 ${menuTexts.length} 条`);
    const menuItems = await page.locator('.el-menu-item').all();
    const menuUrls = [];
    for (const item of menuItems) {
      const href = await item.getAttribute('href').catch(() => null) || await item.getAttribute('data-href').catch(() => null) || await item.textContent().catch(() => '?');
      menuUrls.push(href);
    }
    // 输出前20个
    menuTexts.slice(0, 20).forEach((t, i) => console.log(`   [${i}] ${t.replace(/\n/g, ' ').trim().slice(0, 40)}`));

    // === 3. 各模块影片列表 ===
    const modules = [
      { name: 'JAV', path: '/jav/movies' },
      { name: 'FC2', path: '/fc2/movies' },
      { name: '国产', path: '/chinese/movies' },
      { name: '无码', path: '/uncensored/movies' },
      { name: '欧美', path: '/western/movies' },
      { name: 'Pornhub', path: '/pornhub/movies' },
    ];

    const moduleResults = [];
    for (const m of modules) {
      console.log(`\n3.${modules.indexOf(m) + 1} ${m.name} 影片列表...`);
      await page.goto(`${BASE_URL}${m.path}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(2000);
      await page.screenshot({ path: `test_screenshots/movies-${m.name}.png`, fullPage: false });

      const pageText = await page.locator('body').textContent().catch(() => '');
      const hasData = !pageText.includes('暂无') && !pageText.includes('没有数据');
      const hasError = pageText.includes('error') || pageText.includes('Error') || pageText.includes('出错');
      let movieCount = 0;
      // 尝试多种选择器数卡片
      const cards = page.locator('[class*="card"], [class*="movie"], [class*="item"], [class*="el-card"]');
      const visibleCards = await cards.count();
      for (let i = 0; i < Math.min(visibleCards, 5); i++) {
        if (await cards.nth(i).isVisible().catch(() => false)) movieCount++;
      }

      moduleResults.push({ name: m.name, hasData, hasError, movieCount });
      console.log(`   ✓ 有数据: ${hasData}  |  错误: ${hasError}  |  可见卡片: ${movieCount}`);
    }

    // === 4. 详情页测试（取有数据的模块） ===
    console.log('\n4. 详情页测试...');
    for (const m of moduleResults) {
      if (!m.hasData) continue;
      console.log(`   测试 ${m.name} 详情页...`);
      await page.goto(`${BASE_URL}${modules.find(x => x.name === m.name).path}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(2000);

      // 找链接
      const links = page.locator('a[href*="/movies/"]');
      const linkCount = await links.count().catch(() => 0);
      if (linkCount === 0) {
        console.log(`   无影片链接，跳过`);
        continue;
      }

      // 打开第一个影片
      const href = await links.first().getAttribute('href').catch(() => null);
      if (!href) continue;

      console.log(`   打开: ${href.substring(0, 60)}...`);
      await page.goto(`${BASE_URL}${href}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(2000);
      await page.screenshot({ path: `test_screenshots/detail-${m.name}.png`, fullPage: true });

      // 检查详情元素
      const detailText = await page.locator('body').textContent().catch(() => '');
      const checks = {
        '播放按钮': /\u25b6|播放|play/i.test(detailText),
        '演员信息': /演员|女优|actor/i.test(detailText),
        '番号': /番号|code|\u756a/i.test(detailText),
        '编辑按钮': /编辑|edit/i.test(detailText),
        '刮削按钮': /刮削|scrape/i.test(detailText),
        '收藏': /收藏|favorite|\u2605/i.test(detailText),
        '预览图': /预览|sample|preview/i.test(detailText) && detailText.includes('封面'),
        '简介': /简介|plot|description/i.test(detailText),
        '标签': /标签|tag|类别|genre/i.test(detailText),
        '评分': /\u2605|评分|rating/i.test(detailText),
      };
      console.log(`   详情页检查:`);
      for (const [key, val] of Object.entries(checks)) {
        console.log(`     ${val ? '✓' : '✗'} ${key}: ${val}`);
      }
    }

    // === 5. 爬虫管理页面 ===
    console.log('\n5. 各模块爬虫管理...');
    const scrapeRoutes = [
      { name: 'JAV', path: '/jav/scrape' },
      { name: 'FC2', path: '/fc2/scrape' },
      { name: '无码', path: '/uncensored/scrape' },
      { name: '欧美', path: '/western/scrape' },
      { name: 'Pornhub', path: '/pornhub/scrape' },
      { name: '国产', path: '/chinese/scrape' },
    ];

    for (const m of scrapeRoutes) {
      console.log(`   ${m.name}...`);
      await page.goto(`${BASE_URL}${m.path}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(1500);
      await page.screenshot({ path: `test_screenshots/scrape-${m.name}.png`, fullPage: false });

      const text = await page.locator('body').textContent().catch(() => '');
      const hasBanner = text.includes(m.name);
      const tableRows = await page.locator('.el-table__row').count().catch(() => 0);
      console.log(`   模块横幅: ${hasBanner}  |  站点数: ${tableRows}`);
    }

    // === 6. 站点优先级 ===
    console.log('\n6. 站点优先级页面...');
    await page.goto(`${BASE_URL}/site-priority`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: 'test_screenshots/site-priority.png', fullPage: true });
    const groupTitles = await page.locator('.group-title, .group-header .el-tag').allTextContents().catch(() => []);
    console.log(`   分组: ${groupTitles.join(' | ')}`);
    const siteItems = await page.locator('.site-row').count().catch(() => 0);
    console.log(`   站点行数: ${siteItems}`);

  } catch (err) {
    console.error(`\n  ✗ 出错: ${err.message}`);
    try { await page.screenshot({ path: 'test_screenshots/error.png', fullPage: true }); } catch (_) {}
  }

  if (consoleErrors.length > 0) {
    console.log(`\n=== 浏览器控制台错误 (${consoleErrors.length} 条) ===`);
    for (const err of consoleErrors.slice(0, 8)) {
      console.log(`  ✗ ${err.substring(0, 120)}`);
    }
    if (consoleErrors.length > 8) console.log(`  ... 还有 ${consoleErrors.length - 8} 个`);
  } else {
    console.log('\n✓ 无 JS 控制台错误');
  }

  await browser.close();
  console.log('\n=== 测试完成 ===');
}

test().catch(err => {
  console.error('FATAL:', err);
  process.exit(1);
});
