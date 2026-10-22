import assert from "node:assert/strict";
import test from "node:test";

import { hasAssistantMention, toSendableMention, toggleAssistantMention } from "./assistantMention.ts";

test("a message that opens with @助手 or @AI asks the assistant", () => {
  assert.equal(hasAssistantMention("@助手 週二 8x400"), true);
  assert.equal(hasAssistantMention("@AI 週二 8x400"), true);
  assert.equal(hasAssistantMention("週二跑 8x400"), false);
  assert.equal(hasAssistantMention("問一下 @AI 好嗎"), false);
});

test("@助手 is sent as @AI so the server still recognises it", () => {
  assert.equal(toSendableMention("@助手 週二 8x400"), "@AI 週二 8x400");
  assert.equal(toSendableMention("@助手週二 8x400"), "@AI週二 8x400");
  assert.equal(toSendableMention("@AI 週二 8x400"), "@AI 週二 8x400");
  assert.equal(toSendableMention("今天跑得很順 @助手"), "今天跑得很順 @助手");
});

test("the toggle inserts @助手 and removes either spelling", () => {
  assert.equal(toggleAssistantMention("週二 8x400"), "@助手 週二 8x400");
  assert.equal(toggleAssistantMention(""), "@助手 ");
  assert.equal(toggleAssistantMention("@助手 週二 8x400"), "週二 8x400");
  assert.equal(toggleAssistantMention("@AI 週二 8x400"), "週二 8x400");
});
