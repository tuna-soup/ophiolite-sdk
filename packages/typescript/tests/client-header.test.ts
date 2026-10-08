import test from "node:test";
import assert from "node:assert/strict";
import { Client, CLIENT_HEADER } from "../src/client.js";
import { server } from "./helpers.js";

test("every request names the package and carries only the caller's own valid trace", async () => {
  const seen: Array<Record<string, unknown>> = [];
  const app = await server((req, res) => { seen.push({ ...req.headers }); res.writeHead(200, { "Content-Type": "application/json" }); res.end("{}"); });
  try {
    const client = new Client(app.url, { mode: "none" });
    const trace = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01";
    await client.request("POST", "/api/v1/projects/{project}/activity/list", { project: "p" }, undefined, { project_id: "p" });
    await client.request("POST", "/api/v1/projects/{project}/activity/list", { project: "p" }, undefined, { project_id: "p" }, { traceparent: trace });
    await client.request("POST", "/api/v1/projects/{project}/activity/list", { project: "p" }, undefined, { project_id: "p" }, { traceparent: "00-" + "0".repeat(32) + "-b7ad6b7169203331-01" });
    assert.equal(CLIENT_HEADER, "ophiolite-typescript/0.1.0");
    assert.deepEqual(seen.map((h) => h["x-ophiolite-client"]), ["ophiolite-typescript/0.1.0", "ophiolite-typescript/0.1.0", "ophiolite-typescript/0.1.0"]);
    assert.deepEqual(seen.map((h) => h["traceparent"]), [undefined, trace, undefined]);
  } finally { await app.close(); }
});
