import type { DepthLayer } from "@frame/types";
import { DEPTH_LAYER_ORIGIN } from "@frame/types";

export async function getOriginLayer(): Promise<DepthLayer> {
  return { ...DEPTH_LAYER_ORIGIN };
}
