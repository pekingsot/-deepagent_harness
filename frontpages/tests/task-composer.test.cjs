// 不安装额外渲染依赖：替代 React 状态存储，验证生产草稿 Hook 的跨会话行为。
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

function composer() {
  let state;
  const react = {
    useState(initial) {
      if (state === undefined) state = initial;
      return [state, (update) => { state = typeof update === "function" ? update(state) : update; }];
    },
  };
  const source = fs.readFileSync(path.join(__dirname, "../src/hooks/use-task-composer.ts"), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  new Function("require", "module", "exports", compiled)((name) => {
    assert.equal(name, "react");
    return react;
  }, module, module.exports);
  return (id, identity = "tenant:user") => module.exports.useTaskComposer(identity, id);
}

test("A 输入不会带入 B，切回各自恢复草稿", () => {
  const render = composer();
  render("A").setPrompt("A 的未发送内容");
  assert.equal(render("B").prompt, "");
  render("B").setPrompt("B 的内容");
  assert.equal(render("A").prompt, "A 的未发送内容");
  assert.equal(render("B").prompt, "B 的内容");
});

test("A 提交后切到 B，A 的迟到成功回调只清空 A", async () => {
  const render = composer();
  render("A").setPrompt("提交 A");
  const submitting = render("A");
  let finish;
  const request = new Promise((resolve) => { finish = resolve; });
  const completion = request.then(() => submitting.setPrompt(""));
  render("B").setPrompt("B 的新草稿");
  finish();
  await completion;
  assert.equal(render("B").prompt, "B 的新草稿");
  assert.equal(render("A").prompt, "");
});

test("新建任务只清空新任务输入区，账号草稿相互隔离", () => {
  const render = composer();
  render("A").setPrompt("A 的草稿");
  render(null).setPrompt("新任务草稿");
  assert.equal(render("A", "other:user").prompt, "");
  render("A").clearNewDraft();
  assert.equal(render("A").prompt, "A 的草稿");
  assert.equal(render(null).prompt, "");
});
