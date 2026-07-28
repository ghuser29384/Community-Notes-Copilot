import { chromium, devices } from 'playwright';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs';
import path from 'node:path';

const outputDir = process.env.AUDIT_OUTPUT || path.resolve('audit-output');
const liveUrl = process.env.LIVE_URL || 'https://shiny-platypus-2c16ce.netlify.app';
const localUrl = process.env.LOCAL_URL || 'http://127.0.0.1:4173';
fs.mkdirSync(outputDir, { recursive: true });

const now = new Date().toISOString();
const audit = {
  generatedAt: now,
  targets: { liveUrl, localUrl },
  runs: {},
  summary: {},
};

const synthetic = {
  name: '审计样例-非真实患者',
  age: '年龄字段接受任意文本',
  bloodType: 'A型',
  idNumber: 'TEST-ID-NOT-REAL-440300000000000000',
  diagnosis: '审计测试诊断-非真实',
  surgery: '审计测试手术史-非真实',
  allergies: '审计测试药物过敏-非真实',
  otherDiseases: '审计测试其他疾病-非真实',
  medication: '审计测试药物-非真实',
  contact: '审计联系人-非真实',
  phone: '13800000000',
  hospital: '审计医院-非真实',
  doctor: '审计医生-非真实',
};

const complicationNames = ['消化道出血', '肠梗阻', '胆道梗阻', '感染', '腹水', '血栓'];

function safeName(value) {
  return value.replace(/[^a-zA-Z0-9_-]+/g, '-').replace(/^-+|-+$/g, '');
}

function saveJson(name, data) {
  fs.writeFileSync(path.join(outputDir, name), JSON.stringify(data, null, 2));
}

function pngDimensions(filePath) {
  const b = fs.readFileSync(filePath);
  if (b.length < 24 || b.toString('ascii', 1, 4) !== 'PNG') return null;
  return { width: b.readUInt32BE(16), height: b.readUInt32BE(20), bytes: b.length };
}

async function runAxe(page, name) {
  try {
    const report = await new AxeBuilder({ page }).analyze();
    const simplified = report.violations.map(v => ({
      id: v.id,
      impact: v.impact,
      description: v.description,
      help: v.help,
      helpUrl: v.helpUrl,
      nodes: v.nodes.map(n => ({ target: n.target, html: n.html, failureSummary: n.failureSummary })),
    }));
    saveJson(`axe-${safeName(name)}.json`, simplified);
    return { violationCount: simplified.length, violations: simplified };
  } catch (error) {
    return { error: String(error) };
  }
}

async function screenshot(page, name, fullPage = true) {
  const file = path.join(outputDir, `${safeName(name)}.png`);
  await page.screenshot({ path: file, fullPage });
  return file;
}

function observePage(context, page) {
  const network = [];
  const consoleMessages = [];
  const pageErrors = [];
  context.on('request', request => {
    network.push({
      phase: 'request',
      method: request.method(),
      url: request.url(),
      resourceType: request.resourceType(),
      postData: request.postData(),
    });
  });
  context.on('response', response => {
    network.push({ phase: 'response', status: response.status(), url: response.url() });
  });
  page.on('console', message => consoleMessages.push({ type: message.type(), text: message.text() }));
  page.on('pageerror', error => pageErrors.push(String(error)));
  return { network, consoleMessages, pageErrors };
}

async function openObserved(browser, url, options = {}) {
  const context = await browser.newContext({
    acceptDownloads: true,
    viewport: options.viewport || { width: 1440, height: 1100 },
    ...(options.device || {}),
  });
  const page = await context.newPage();
  const observation = observePage(context, page);
  const started = Date.now();
  let status = null;
  try {
    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    status = response?.status() ?? null;
    await page.waitForTimeout(1800);
  } catch (error) {
    observation.navigationError = String(error);
  }
  observation.loadMs = Date.now() - started;
  observation.status = status;
  observation.title = await page.title().catch(() => null);
  observation.url = page.url();
  return { context, page, observation };
}

async function statSnapshot(browser, url, count = 5) {
  const snapshots = [];
  for (let i = 0; i < count; i++) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const page = await context.newPage();
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
      await page.waitForTimeout(1300);
      const cards = await page.locator('div.grid.grid-cols-2.md\\:grid-cols-4 > div').allTextContents().catch(() => []);
      snapshots.push({ cards: cards.map(x => x.replace(/\s+/g, ' ').trim()), bodyHasOfflineMode: (await page.locator('body').innerText()).includes('离线模式') });
    } catch (error) {
      snapshots.push({ error: String(error) });
    }
    await context.close();
  }
  return snapshots;
}

