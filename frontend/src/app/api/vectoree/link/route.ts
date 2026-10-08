import { NextResponse } from "next/server";

import { getConsoleLinker } from "@/core/vectoree/console-link";
import { DeployModeError, rejectCloudLink } from "@/core/vectoree/deploy-mode";
import { publicJson } from "@/core/vectoree/link-files";

export const dynamic = "force-dynamic";

export function GET() {
  try {
    rejectCloudLink();
    return NextResponse.json(publicJson(getConsoleLinker().snapshot()));
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Could not connect Vectoree";
    const status = error instanceof DeployModeError ? error.status : 200;
    return NextResponse.json(publicJson({ status: "error", message }), {
      status,
    });
  }
}
