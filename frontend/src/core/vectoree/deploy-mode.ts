export type DeployMode = "local" | "cloud";

export class DeployModeError extends Error {
  readonly status: 404 | 500;

  constructor(message: string, status: 404 | 500) {
    super(message);
    this.name = "DeployModeError";
    this.status = status;
  }
}

export function readDeployMode(
  env: NodeJS.ProcessEnv = process.env,
): DeployMode {
  const raw = env.DEPLOY_MODE?.trim().toLowerCase() ?? "";
  if (raw === "" || raw === "local") return "local";
  if (raw === "cloud") return "cloud";
  throw new DeployModeError("DEPLOY_MODE must be local or cloud", 500);
}

export function rejectCloudLink(env: NodeJS.ProcessEnv = process.env): void {
  if (readDeployMode(env) === "cloud") {
    throw new DeployModeError(
      "Link is not used when DEPLOY_MODE=cloud",
      404,
    );
  }
}
