import test from "node:test";
import assert from "node:assert/strict";
import { Client, story, whatChanged, dependents, remake, remakeSave } from "../src/client.js";
import { fixture, server } from "./helpers.js";

// E94 C5: the four functions send the bodies Python sends and return the same answers (tests/fixtures/story/exchanges.json,
// asserted by tests/test_story_client.py for Python).
test("story, whatChanged, dependents and remake equal Python on the shared exchanges", async () => {
  const { exchanges } = await fixture("fixtures/story/exchanges.json");
  const seen: { path: string; body: unknown }[] = [];
  let next = 0;
  const app = await server((req, res) => {
    const parts: Uint8Array[] = []; req.on("data", (chunk: Uint8Array) => { parts.push(chunk); });
    req.on("end", () => {
      seen.push({ path: req.url ?? "", body: JSON.parse(parts.map(part => new TextDecoder().decode(part)).join("")) });
      res.writeHead(200, { "Content-Type": "application/json" }); res.end(JSON.stringify(exchanges[next++].response));
    });
  });
  try {
    const client = new Client(app.url, { mode: "none" });
    const R = "a".repeat(64);
    const got = [
      await story(client, "p", "a-shale", R, { limit: 5 }),
      await whatChanged(client, "p", { asset_id: "a-shale", revision: "d".repeat(64) }, { asset_id: "a-shale", revision: R }),
      await dependents(client, "p", "a-shale", R),
      await remake(client, "p", "a-shale", R, { step: "preview", inputs: "newer" }),
      await remake(client, "p", "a-shale", R, { step: "run", inputs: [{ slot: "gamma", asset_id: "a-gr", revision: "c".repeat(64) }], command_id: "k1" }),
      await remake(client, "p", "a-shale", R, { step: "status", execution_id: "e1" }),
      await remakeSave(client, "p", "e1", [{ role: "vshale", target: "new-version", command_id: "k1-0", audience_digest: "f".repeat(64) }]),
    ];
    assert.equal(seen.length, exchanges.length);
    exchanges.forEach((e: any, i: number) => {
      assert.deepEqual(seen[i], { path: e.path, body: e.request });
      assert.deepEqual(got[i], e.response);
    });
  } finally { await app.close(); }
});

test("a run without a command id and a save without a target are refused before any request", async () => {
  const client = new Client("http://127.0.0.1:9", { mode: "none" });
  assert.throws(() => remake(client, "p", "a", "r", { step: "run", inputs: [], command_id: "" }));
  assert.throws(() => remakeSave(client, "p", "e1", []));
  assert.throws(() => remakeSave(client, "p", "e1", [{ role: "v", target: "replace" as "new-result", command_id: "k" }]));
});
