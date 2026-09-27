import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { validateDescriptor } from "../src/verify.js";

const contract = async (name: string) => JSON.parse(await readFile(new URL("../../../../ophiolite/contracts/assets/v1/fixtures/" + name, import.meta.url), "utf8"));

test("typed data (E11) is refused by the curve client instead of misread", async () => {
  for (const name of ["tops.json", "trajectory.json", "grid.json"]) {
    const value = await contract(name);
    assert.throws(() => validateDescriptor(value), /not a well log/);
  }
  assert.equal(validateDescriptor(await contract("source.json")).profile, "las2/1");
});
