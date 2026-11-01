// 使用 Node 自带测试和 TypeScript 转译，验证停止期间的页面状态规则。
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

function load(name) {
  const filename = path.join(__dirname, "../src/lib", `${name}.ts`);
  const compiled = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  new Function("require", "module", "exports", compiled)((source) => {
    if (source === "./task-types") return load("task-types");
    throw new Error(`意外导入：${source}`);
  }, module, module.exports);
  return module.exports;
}

const { applyEvent, mergeTask, mergeExecutions, canCancelTask } = load("task-state");
function task(status = "running") {
  return {
    task_id: "test", title: "任务", prompt: "测试", attempt: 1, status,
    result: null, error: null, messages: [], draft: "已收到的部分文本", cursor: "1-0",
    interrupts: [], timeline: [], todos: null, planError: "", artifacts: [],
    created_at: "2026-10-31T00:00:00Z", updated_at: "2026-10-31T00:00:00Z",
  };
}
function event(name, data = {}) {
  return { id: "2-0", event: name, data: { attempt: 1, ...data } };
}

test("排队、运行、等待人工可停止，停止中不重复提交", () => {
  for (const status of ["queued", "running", "waiting_human"]) assert.equal(canCancelTask(status), true);
  for (const status of ["cancelling", "cancelled", "succeeded", "failed"]) assert.equal(canCancelTask(status), false);
});

test("取消请求进入停止中，不提前冒充已取消", () => {
  const current = applyEvent(task(), event("cancelling", { status: "cancelling" }));
  assert.equal(current.status, "cancelling");
  assert.equal(current.draft, "已收到的部分文本");
  assert.equal(current.timeline.at(-1).event, "cancelling");
});

test("停止中忽略晚到的运行、完成、失败和等待事件", () => {
  for (const name of ["started", "completed", "failed", "waiting_human"]) {
    const current = applyEvent(task("cancelling"), event(name, { error: "晚到错误", output: "晚到回答" }));
    assert.equal(current.status, "cancelling");
    assert.equal(current.error, null);
    assert.equal(current.result, null);
  }
});

test("已取消后不再追加晚到文本，但游标仍前进", () => {
  const current = applyEvent(task("cancelled"), event("text_delta", { text: "迟到文本" }));
  assert.equal(current.draft, "已收到的部分文本");
  assert.equal(current.cursor, "2-0");
});

test("旧 HTTP 响应不能覆盖停止状态，最终取消保留草稿", () => {
  const stale = mergeTask(task("cancelling"), task("running"));
  assert.equal(stale.status, "cancelling");
  const stopped = mergeTask(stale, task("cancelled"));
  assert.equal(stopped.status, "cancelled");
  assert.equal(stopped.draft, "已收到的部分文本");
  assert.equal(mergeTask(stopped, task("running")).status, "cancelled");
});

test("取消事件丢失时，状态事件仍能校准为停止中和已取消", () => {
  const requested = applyEvent(task(), event("state", { status: "cancelling" }));
  assert.equal(requested.status, "cancelling");
  assert.equal(applyEvent(requested, event("state", { status: "cancelled" })).status, "cancelled");
});

test("普通下一轮仍可正常更新，旧轮次不污染当前状态", () => {
  const next = mergeTask(task("succeeded"), { ...task("running"), attempt: 2 });
  assert.equal(next.attempt, 2);
  assert.equal(next.draft, "");
  assert.equal(applyEvent(next, event("cancelled")).status, "running");
});

test("停止后同轮次重新排队，旧取消响应不能覆盖新输入", () => {
  const stopped = task("cancelled");
  stopped.updated_at = "2026-10-31T00:00:00.000001Z";
  const queued = { ...task("queued"), updated_at: "2026-10-31T00:00:00.000002Z" };
  const next = mergeTask(stopped, queued);
  assert.equal(next.status, "queued");
  assert.equal(next.draft, "");
  assert.equal(mergeTask(next, stopped).status, "queued");
  assert.equal(applyEvent(next, event("cancelled", { updated_at: stopped.updated_at })).status, "queued");
  const running = applyEvent(next, event("started", { attempt: 2, updated_at: "2026-10-31T00:00:01Z" }));
  assert.equal(running.status, "running");
  assert.equal(applyEvent(running, event("text_delta", { text: "旧文本" })).draft, "");
});

test("另一页面提交新内容时，消息事件和状态同步也能解除停止状态", () => {
  for (const name of ["message_received", "state"]) {
    const next = applyEvent(task("cancelled"), event(name, {
      status: "queued", updated_at: "2026-10-31T00:00:01+00:00",
    }));
    assert.equal(next.status, "queued");
    assert.equal(next.draft, "");
  }
});

test("失败后接受新输入，清理旧错误；迟到失败和同轮次文本不能覆盖新请求", () => {
  const failed = { ...task("failed"), error: "图执行超限", updated_at: "2026-10-31T00:00:00.000001Z" };
  assert.equal(applyEvent(failed, event("text_delta", { text: "迟到文本" })).draft, failed.draft);
  assert.equal(mergeTask(failed, task("running")).status, "failed");
  const next = mergeTask(failed, { ...task("queued"), updated_at: "2026-10-31T00:00:00.000002Z" });
  assert.equal(next.status, "queued");
  assert.equal(next.error, null);
  assert.equal(next.draft, "");
  assert.equal(mergeTask(next, failed).status, "queued");
  assert.equal(applyEvent(next, event("failed", { error: "旧错误", updated_at: failed.updated_at })).status, "queued");
});

function execution(attempt, title, updated_at) {
  return { attempt, title, updated_at, created_at: updated_at, status: "running", todos: [], output: null, error: null };
}

test("本轮执行标题独立于会话标题，旧轮次标题不能覆盖新轮次", () => {
  const next = applyEvent({ ...task(), executions: [] }, event("execution_titled", {
    attempt: 2, status: "running", execution: execution(2, "检查上线风险", "2026-10-31T00:00:02Z"),
  }));
  assert.equal(next.title, "任务");
  assert.equal(next.executions[0].title, "检查上线风险");
  assert.equal(next.attempt, 2);
  const late = applyEvent(next, event("execution_titled", {
    execution: execution(1, "旧策划标题", "2026-10-31T00:00:03Z"),
  }));
  assert.equal(late.executions[0].title, "检查上线风险");
});

test("刷新返回的旧快照不覆盖新标题，历史轮次独立保留", () => {
  const first = execution(1, "编写地图策划", "2026-10-31T00:00:01Z");
  const second = execution(2, "检查上线风险", "2026-10-31T00:00:03Z");
  const records = mergeExecutions([second, first], [execution(2, "第 2 轮执行", "2026-10-31T00:00:02Z")]);
  assert.deepEqual(records.map((item) => item.title), ["检查上线风险", "编写地图策划"]);
});

test("成功后追加新输入时清空旧计划，不把上一轮步骤当作新计划", () => {
  const previous = { ...task("succeeded"), todos: [{ content: "旧步骤", status: "completed" }] };
  const next = mergeTask(previous, { ...task("queued"), updated_at: "2026-10-31T00:00:02Z" });
  assert.equal(next.todos, null);
});
