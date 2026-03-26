/**
 * stdin: JSON { query, queryType, primarySources, historicalSources }
 * stdout: JSON ThreeLayerReceiptPayload (signing fields empty/false until API signs)
 */
import { readFileSync } from "node:fs";
import { generateThreeLayerNarrative } from "../packages/sources/dist/index.js";

async function main(): Promise<void> {
  const raw = readFileSync(0, "utf8");
  const input = JSON.parse(raw) as {
    query: string;
    queryType: string;
    primarySources: object;
    historicalSources: object;
  };
  const out = await generateThreeLayerNarrative(
    input.queryType,
    input.primarySources,
    input.historicalSources,
    input.query,
  );
  process.stdout.write(`${JSON.stringify(out)}\n`);
}

main().catch((err: unknown) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