async function selectComplication(page, name) {
  const card = page.locator('div.cursor-pointer').filter({ hasText: name }).first();
  await card.click();
}

async function desktopFunctionalAudit(browser, label, url) {
  const { context, page, observation } = await openObserved(browser, url);
  const result = { observation, checks: {}, axe: {}, downloads: {}, screenshots: [], errors: [] };
  if (observation.navigationError) {
    await context.close();
    return result;
  }

  const nextButton = () => page.getByRole('button', { name: /下一步/ });
  try {
    result.screenshots.push(await screenshot(page, `${label}-01-home`));
    result.axe.home = await runAxe(page, `${label}-home`);
    result.checks.homeText = (await page.locator('body').innerText()).slice(0, 12000);
    result.checks.footerLocalOnlyClaim = result.checks.homeText.includes('数据完全在本地处理，不会上传到服务器');
    result.checks.initialNextDisabled = await nextButton().isDisabled();

    const bleedingCard = page.locator('div.cursor-pointer').filter({ hasText: '消化道出血' }).first();
    result.checks.complicationCardSemantics = {
      tagName: await bleedingCard.evaluate(el => el.tagName),
      role: await bleedingCard.getAttribute('role'),
      tabIndexAttribute: await bleedingCard.getAttribute('tabindex'),
    };
    await bleedingCard.focus();
    result.checks.complicationCardFocusable = await bleedingCard.evaluate(el => document.activeElement === el);
    await page.keyboard.press('Enter');
    await page.waitForTimeout(150);
    result.checks.enterSelectsComplication = !(await nextButton().isDisabled());

    for (const name of complicationNames) {
      const card = page.locator('div.cursor-pointer').filter({ hasText: name }).first();
      const selected = (await card.getAttribute('class') || '').includes('border-red-500');
      if (!selected) await card.click();
    }
    result.checks.allSixSelected = !(await nextButton().isDisabled());
    await nextButton().click();
    await page.waitForTimeout(250);
    result.screenshots.push(await screenshot(page, `${label}-02-medical-form`));
    result.axe.medicalForm = await runAxe(page, `${label}-medical-form`);

    result.checks.medicalStepInitiallyDisabled = await nextButton().isDisabled();
    await page.locator('input[placeholder="请输入姓名"]').fill(' ');
    await page.locator('select').first().selectOption({ label: synthetic.bloodType });
    result.checks.whitespaceNameAccepted = !(await nextButton().isDisabled());

    await page.locator('input[placeholder="请输入姓名"]').fill(synthetic.name);
    await page.locator('input[placeholder="请输入年龄"]').fill(synthetic.age);
    await page.locator('input[placeholder="请输入身份证号"]').fill(synthetic.idNumber);
    await page.locator('input[placeholder*="胰腺癌"]').fill(synthetic.diagnosis);
    await page.locator('textarea[placeholder="请描述既往手术情况"]').fill(synthetic.surgery);
    await page.locator('input[placeholder*="青霉素过敏"]').fill(synthetic.allergies);
    await page.locator('textarea[placeholder*="高血压"]').fill(synthetic.otherDiseases);

    const antiCheckbox = page.getByText('正在进行抗凝治疗').locator('..').locator('input[type="checkbox"]');
    await antiCheckbox.check();
    await page.locator('input[placeholder*="华法林"]').fill('利伐沙班-审计样例');
    await page.locator('input[placeholder*="今日上午、昨日晚上"]').fill('今日08:00');

    await page.getByRole('button', { name: '添加药物' }).click();
    await page.locator('input[placeholder="请输入药物名称"]').fill(synthetic.medication);
    await page.locator('input[placeholder="如：100mg"]').fill('10mg');
    await page.locator('input[placeholder="如：每日2次"]').fill('每日1次');
    await page.locator('input[placeholder="如：今日上午8点"]').fill('今日08:00');
    await page.locator('input[placeholder="特殊说明或注意事项"]').fill('审计备注-非真实');

    result.checks.requiredFields = {
      nameRequiredByGate: true,
      bloodTypeRequiredByGate: true,
      ageRequiredByGate: false,
      allergiesRequiredByGate: false,
    };
    await nextButton().click();
    await page.waitForTimeout(250);
    result.screenshots.push(await screenshot(page, `${label}-03-contacts`));
    result.axe.contacts = await runAxe(page, `${label}-contacts`);

    const addButtons = page.getByRole('button', { name: '添加' });
    await addButtons.nth(2).click();
    result.checks.doctorOnlyAllowsProceed = !(await nextButton().isDisabled());
    await addButtons.nth(0).click();
    result.checks.emptyContactAllowsProceed = !(await nextButton().isDisabled());

    const contactBlock = page.locator('input[placeholder="姓名"]').first().locator('..');
    await contactBlock.locator('input[placeholder="姓名"]').fill(synthetic.contact);
    await contactBlock.locator('input[placeholder="电话号码"]').fill(synthetic.phone);
    await contactBlock.locator('input[placeholder="关系"]').fill('家属');

    await addButtons.nth(1).click();
    await page.locator('input[placeholder="医院名称"]').fill(synthetic.hospital);
    await page.locator('input[placeholder="急诊科电话"]').fill('010-00000000');
    await page.locator('input[placeholder="相关科室电话"]').fill('010-11111111');
    await page.locator('input[placeholder="医院特色"]').fill('审计测试特色');
    await page.locator('input[placeholder="医院地址"]').fill('审计测试地址');

    await page.locator('input[placeholder="医生姓名"]').fill(synthetic.doctor);
    await page.locator('input[placeholder="联系电话"]').fill('010-22222222');
    await page.locator('input[placeholder="科室"]').fill('肿瘤科');
    await page.locator('input[placeholder="所在医院"]').fill(synthetic.hospital);

    await nextButton().click();
    await page.waitForTimeout(400);
    result.screenshots.push(await screenshot(page, `${label}-04-preview-all-six`));
    result.axe.preview = await runAxe(page, `${label}-preview`);

    const previewText = await page.locator('body').innerText();
    const innerCard = page.locator('div[style*="min-height"]').first();
    const outerCapture = page.locator('[data-card-preview]').first();
    result.checks.preview = {
      containsName: previewText.includes(synthetic.name),
      containsDiagnosis: previewText.includes(synthetic.diagnosis),
      containsMedication: previewText.includes(synthetic.medication),
      containsAllergies: previewText.includes(synthetic.allergies),
      containsSurgeryHistory: previewText.includes(synthetic.surgery),
      containsOtherDiseases: previewText.includes(synthetic.otherDiseases),
      containsIdNumber: previewText.includes(synthetic.idNumber),
      containsHospitalDepartment: previewText.includes('010-11111111'),
      containsHospitalFeatures: previewText.includes('审计测试特色'),
      containsDoctorHospital: previewText.includes(`${synthetic.doctor}`) && previewText.includes(synthetic.hospital),
      hasContradictoryAnticoagulantInstructions: previewText.includes('服用阿司匹林等抗凝药物') && previewText.includes('自行停用抗凝药'),
      labelsAllSignalsCall120: (previewText.match(/立即拨打120的情况/g) || []).length,
      selectedComplicationCount: complicationNames.filter(n => previewText.includes(`${n}急症处理`)).length,
      documentScrollHeight: await page.evaluate(() => document.documentElement.scrollHeight),
      cardScrollHeight: await innerCard.evaluate(el => el.scrollHeight),
      outerCaptureScrollHeight: await outerCapture.evaluate(el => el.scrollHeight),
      innerCardBox: await innerCard.boundingBox(),
      outerCaptureBox: await outerCapture.boundingBox(),
    };

    const configDownloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: '下载配置' }).click();
    const configDownload = await configDownloadPromise;
    const configPath = path.join(outputDir, `${label}-downloaded-config.json`);
    await configDownload.saveAs(configPath);
    const downloadedConfig = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    result.downloads.config = {
      suggestedFilename: configDownload.suggestedFilename(),
      includesPatientNameInFilename: configDownload.suggestedFilename().includes(synthetic.name),
      includesIdNumber: JSON.stringify(downloadedConfig).includes(synthetic.idNumber),
      includesAllergies: JSON.stringify(downloadedConfig).includes(synthetic.allergies),
      includesContacts: JSON.stringify(downloadedConfig).includes(synthetic.phone),
      bytes: fs.statSync(configPath).size,
    };

    const imageDownloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: '下载图片' }).click();
    const imageDownload = await imageDownloadPromise;
    const imagePath = path.join(outputDir, `${label}-downloaded-card.png`);
    await imageDownload.saveAs(imagePath);
    result.downloads.image = {
      suggestedFilename: imageDownload.suggestedFilename(),
      includesPatientNameInFilename: imageDownload.suggestedFilename().includes(synthetic.name),
      dimensions: pngDimensions(imagePath),
      expectedOuterDimensionsAtScale2: {
        width: Math.round(result.checks.preview.outerCaptureScrollHeight ? await outerCapture.evaluate(el => el.scrollWidth * 2) : 0),
        height: Math.round(result.checks.preview.outerCaptureScrollHeight * 2),
      },
      expectedInnerCardDimensionsAtScale2: {
        width: Math.round(await innerCard.evaluate(el => el.scrollWidth * 2)),
        height: Math.round(result.checks.preview.cardScrollHeight * 2),
      },
    };

    const sentinels = Object.values(synthetic);
    await page.waitForTimeout(32000);
    const serializedNetwork = JSON.stringify(observation.network);
    result.checks.networkPrivacy = {
      requestCount: observation.network.filter(x => x.phase === 'request').length,
      requestUrls: [...new Set(observation.network.filter(x => x.phase === 'request').map(x => x.url))],
      sentinelsFoundInNetwork: sentinels.filter(s => serializedNetwork.includes(s)),
      telemetryPostBodies: observation.network.filter(x => x.phase === 'request' && x.postData).map(x => ({ url: x.url, postData: x.postData })),
      localStorage: await page.evaluate(() => ({ ...localStorage })),
    };

    const malformedPath = path.join(outputDir, `${label}-malformed.json`);
    fs.writeFileSync(malformedPath, '{not-json');
    const dialogs = [];
    page.once('dialog', async dialog => { dialogs.push({ type: dialog.type(), message: dialog.message() }); await dialog.accept(); });
    await page.locator('input[type="file"]').setInputFiles(malformedPath);
    await page.waitForTimeout(300);
    result.checks.malformedUpload = { dialogs };

    const invalidShapePath = path.join(outputDir, `${label}-invalid-shape.json`);
    fs.writeFileSync(invalidShapePath, JSON.stringify({
      complications: [{ id: 'bleeding', enabled: true }],
      medicalInfo: { name: '结构错误测试', bloodType: 'A型' },
      anticoagulation: {},
      currentMedications: {},
      emergencyContacts: [],
      hospitals: [],
      doctors: [],
    }));
    await page.locator('input[type="file"]').setInputFiles(invalidShapePath);
    await page.waitForTimeout(500);
    result.checks.invalidShapeUpload = {
      bodyTextAfterUpload: (await page.locator('body').innerText().catch(() => '')).slice(0, 3000),
      pageErrors: [...observation.pageErrors],
    };
  } catch (error) {
    result.errors.push({ stage: 'desktop-functional', error: String(error), stack: error?.stack });
    await screenshot(page, `${label}-failure-state`).catch(() => null);
  }
  result.observation = observation;
  saveJson(`${label}-desktop-result.json`, result);
  await context.close();
  return result;
}

