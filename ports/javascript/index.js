#!/usr/bin/env node
// JavaScript / Node port of the apidiff OpenAPI breaking-change engine.
// Mirrors the Python reference CLI surface:
//   node index.js diff OLD.json NEW.json [--format table|json]
// Exit code 1 when breaking changes are found, else 0 (2 on IO/usage error).
// Pure stdlib, no dependencies. Passive, read-only, offline.
import { readFileSync } from "fs";
import { pathToFileURL } from "url";

const BREAKING = "BREAKING";
const WARNING = "WARNING";
const INFO = "INFO";

const METHODS = ["get", "put", "post", "delete", "patch", "head", "options"];

// ---- engine --------------------------------------------------------------
export function diffOpenapi(oldDoc, newDoc) {
  const changes = [];
  const add = (severity, code, location, message) =>
    changes.push({ severity, code, location, message });

  const oldPaths = oldDoc.paths || {};
  const newPaths = newDoc.paths || {};

  for (const p of Object.keys(oldPaths))
    if (!(p in newPaths)) add(BREAKING, "path.removed", p, `Path '${p}' was removed`);
  for (const p of Object.keys(newPaths))
    if (!(p in oldPaths)) add(INFO, "path.added", p, `Path '${p}' was added`);

  for (const p of Object.keys(oldPaths)) {
    if (!(p in newPaths)) continue;
    const oldItem = oldPaths[p] || {};
    const newItem = newPaths[p] || {};
    for (const m of METHODS) {
      const oldOp = oldItem[m];
      const newOp = newItem[m];
      const loc = `${m.toUpperCase()} ${p}`;
      if (oldOp && !newOp) { add(BREAKING, "operation.removed", loc, `Operation '${loc}' was removed`); continue; }
      if (newOp && !oldOp) { add(INFO, "operation.added", loc, `Operation '${loc}' was added`); continue; }
      if (!oldOp || !newOp) continue;
      diffOperation(add, loc, oldOp, newOp);
    }
  }
  return changes;
}

function paramsIndex(op) {
  const out = {};
  for (const p of op.parameters || [])
    if (p && p.name) out[`${p.name} ${p.in || "query"}`] = p;
  return out;
}

function bodySchema(op) {
  const rb = op.requestBody;
  if (!rb || typeof rb !== "object") return null;
  const content = rb.content || {};
  for (const ct of ["application/json", ...Object.keys(content)]) {
    const media = content[ct];
    if (media && typeof media === "object" && "schema" in media) return media.schema;
  }
  return null;
}

function successResponseSchema(op) {
  const responses = op.responses || {};
  for (const code of ["200", "201", "2XX", "default"]) {
    const resp = responses[code];
    if (resp && typeof resp === "object") {
      const media = (resp.content || {})["application/json"];
      if (media && typeof media === "object" && "schema" in media) return media.schema;
    }
  }
  return null;
}

function diffProps(add, loc, scope, oldProps, newProps, removedBreaking) {
  for (const name of Object.keys(oldProps)) {
    if (!(name in newProps)) {
      add(removedBreaking ? BREAKING : WARNING, `${scope}.property.removed`, loc,
        `${scope} property '${name}' was removed`);
      continue;
    }
    const ot = (oldProps[name] || {}).type;
    const nt = (newProps[name] || {}).type;
    if (ot && nt && ot !== nt)
      add(BREAKING, `${scope}.property.type.changed`, loc,
        `${scope} property '${name}' type changed: ${ot} -> ${nt}`);
  }
  for (const name of Object.keys(newProps))
    if (!(name in oldProps))
      add(INFO, `${scope}.property.added`, loc, `${scope} property '${name}' was added`);
}

