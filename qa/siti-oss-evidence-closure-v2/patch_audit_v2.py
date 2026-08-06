#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from pathlib import Path

path = Path(os.environ.get("SITI_BROWSER_HARNESS", "runner/audit.mjs"))
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    text = text.replace(old, new, 1)


def sub_once(pattern: str, replacement: str, label: str, flags: int = 0) -> None:
    global text
    text, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{label}: expected one regex anchor, found {count}")


replace_once(
    "import { chromium } from 'playwright';",
    "import { chromium, devices } from 'playwright';",
    "Playwright device descriptors",
)

sub_once(
    r"const validExifJpeg = Buffer\.from\(\n.*?\n\);",
    "const validExifJpeg = fs.readFileSync(process.env.SITI_TRUE_EXIF_JPEG);",
    "standards-compliant EXIF fixture",
    re.S,
)

sub_once(
    r"async function clickTraining\(page\) \{.*?\n\}\n\nasync function selectLocation",
    """async function chooseReportType(page, reportType) {
  const className = reportType === 'training' ? 'training_btn' : 'real_btn';
  const button = page.locator(`button.${className}`).first();
  await button.waitFor({ state: 'visible', timeout: 15000 });
  await button.click();
}

async function selectLocation""",
    "real/training report selection",
    re.S,
)

replace_once(
    """  const context = await browser.newContext({
    viewport: scenario.viewport || { width: 1365, height: 900 },
    geolocation: { latitude: -6.175392, longitude: 106.827153 },
    permissions: ['geolocation'],
  });""",
    """  const deviceDescriptor = scenario.deviceName ? devices[scenario.deviceName] : {};
  const context = await browser.newContext({
    ...deviceDescriptor,
    viewport: scenario.viewport || deviceDescriptor.viewport || { width: 1365, height: 900 },
    geolocation: { latitude: -6.175392, longitude: 106.827153 },
    permissions: ['geolocation'],
  });""",
    "mobile device emulation",
)

replace_once(
    """  const s3Uploads = [];
  let reportPutCount = 0;""",
    """  const s3Uploads = [];
  const storageResponses = [];
  const reportPayloads = [];
  let reportPutCount = 0;""",
    "storage responses and report payloads",
)

replace_once(
    """  page.on('response', async response => {
    if (response.url().startsWith(apiURL)) {
      let body = null;
      try { body = await response.clone().json(); } catch {}
      network.push({ phase: 'response', status: response.status(), url: response.url(), body });
    }
  });""",
    """  page.on('response', async response => {
    if (response.url().startsWith(apiURL)) {
      let body = null;
      try { body = await response.clone().json(); } catch {}
      network.push({ phase: 'response', status: response.status(), url: response.url(), body });
    }
    if (objectStorageOrigin && response.url().startsWith(objectStorageOrigin)) {
      storageResponses.push({
        status: response.status(),
        url: response.url(),
        contentType: response.headers()['content-type'] || null,
      });
    }
  });""",
    "storage response capture",
)

replace_once(
    """    if (url.origin === apiURL && url.pathname === `/cards/${cardId}` && method === 'PUT') {
      reportPutCount += 1;""",
    """    if (url.origin === apiURL && url.pathname === `/cards/${cardId}` && method === 'PUT') {
      reportPutCount += 1;
      try {
        reportPayloads.push(JSON.parse(request.postData() || '{}'));
      } catch {
        reportPayloads.push({ parseError: true, raw: request.postData() });
      }""",
    "report payload capture",
)

replace_once(
    """        containsAuditGPS: bytes ? bytes.includes(Buffer.from('SITI_AUDIT_GPSLatitude')) : false,
        containsHTMLScript: bytes ? bytes.includes(Buffer.from('<html><script>')) : false,
        prefixHex: bytes?.subarray(0, 80).toString('hex') || '',
      });""",
    """        containsAuditGPS: bytes ? bytes.includes(Buffer.from('SITI_AUDIT_GPSLatitude')) : false,
        containsExifHeader: bytes ? bytes.includes(Buffer.from('Exif\\0\\0', 'binary')) : false,
        containsHTMLScript: bytes ? bytes.includes(Buffer.from('<html><script>')) : false,
        prefixHex: bytes?.subarray(0, 160).toString('hex') || '',
      });
      if (bytes) {
        fs.writeFileSync(path.join(outDir, `${scenario.id}-storage-upload-${s3Uploads.length}.bin`), bytes);
      }""",
    "EXIF and upload-byte capture",
)

replace_once(
    """    await page.goto(`${appURL}/${cardId}/flood?lang=en`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(900);
    await clickTraining(page);""",
    """    await page.goto(`${appURL}/${cardId}/flood?lang=en`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(900);
    result.clientProfile = await page.evaluate(() => ({
      userAgent: navigator.userAgent,
      maxTouchPoints: navigator.maxTouchPoints,
      innerWidth: window.innerWidth,
      innerHeight: window.innerHeight,
      coarsePointer: window.matchMedia('(pointer: coarse)').matches,
      hoverNone: window.matchMedia('(hover: none)').matches,
    }));
    await chooseReportType(page, scenario.reportType || 'real');""",
    "client profile and explicit report type",
)

replace_once(
    """  result.reportPutCount = reportPutCount;
  result.reportPatchCount = reportPatchCount;""",
    """  result.reportPutCount = reportPutCount;
  result.reportPatchCount = reportPatchCount;
  result.reportPayloads = reportPayloads;
  result.storageResponses = storageResponses;
  result.selectedReportType = scenario.reportType || 'real';""",
    "result payload/profile fields",
)

