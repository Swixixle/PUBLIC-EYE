import { readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ActorEvent, ActorRecord } from "@frame/types";
import { ConfidenceTier } from "@frame/types";

const __dirname = dirname(fileURLToPath(import.meta.url));
const LEDGER_PATH = join(__dirname, "..", "ledger.json");

/** On-disk shape: slug is the object key, not duplicated inside the row. */
type StoredActor = {
  name: string;
  aliases: string[];
  events: ActorEvent[];
};

type LedgerRoot = Record<string, StoredActor>;

const TIER_SET = new Set<string>(Object.values(ConfidenceTier));

function loadLedger(): LedgerRoot {
  const raw = readFileSync(LEDGER_PATH, "utf8");
  const parsed = JSON.parse(raw) as unknown;
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("ledger.json must be a top-level object");
  }
  return parsed as LedgerRoot;
}

function saveLedger(data: LedgerRoot): void {
  const dir = dirname(LEDGER_PATH);
  const tmp = join(dir, `.ledger.${process.pid}.${Date.now()}.tmp`);
  const body = `${JSON.stringify(data, null, 2)}\n`;
  writeFileSync(tmp, body, "utf8");
  renameSync(tmp, LEDGER_PATH);
}

function sortEventsByDate(events: ActorEvent[]): ActorEvent[] {
  return [...events].sort((a, b) => a.date.localeCompare(b.date));
}

function humanizeSlug(slug: string): string {
  return slug
    .split("-")
    .map((s) => (s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : s))
    .join(" ");
}

function assertActorEvent(event: ActorEvent): void {
  if (!event.date?.trim()) throw new Error("event.date is required");
  if (!event.type?.trim()) throw new Error("event.type is required");
  if (!event.description?.trim()) throw new Error("event.description is required");
  if (!event.source?.trim()) throw new Error("event.source is required");
  const t = event.confidence_tier;
  if (typeof t !== "string" || !TIER_SET.has(t)) {
    throw new Error(`event.confidence_tier must be one of: ${[...TIER_SET].join(", ")}`);
  }
}

/**
 * Case-insensitive match on ledger row `name` or any `alias` (not fuzzy).
 * Returns the same shape as getActor for that slug.
 */
export function findActorByExactNameOrAlias(query: string): ActorRecord | null {
  const q = query.trim().toLowerCase();
  if (!q) return null;
  const ledger = loadLedger();
  for (const [slug, row] of Object.entries(ledger)) {
    if (row.name.trim().toLowerCase() === q) {
      return {
        slug,
        name: row.name,
        aliases: [...row.aliases],
        events: sortEventsByDate(row.events),
      };
    }
    for (const al of row.aliases) {
      if (al.trim().toLowerCase() === q) {
        return {
          slug,
          name: row.name,
          aliases: [...row.aliases],
          events: sortEventsByDate(row.events),
        };
      }
    }
  }
  return null;
}

/** Exact slug lookup; returns full record with events sorted ascending by date. */
export function getActor(slug: string): ActorRecord | null {
  const key = slug.trim();
  if (!key) return null;
  const ledger = loadLedger();
  const row = ledger[key];
  if (!row) return null;
  return {
    slug: key,
    name: row.name,
    aliases: row.aliases,
    events: sortEventsByDate(row.events),
  };
}

/** Events only, sorted ascending by date; empty array if actor is absent. */
export function getActorEvents(slug: string): ActorEvent[] {
  const key = slug.trim();
  if (!key) return [];
  const ledger = loadLedger();
  const row = ledger[key];
  if (!row) return [];
  return sortEventsByDate(row.events);
}

/**
 * Append-only: pushes one new event. Never edits or removes prior events.
 * If the slug is new, creates a record (name derived from slug, empty aliases).
 */
export function appendEvent(slug: string, event: ActorEvent): ActorRecord {
  const key = slug.trim();
  if (!key) throw new Error("slug is required");
  assertActorEvent(event);

  const ledger = loadLedger();
  const row = ledger[key];

  if (!row) {
    ledger[key] = {
      name: humanizeSlug(key),
      aliases: [],
      events: [event],
    };
  } else {
    ledger[key] = {
      name: row.name,
      aliases: row.aliases,
      events: [...row.events, event],
    };
  }

  saveLedger(ledger);
  const out = getActor(key);
  if (!out) throw new Error("ledger invariant failed after append");
  return out;
}
