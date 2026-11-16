const TAG_PATTERN = /^[\w\u4e00-\u9fff-]{1,64}$/u;
const RESERVED_TAGS = new Set(["and", "or"]);

export const TAG_RULE_TEXT = "仅允许中文、字母、数字、下划线和短横线；不能使用 AND/OR、&、|、括号等特殊字符";

export function parseTags(text: string): string[] {
  return Array.from(new Set(text.split(",").map((item) => item.trim()).filter(Boolean)));
}

export function tagValidationError(text: string): string | null {
  for (const tag of parseTags(text)) {
    if (RESERVED_TAGS.has(tag.toLowerCase())) {
      return `标签「${tag}」是保留字，不能使用 AND/OR`;
    }
    if (!TAG_PATTERN.test(tag)) {
      return `标签「${tag}」含非法字符，${TAG_RULE_TEXT}`;
    }
  }
  return null;
}
