/* Run with: node -r babel-register notification_idempotency.js */
const fs = require('fs');
const path = require('path');
const AWS = require('aws-sdk');

const outDir = path.resolve(process.env.SITI_VALIDATION_OUT || 'artifacts/notification-validation');
fs.mkdirSync(outDir, { recursive: true });

const publishCalls = [];
AWS.SNS.prototype.publish = function(payload, callback) {
  publishCalls.push({ payload, at: Date.now() });
  setImmediate(() => callback(null, { MessageId: `audit-${publishCalls.length}` }));
};

const sourceRoot = path.resolve(process.env.NOTIFICATION_SOURCE);
const Notify = require(path.join(sourceRoot, 'src/functions/notify/Notify.js')).default;
const params = {
  instanceRegionCode: 'ID-JK',
  language: 'en',
  network: 'twitter',
  reportId: 424242,
  username: 'synthetic-audit-user',
};

async function main() {
  const notify = new Notify('ap-southeast-1', '000000000000');

  publishCalls.length = 0;
  await notify.send({ ...params });
  await notify.send({ ...params });
  const sequential = publishCalls.map((item, index) => ({ index: index + 1, topic: item.payload.TopicArn, message: item.payload.Message }));

  publishCalls.length = 0;
  const concurrentAttempts = 50;
  const concurrentResults = await Promise.allSettled(Array.from({ length: concurrentAttempts }, () => notify.send({ ...params })));
  const concurrent = {
    attempts: concurrentAttempts,
    fulfilled: concurrentResults.filter(item => item.status === 'fulfilled').length,
    rejected: concurrentResults.filter(item => item.status === 'rejected').length,
    publish_call_count: publishCalls.length,
    unique_payload_count: new Set(publishCalls.map(item => JSON.stringify(item.payload))).size,
  };

  publishCalls.length = 0;
  const handler = require(path.join(sourceRoot, 'src/functions/notify/index.js')).default;
  const event = { body: JSON.stringify(params) };
  function invokeHandler() {
    return new Promise(resolve => handler(event, {}, (_error, response) => resolve(response)));
  }
  const handlerResults = await Promise.all([invokeHandler(), invokeHandler()]);
  const handlerDuplicate = { invocations: 2, publish_call_count: publishCalls.length, responses: handlerResults };

  const result = {
    generated_at: new Date().toISOString(),
    scope: 'exact public notification source with AWS SNS publish mocked; no real messages sent',
    sequential_identical_calls: { attempts: 2, publish_call_count: sequential.length, calls: sequential },
    concurrent_identical_calls: concurrent,
    duplicate_lambda_event: handlerDuplicate,
    interpretation: concurrent.publish_call_count === 1 ? 'deduplicated' : 'no source-level idempotency observed',
  };
  fs.writeFileSync(path.join(outDir, 'notification-idempotency.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
}

main().catch(error => {
  fs.writeFileSync(path.join(outDir, 'fatal-error.txt'), error.stack || String(error));
  process.exitCode = 1;
});
