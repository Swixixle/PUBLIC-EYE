import type { DepthLayer } from "@frame/types";
import { DEPTH_LAYER_SPREAD } from "@frame/types";

export async function getSpreadLayer(): Promise<DepthLayer> {
  return { ...DEPTH_LAYER_SPREAD };
}