async function mobileAudit(browser, label, url) {
  const context = await browser.newContext({ ...devices['iPhone 13'] });
  const page = await context.newPage();
  const observation = observePage(context, page);
  const result = { observation, steps: [], errors: [] };
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(1200);
    for (const [index, name] of [['home', null], ['medical', '消化道出血']]) {
      if (name) {
        await selectComplication(page, name);
        await page.getByRole('button', { name: /下一步/ }).click();
      }
      const stepResult = {
        name: index,
        viewport: await page.evaluate(() => ({ width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth, scrollHeight: document.documentElement.scrollHeight })),
        horizontalOverflow: await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth),
        axe: await runAxe(page, `${label}-mobile-${index}`),
      };
      result.steps.push(stepResult);
      await screenshot(page, `${label}-mobile-${index}`);
    }
    await page.locator('input[placeholder="请输入姓名"]').fill('移动端审计');
    await page.locator('select').first().selectOption({ label: 'A型' });
    await page.getByRole('button', { name: /下一步/ }).click();
    await page.getByRole('button', { name: '添加' }).first().click();
    await page.getByRole('button', { name: /下一步/ }).click();
    await page.waitForTimeout(350);
    result.steps.push({
      name: 'preview',
      horizontalOverflow: await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth),
      viewport: await page.evaluate(() => ({ width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth, scrollHeight: document.documentElement.scrollHeight })),
      cardWidth: await page.locator('div[style*="min-height"]').first().evaluate(el => el.scrollWidth),
      axe: await runAxe(page, `${label}-mobile-preview`),
    });
    await screenshot(page, `${label}-mobile-preview`);
  } catch (error) {
    result.errors.push({ error: String(error), stack: error?.stack });
    await screenshot(page, `${label}-mobile-failure`).catch(() => null);
  }
  saveJson(`${label}-mobile-result.json`, result);
  await context.close();
  return result;
}

