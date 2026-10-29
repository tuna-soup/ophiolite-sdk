import test from "node:test";
import assert from "node:assert/strict";
import { Client, PermissionRefused, IntegrityConflict, RightsEnded, RightsConflict, Refused, rights, attachRights, renewRights } from "../src/client.js";

// E35a C3 (test 8): a rights refusal is its own category, with the server's sentence and the last permitted day.
const sentence = "The rights to use this data ended after 30 June 2099. Ask the project administrator to renew them.";
const answer = (status: number, body: unknown) => new Client("https://example.invalid", { mode: "none" }, async () => new Response(JSON.stringify(body), { status }));

test("rights-ended carries the sentence and the last day, and is still a permission refusal", async () => {
  const client = answer(403, { error: sentence, code: "rights-ended", message: sentence, last_day: "2099-06-30", remedy: "Ask.", docs: "/docs/reference/errors/#rights-ended", request_id: "req_1" });
  await assert.rejects(client.request("GET", "/api/v1/contracts", {}), (error: unknown) => {
    assert(error instanceof RightsEnded && error instanceof PermissionRefused);
    assert.equal(error.message, sentence); assert.equal(error.lastDay, "2099-06-30"); assert.equal(error.code, "rights-ended");
    return true;
  });
});

test("a malformed last day is dropped; rights-conflict is an integrity conflict", async () => {
  await assert.rejects(answer(403, { code: "rights-ended", message: sentence, last_day: "30/06/2099" }).request("GET", "/api/v1/contracts", {}),
    (error: unknown) => error instanceof RightsEnded && error.lastDay === undefined);
  await assert.rejects(answer(409, { code: "rights-conflict", message: "The rights changed; reload before saving" }).request("GET", "/api/v1/contracts", {}),
    (error: unknown) => error instanceof RightsConflict && error instanceof IntegrityConflict && error.message === "The rights changed; reload before saving");
});

test("any other refusal keeps its status category and never shows the server's words", async () => {
  await assert.rejects(answer(403, { code: "PERMISSION_DENIED", message: "private" }).request("GET", "/api/v1/contracts", {}),
    (error: unknown) => error instanceof PermissionRefused && !(error instanceof RightsEnded) && !String((error as Error).message).includes("private"));
});

test("rights, attachRights and renewRights post to the three rights routes; a target that names nothing is refused first", async () => {
  const seen: Array<[string, unknown]> = [];
  const client = new Client("https://example.invalid", { mode: "none" }, async (url, init) => {
    seen.push([new URL(String(url)).pathname, JSON.parse(String(init?.body))]);
    return new Response(JSON.stringify({ basis: null, can_change: true }), { status: 200 });
  });
  await rights(client, "p", { target_kind: "connection", target_ref: "c1", key: "curve" });
  await attachRights(client, "p", { target_kind: "upload", target_ref: "a1" }, { uses: ["read"], last_day: "2026-12-31" });
  await renewRights(client, "p", { target_kind: "release", target_ref: "r1" }, { uses: ["read", "export"], last_day: "2027-01-31", expected_generation: 2 });
  assert.deepEqual(seen, [
    ["/api/v1/projects/p/rights/get", { project_id: "p", target_kind: "connection", target_ref: "c1", key: "curve" }],
    ["/api/v1/projects/p/rights/attach", { project_id: "p", target_kind: "upload", target_ref: "a1", uses: ["read"], last_day: "2026-12-31" }],
    ["/api/v1/projects/p/rights/renew", { project_id: "p", target_kind: "release", target_ref: "r1", uses: ["read", "export"], last_day: "2027-01-31", expected_generation: 2 }],
  ]);
  assert.throws(() => rights(client, "p", { target_kind: "connection", target_ref: "c1" } as never), Refused);
  assert.throws(() => rights(client, "p", { target_kind: "upload", target_ref: "" }), Refused);
  assert.equal(seen.length, 3);
});
