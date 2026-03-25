import type { ConfidenceTier } from "./depth.js";

/** Single dated fact in an actor's public-record timeline (Layer 4 ledger). */
export interface ActorEvent {
  date: string;
  type: string;
  description: string;
  source: string;
  confidence_tier: ConfidenceTier;
}

/** Append-only actor row (events grow at the end only). */
export interface ActorRecord {
  slug: string;
  name: string;
  aliases: string[];
  events: ActorEvent[];
}
