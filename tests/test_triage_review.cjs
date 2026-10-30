const { test } = require("node:test");
const assert = require("node:assert/strict");
const { buildTriageReviewPlan } = require("../issue_tracker/static/triage-review.js");

test("human corrections across pages override AI and preserve reviewed fingerprints", () => {
  const base = [{ number: 1, result: "非问题", previous_result: "", fingerprint: "new" },
    { number: 51, result: "确认问题", previous_result: "", fingerprint: "page-two" }];
  const edit = { number: 1, result: "确认问题", previous_result: "", fingerprint: "reviewed",
    batch_id: 5, batch_fingerprint: "reviewed-batch" };
  const result = buildTriageReviewPlan(base, new Map([[1, edit]]), true);
  assert.equal(result.length, 2);
  assert.deepEqual(result.find((item) => item.number === 1), edit);
  assert.equal(result.find((item) => item.number === 51).result, "确认问题");
  assert.equal(base[0].result, "非问题");
});

test("can correct a row whose AI value originally matched its saved value", () => {
  const edit = { number: 7, result: "非问题", previous_result: "确认问题", fingerprint: "original" };
  const edits = new Map([[7, edit]]);
  assert.deepEqual(buildTriageReviewPlan([], edits, false), [edit]);
  assert.deepEqual(buildTriageReviewPlan([], edits, true), []);
});

test("keeping the saved result cancels an AI overwrite", () => {
  const base = [{ number: 7, result: "非问题", previous_result: "确认问题" }];
  const edits = new Map([[7, { number: 7, result: "确认问题", previous_result: "确认问题" }]]);
  assert.deepEqual(buildTriageReviewPlan(base, edits, false), []);
});

test("does not produce writes until the batch plan has loaded", () => {
  const edits = new Map([[1, { number: 1, result: "待分析", previous_result: "" }]]);
  assert.deepEqual(buildTriageReviewPlan(null, edits, false), []);
});

test("human can choose hard to reproduce in the review plan", () => {
  const edit = { number: 7, result: "难以复现", previous_result: "", fingerprint: "reviewed" };
  assert.deepEqual(buildTriageReviewPlan([], new Map([[7, edit]]), true), [edit]);
});
