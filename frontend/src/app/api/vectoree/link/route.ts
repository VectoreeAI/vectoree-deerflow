import { NextResponse } from "next/server";

import {
  getConsoleLinker,
  visibleConnectStatus,
} from "@/core/vectoree/console-link";
import { DeployModeError, rejectCloudLink } from "@/core/vectoree/deploy-mode";
import {
  publicJson,
  readPublicLinkStatus,
  resolveWritableRepoRoot,
} from "@/core/vectoree/link-files";

export const dynamic = "force-dynamic";

function json(body: object, status = 200) {
  const response = NextResponse.json(publicJson(body), { status });
  response.headers.set("Cache-Control", "no-store");
  return response;
}

export function GET() {
  try {
    rejectCloudLink();
    const live = getConsoleLinker().snapshot();
    const saved = readPublicLinkStatus(resolveWritableRepoRoot());
    return json(visibleConnectStatus(live, saved));
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Could not connect Vectoree";
    const status = error instanceof DeployModeError ? error.status : 200;
    return json({ status: "error", message }, status);
  }
}