function diffOperation(add, loc, oldOp, newOp) {
  const oldParams = paramsIndex(oldOp);
  const newParams = paramsIndex(newOp);

  for (const key of Object.keys(oldParams))
    if (!(key in newParams)) {
      const [name, where] = key.split(" ");
      add(WARNING, "param.removed", loc, `Parameter '${name}' (in: ${where}) was removed`);
    }
  for (const key of Object.keys(newParams)) {
    const [name, where] = key.split(" ");
    const p = newParams[key];
    if (!(key in oldParams)) {
      if (p.required) add(BREAKING, "param.added.required", loc, `New required parameter '${name}' (in: ${where}) added`);
      else add(INFO, "param.added", loc, `New optional parameter '${name}' (in: ${where}) added`);
    } else {
      const oldP = oldParams[key];
      if (p.required && !oldP.required) add(BREAKING, "param.required.added", loc, `Parameter '${name}' (in: ${where}) became required`);
      else if (oldP.required && !p.required) add(INFO, "param.required.removed", loc, `Parameter '${name}' (in: ${where}) is no longer required`);
    }
  }

  const oldBody = bodySchema(oldOp);
  const newBody = bodySchema(newOp);
  if (oldBody && newBody) {
    const oldReq = new Set(oldBody.required || []);
    const newReq = new Set(newBody.required || []);
    for (const f of [...newReq].filter((x) => !oldReq.has(x)).sort())
      add(BREAKING, "requestBody.required.added", loc, `Request body field '${f}' became required`);
    for (const f of [...oldReq].filter((x) => !newReq.has(x)).sort())
      add(INFO, "requestBody.required.removed", loc, `Request body field '${f}' is no longer required`);
    diffProps(add, loc, "requestBody", oldBody.properties || {}, newBody.properties || {}, false);
  }

  const oldResp = successResponseSchema(oldOp);
  const newResp = successResponseSchema(newOp);
  if (oldResp && newResp)
    diffProps(add, loc, "response", oldResp.properties || {}, newResp.properties || {}, true);

  const oldCodes = new Set(Object.keys(oldOp.responses || {}));
  const newCodes = new Set(Object.keys(newOp.responses || {}));
  for (const code of [...oldCodes].filter((c) => !newCodes.has(c)).sort())
    if (code.startsWith("2")) add(BREAKING, "response.removed", loc, `Success response '${code}' was removed`);
}

export function summarize(changes) {
  const counts = { BREAKING: 0, WARNING: 0, INFO: 0 };
  for (const c of changes) counts[c.severity]++;
  return { total: changes.length, breaking: counts.BREAKING, warning: counts.WARNING, info: counts.INFO };
}

export function diffFiles(oldText, newText) {
  return diffOpenapi(JSON.parse(oldText), JSON.parse(newText));
}

export function hasBreaking(changes) {
  return changes.some((c) => c.severity === BREAKING);
}

// ---- CLI -----------------------------------------------------------------
function renderTable(changes) {
  const s = summarize(changes);
  const lines = [
    "format: openapi",
    `changes: ${s.total}  breaking: ${s.breaking}  warning: ${s.warning}  info: ${s.info}`,
    "",
  ];
  if (!changes.length) { lines.push("No changes detected."); return lines.join("\n"); }
  const order = { BREAKING: 0, WARNING: 1, INFO: 2 };
  for (const c of [...changes].sort((a, b) => order[a.severity] - order[b.severity]))
    lines.push(`  [${c.severity.padEnd(8)}] ${c.location}  ${c.message}`);
  return lines.join("\n");
}

function main(argv) {
  if (argv[0] !== "diff" || argv.length < 3) {
    console.error("usage: node index.js diff OLD NEW [--format table|json]");
    return 2;
  }
  const oldPath = argv[1];
  const newPath = argv[2];
  const fmt = argv.includes("--format") ? argv[argv.indexOf("--format") + 1] : "table";
  let changes;
  try {
    changes = diffFiles(readFileSync(oldPath, "utf8"), readFileSync(newPath, "utf8"));
  } catch (e) {
    console.error(`error: ${e.message}`);
    return 2;
  }
  if (fmt === "json") console.log(JSON.stringify({ format: "openapi", summary: summarize(changes), changes }, null, 2));
  else console.log(renderTable(changes));
  return hasBreaking(changes) ? 1 : 0;
}

// Run as CLI when invoked directly (cross-platform entry-point check).
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exit(main(process.argv.slice(2)));
}
