/* Team chat assistant mention. The interface shows "@助手"; the backend
 * listens for "@AI". Both are accepted when typed. */

const LEADING_MENTION = /^@(助手|AI)/;

export function hasAssistantMention(text: string): boolean {
  return LEADING_MENTION.test(text);
}

export function toSendableMention(text: string): string {
  return text.replace(/^@助手/, "@AI");
}

export function toggleAssistantMention(text: string): string {
  return hasAssistantMention(text) ? text.replace(/^@(助手|AI)\s?/, "") : `@助手 ${text}`;
}
