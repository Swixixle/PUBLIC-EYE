import { readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { DisputeEntry } from "@frame/types";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DISPUTES_PATH = join(__dirname, "..", "disputes.json");

function loadDisputes(): DisputeEntry[] {
  const raw = readFileSync(DISPUTES_PATH, "utf8");
  const parsed = JSON.parse(raw) as unknown;
  if (!Array.isArray(parsed)) {
    throw new Error("disputes.json must be a top-level array");
  }
  return parsed as DisputeEntry[];
}

function saveDisputes(rows: DisputeEntry[]): void {
  const dir = dirname(DISPUTES_PATH);
  const tmp = join(dir, `.disputes.${process.pid}.${Date.now()}.tmp`);
  const body = `${JSON.stringify(rows, null, 2)}\n`;
  writeFileSync(tmp, body, "utf8");
  renameSync(tmp, DISPUTES_PATH);
}

function assertEntry(e: DisputeEntry): void {
  if (!e.dispute_id?.trim()) throw new Error("dispute_id required");
  if (!e.pattern_id?.trim()) throw new Error("pattern_id required");
  if (!e.submitted_at?.trim()) throw new Error("submitted_at required");
  if (!e.counter_evidence?.trim()) throw new Error("counter_evidence required");
  const s = e.status;
  if (s !== "RECEIVED" && s !== "UNDER_REVIEW" && s !== "RESOLVED") {
    throw new Error("invalid status");
  }
}

/** Append-only: push one dispute row and persist atomically. */
export function appendDispute(entry: DisputeEntry): DisputeEntry {
  assertEntry(entry);
  const rows = loadDisputes();
  rows.push(entry);
  saveDisputes(rows);
  return entry;
}

/** All disputes, optionally filtered by `pattern_id` (exact match). */
export function getDisputes(pattern_id?: string): DisputeEntry[] {
  const rows = loadDisputes();
  if (pattern_id == null || pattern_id.trim() === "") {
    return [...rows];
  }
  const pid = pattern_id.trim();
  return rows.filter((r) => r.pattern_id === pid);
}
