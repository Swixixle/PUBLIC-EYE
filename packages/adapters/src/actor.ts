import type { DepthLayer } from "@frame/types";
import { DEPTH_LAYER_ACTOR } from "@frame/types";

export async function getActorLayer(): Promise<DepthLayer> {
  return { ...DEPTH_LAYER_ACTOR };
}
