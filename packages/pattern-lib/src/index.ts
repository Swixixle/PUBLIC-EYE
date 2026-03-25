import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PATTERNS_PATH = join(__dirname, "..", "patterns.json");

/** One catalogued pattern (spec + detection hints). */
export interface PatternRecord {
  id: string;
  label: string;
  summary: string;
  constraints: Record<string, unknown>;
  literary_analog: string | null;
  signature: string;
  detection: {
    keywords: string[];
    min_hits: number;
  };
}

let _cache: PatternRecord[] | null = null;

function loadRaw(): PatternRecord[] {
  const raw = readFileSync(PATTERNS_PATH, "utf8");
  const parsed = JSON.parse(raw) as unknown;
  if (!Array.isArray(parsed)) {
    throw new Error("patterns.json must be a top-level array");
  }
  return parsed as PatternRecord[];
}

/** Full pattern library (cached after first read). */
export function getPatternLibrary(): PatternRecord[] {
  if (_cache === null) {
    _cache = loadRaw();
  }
  return _cache;
}

/** Exact id lookup; no fuzzy matching. */
export function getPattern(id: string): PatternRecord | null {
  return getPatternLibrary().find((p) => p.id === id) ?? null;
}

/** Test hook: reset cache (e.g. after file swap in tests). */
export function __resetPatternLibraryCacheForTests(): void {
  _cache = null;
}
