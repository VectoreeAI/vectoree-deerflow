import { NextResponse } from "next/server";

import { getConsoleLinker } from "@/core/vectoree/console-link";
import { DeployModeError, rejectCloudLink } from "@/core/vectoree/deploy-mode";
import { ConfigError, publicJson } from "@/core/vectoree/link-files";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      publicJson({ status: "error", message: "Expected a JSON object" }),
      { status: 400 },
    );
  }
  const record =
    body && typeof body === "object" ? (body as Record<string, unknown>) : {};
  const apiUrl = typeof record.apiUrl === "string" ? record.apiUrl : undefined;
  const projectId =
    typeof record.projectId === "string" ? record.projectId : undefined;
  try {
    rejectCloudLink();
    const status = await getConsoleLinker().start({ apiUrl, projectId });
    return NextResponse.json(publicJson(status));
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Could not connect Vectoree";
    const status =
      error instanceof ConfigError || error instanceof DeployModeError
        ? error.status
        : 400;
    return NextResponse.json(publicJson({ status: "error", message }), {
      status,
    });
  }
}