sub_once(
    r"""  const scenarios = \[
.*?
  \];""",
    """  const scenarios = [
    { id: 'real-desktop-success', reportType: 'real' },
    {
      id: 'real-mobile-device-success',
      reportType: 'real',
      deviceName: 'iPhone 13',
      viewport: { width: 390, height: 844 },
    },
    { id: 'training-desktop-success', reportType: 'training' },
    { id: 'double-submit-real', reportType: 'real', doubleSubmit: true },
    {
      id: 'network-drop-before-server-real',
      reportType: 'real',
      abortBeforeServer: true,
      retryAfterFailure: true,
    },
    {
      id: 'accepted-response-lost-real',
      reportType: 'real',
      acceptedThenLost: true,
      retryAfterFailure: true,
    },
    { id: 'valid-image-real', reportType: 'real', uploadMode: 'valid' },
    { id: 'disguised-image-real', reportType: 'real', uploadMode: 'disguised' },
    { id: 'oversized-image-real', reportType: 'real', uploadMode: 'oversized' },
    { id: 'true-exif-gps-image-real', reportType: 'real', uploadMode: 'exif' },
  ];""",
    "v2 scenario matrix",
    re.S,
)

sub_once(
    r"""  const assertions = \{
.*?
  \};
  const summary = \{""",
    """  const realDesktop = byId['real-desktop-success'];
  const realMobile = byId['real-mobile-device-success'];
  const trainingDesktop = byId['training-desktop-success'];
  const validImage = byId['valid-image-real'];
  const trueExif = byId['true-exif-gps-image-real'];
  const payloadTrainingFlag = result => result?.reportPayloads?.[0]?.is_training;
  const assertions = {
    real_desktop_success: Boolean(
      realDesktop?.reportPersisted &&
      realDesktop?.errors.length === 0 &&
      payloadTrainingFlag(realDesktop) === false
    ),
    real_mobile_device_success: Boolean(
      realMobile?.reportPersisted &&
      realMobile?.errors.length === 0 &&
      payloadTrainingFlag(realMobile) === false &&
      /iPhone/.test(realMobile?.clientProfile?.userAgent || '') &&
      realMobile?.clientProfile?.maxTouchPoints > 0 &&
      realMobile?.clientProfile?.coarsePointer === true &&
      realMobile?.clientProfile?.innerWidth === 390 &&
      realMobile?.clientProfile?.innerHeight === 844
    ),
    training_mode_success: Boolean(
      trainingDesktop?.reportPersisted &&
      trainingDesktop?.errors.length === 0 &&
      payloadTrainingFlag(trainingDesktop) === true
    ),
    double_submit_one_put: Boolean(
      byId['double-submit-real']?.reportPutCount === 1 &&
      byId['double-submit-real']?.reportPersisted
    ),
    network_drop_retry: Boolean(
      byId['network-drop-before-server-real']?.submitEvidence?.retried &&
      byId['network-drop-before-server-real']?.reportPersisted &&
      byId['network-drop-before-server-real']?.reportPutCount === 2
    ),
    accepted_response_loss_reconciled: Boolean(
      byId['accepted-response-lost-real']?.acceptedThenLost?.status === 200 &&
      byId['accepted-response-lost-real']?.reportPersisted &&
      /\\/thank(?:\\?|$)/.test(byId['accepted-response-lost-real']?.finalURL || '')
    ),
    valid_image_real_storage: Boolean(
      validImage?.s3Uploads.length === 1 &&
      validImage?.storageResponses.some(response => response.status >= 200 && response.status < 300) &&
      /\\.png$/.test(validImage?.reportImageURL || '')
    ),
    signed_content_type_bound: Boolean(
      validImage?.s3Uploads[0]?.signedHeaders?.includes('content-type')
    ),
    disguised_image_blocked: byId['disguised-image-real']?.s3Uploads.length === 0,
    oversized_image_blocked: byId['oversized-image-real']?.s3Uploads.length === 0,
    true_exif_gps_removed: Boolean(
      trueExif?.s3Uploads.length === 1 &&
      trueExif?.storageResponses.some(response => response.status >= 200 && response.status < 300) &&
      !trueExif?.s3Uploads[0]?.containsExifHeader &&
      !trueExif?.s3Uploads[0]?.containsAuditGPS
    ),
    no_page_errors: results.every(result => result.pageErrors.length === 0),
    no_flow_errors: results.every(result => result.errors.length === 0),
  };
  const summary = {""",
    "v2 assertions",
    re.S,
)

sub_once(
    r"""    scenarioResults: results\.map\(result => \(\{
.*?
    \}\)\),""",
    """    scenarioResults: results.map(result => ({
      id: result.scenario.id,
      reportType: result.selectedReportType,
      deviceName: result.scenario.deviceName || null,
      viewport: {
        width: result.clientProfile?.innerWidth || result.scenario.viewport?.width || 1365,
        height: result.clientProfile?.innerHeight || result.scenario.viewport?.height || 900,
      },
      clientProfile: result.clientProfile,
      errors: result.errors.length,
      finalURL: result.finalURL,
      reportPutCount: result.reportPutCount,
      reportPatchCount: result.reportPatchCount,
      reportPayloads: result.reportPayloads,
      reportPersisted: result.reportPersisted,
      reportImageURL: result.reportImageURL,
      acceptedThenLost: result.acceptedThenLost,
      imageErrors: result.imageErrors,
      s3Uploads: result.s3Uploads,
      storageResponses: result.storageResponses,
      pageErrors: result.pageErrors,
    })),""",
    "v2 summary fields",
    re.S,
)

path.write_text(text, encoding="utf-8")
print({"status": "evidence closure v2 browser harness patched", "path": str(path)})
