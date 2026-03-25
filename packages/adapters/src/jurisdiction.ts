import type { DepthLayer } from "@frame/types";
import { DEPTH_LAYER_JURISDICTION } from "@frame/types";

/** Labeled floor: comparative jurisdiction is defined but adapters are not built yet. */
export async function getJurisdictionLayer(): Promise<DepthLayer> {
  return { ...DEPTH_LAYER_JURISDICTION };
}
