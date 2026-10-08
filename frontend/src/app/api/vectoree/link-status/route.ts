import { NextResponse } from "next/server";

import {
  DeployModeError,
  readDeployMode,
  type DeployMode,
} from "@/core/vectoree/deploy-mode";
import {
  publicJson,
  readPublicLinkStatus,
  resolveWritableRepoRoot,
} from "@/core/vectoree/link-files";

export const dynamic = "force-dynamic";

export function GET() {
  let deployMode: DeployMode;
  try {
    deployMode = readDeployMode();
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "DEPLOY_MODE must be local or cloud";
    const status = error instanceof DeployModeError ? error.status : 500;
    return NextResponse.json(publicJson({ linked: false, message }), { status });
  }
  try {
    const root = resolveWritableRepoRoot();
    return NextResponse.json(
      publicJson({ ...readPublicLinkStatus(root), deployMode }),
    );
  } catch (error) {
    const message =
      error instanceof Error
        ? error.message
        : "Could not find a writable project directory";
    return NextResponse.json(publicJson({ linked: false, deployMode, message }));
  }
}
