// @vitest-environment node
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? sources(join(directory, entry.name)) : [join(directory, entry.name)]);
}
it("exposes only the public API origin and never imports backend secrets or test fixtures", () => {
  const source = sources("src").map(file => readFileSync(file, "utf8")).join("\n");
  const config = readFileSync("next.config.ts", "utf8") + readFileSync(".env.example", "utf8");
  expect(source + config).not.toMatch(/CANVAS_ACCESS_TOKEN|DEEPSEEK_API_KEY|OPENAI_API_KEY|dotenv/);
  expect(source.match(/process\.env\.[A-Z_]+/g)).toEqual(["process.env.NEXT_PUBLIC_API_BASE_URL"]);
  expect(source).not.toMatch(/tests\/fixtures|include_stale=true|localhost:8000/);
  expect(config).toContain("NEXT_PUBLIC_API_BASE_URL=");
});
