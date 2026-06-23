// Smoke tests for the JavaScript port — uses the built-in node:test runner.
//   node --test ports/javascript/test.js
import { test } from "node:test";
import assert from "node:assert/strict";
import { diffFiles, hasBreaking, summarize } from "./index.js";

const codes = (cs) => new Set(cs.map((c) => c.code));

test("removed path is breaking", () => {
  const c = diffFiles(
    '{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{}}}}}',
    '{"openapi":"3.0.0","paths":{}}');
  assert.ok(hasBreaking(c));
  assert.ok(codes(c).has("path.removed"));
});

test("new required param is breaking", () => {
  const c = diffFiles(
    '{"openapi":"3.0.0","paths":{"/a":{"get":{"parameters":[],"responses":{}}}}}',
    '{"openapi":"3.0.0","paths":{"/a":{"get":{"parameters":[{"name":"q","in":"query","required":true}],"responses":{}}}}}');
  assert.ok(codes(c).has("param.added.required"));
});

test("added optional param is not breaking", () => {
  const c = diffFiles(
    '{"openapi":"3.0.0","paths":{"/a":{"get":{"parameters":[],"responses":{}}}}}',
    '{"openapi":"3.0.0","paths":{"/a":{"get":{"parameters":[{"name":"q","in":"query","required":false}],"responses":{}}}}}');
  assert.ok(!hasBreaking(c));
});

test("response property removal is breaking", () => {
  const mk = (props) => JSON.stringify({ openapi: "3.0.0", paths: { "/a": { get: { responses: { "200": { content: { "application/json": { schema: { properties: props } } } } } } } } });
  const c = diffFiles(mk({ x: { type: "string" } }), mk({}));
  assert.ok(codes(c).has("response.property.removed"));
});

test("identical docs yield no changes", () => {
  const d = '{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{}}}}}';
  assert.equal(diffFiles(d, d).length, 0);
});

test("dropped 2xx status code is breaking", () => {
  const c = diffFiles(
    '{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{"200":{},"206":{}}}}}}',
    '{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{"200":{}}}}}}');
  assert.ok(codes(c).has("response.removed"));
});

test("added path is info only", () => {
  const c = diffFiles(
    '{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{}}}}}',
    '{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{}}},"/b":{"get":{"responses":{}}}}}');
  assert.ok(!hasBreaking(c));
  assert.ok(codes(c).has("path.added"));
});

test("summary counts severities", () => {
  const c = diffFiles(
    '{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{}}},"/gone":{"get":{"responses":{}}}}}',
    '{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{}}},"/new":{"get":{"responses":{}}}}}');
  const s = summarize(c);
  assert.ok(s.breaking >= 1);
  assert.ok(s.info >= 1);
  assert.equal(s.total, c.length);
});

test("requestBody field becoming required is breaking", () => {
  const mk = (req) => JSON.stringify({ openapi: "3.0.0", paths: { "/a": { post: { requestBody: { content: { "application/json": { schema: { required: req, properties: { name: { type: "string" } } } } } }, responses: {} } } } });
  const c = diffFiles(mk([]), mk(["name"]));
  assert.ok(codes(c).has("requestBody.required.added"));
});