async function aboutAudit(browser, label, url) {
  const { context, page, observation } = await openObserved(browser, url);
  const result = { observation, errors: [] };
  try {
    await page.getByRole('button', { name: /关于项目/ }).click();
    await page.waitForTimeout(250);
    const text = await page.locator('body').innerText();
    result.claims = {
      professionalAuthoritative: text.includes('专业医学指导，权威可靠'),
      localPrivacy: text.includes('数据本地处理，隐私安全'),
      personalizedPrecise: text.includes('个性化定制，精准匹配'),
      namedMedicalReviewersVisible: /医学专家团队/.test(text) && !/Dr\.|医生姓名|主任医师/.test(text),
      versionEntries: [...text.matchAll(/v\d+\.\d+\.\d+/g)].map(m => m[0]),
      claimsAiIntegration: text.includes('AI技术集成'),
    };
    result.axe = await runAxe(page, `${label}-about`);
    result.screenshot = await screenshot(page, `${label}-about`);
  } catch (error) {
    result.errors.push(String(error));
  }
  saveJson(`${label}-about-result.json`, result);
  await context.close();
  return result;
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const [label, url] of [['live', liveUrl], ['local', localUrl]]) {
      audit.runs[label] = {};
      audit.runs[label].statsFreshContexts = await statSnapshot(browser, url, 5);
      audit.runs[label].desktop = await desktopFunctionalAudit(browser, label, url);
      audit.runs[label].mobile = await mobileAudit(browser, label, url);
      audit.runs[label].about = await aboutAudit(browser, label, url);
    }
  } finally {
    await browser.close();
  }

  const allViolations = [];
  for (const target of Object.values(audit.runs)) {
    for (const section of [target.desktop?.axe, target.mobile?.steps?.reduce((acc, x) => ({ ...acc, [x.name]: x.axe }), {}), { about: target.about?.axe }]) {
      if (!section) continue;
      for (const report of Object.values(section)) {
        if (report?.violations) allViolations.push(...report.violations);
      }
    }
  }
  audit.summary = {
    uniqueAxeRuleIds: [...new Set(allViolations.map(x => x.id))],
    totalAxeViolationOccurrences: allViolations.length,
    liveNavigationError: audit.runs.live?.desktop?.observation?.navigationError || null,
    localNavigationError: audit.runs.local?.desktop?.observation?.navigationError || null,
    keyChecks: {
      keyboardSelectable: audit.runs.local?.desktop?.checks?.enterSelectsComplication,
      whitespaceNameAccepted: audit.runs.local?.desktop?.checks?.whitespaceNameAccepted,
      emptyContactAllowsProceed: audit.runs.local?.desktop?.checks?.emptyContactAllowsProceed,
      doctorOnlyAllowsProceed: audit.runs.local?.desktop?.checks?.doctorOnlyAllowsProceed,
      previewOmitsAllergies: audit.runs.local?.desktop?.checks?.preview?.containsAllergies === false,
      downloadedJsonContainsId: audit.runs.local?.desktop?.downloads?.config?.includesIdNumber,
      contradictoryAnticoagulantInstructions: audit.runs.local?.desktop?.checks?.preview?.hasContradictoryAnticoagulantInstructions,
    },
  };
  saveJson('audit-results.json', audit);

  const md = `# Tiny Red Card automated audit\n\nGenerated: ${now}\n\n- Live: ${liveUrl}\n- Local build: ${localUrl}\n- Axe rule IDs: ${audit.summary.uniqueAxeRuleIds.join(', ') || 'none recorded'}\n- Keyboard complication selection works: ${audit.summary.keyChecks.keyboardSelectable}\n- Whitespace-only name passes gate: ${audit.summary.keyChecks.whitespaceNameAccepted}\n- Empty contact passes step gate: ${audit.summary.keyChecks.emptyContactAllowsProceed}\n- Doctor alone passes step gate: ${audit.summary.keyChecks.doctorOnlyAllowsProceed}\n- Allergies omitted from rendered card: ${audit.summary.keyChecks.previewOmitsAllergies}\n- Downloaded JSON contains ID number: ${audit.summary.keyChecks.downloadedJsonContainsId}\n- Bleeding/thrombosis anticoagulant contradiction present: ${audit.summary.keyChecks.contradictoryAnticoagulantInstructions}\n\nSee audit-results.json and screenshots for full evidence.\n`;
  fs.writeFileSync(path.join(outputDir, 'AUTOMATED-AUDIT-SUMMARY.md'), md);
}

main().catch(error => {
  fs.writeFileSync(path.join(outputDir, 'runner-fatal-error.txt'), `${error?.stack || error}`);
  process.exitCode = 1;
});
