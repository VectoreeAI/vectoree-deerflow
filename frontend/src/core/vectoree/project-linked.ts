import { withBasePath } from "@/core/config";

export type LinkGate = {
  linked: boolean;
  /** The Gateway holds the project key; Google login starts there. */
  gatewayLinked: boolean;
  deployMode: "local" | "cloud";
  /** Cloud only: whether this browser holds a live preview. `null` when unknown. */
  previewActive?: boolean | null;
};

export function needsLinkPage(
  gate: Pick<LinkGate, "linked" | "deployMode">,
): boolean {
  return gate.deployMode !== "cloud" && !gate.linked;
}

/** Where a cloud visitor without a usable preview should go, or `null` to stay. */
export function previewExpiredPath(
  gate: Pick<LinkGate, "deployMode" | "previewActive">,
): string | null {
  if (gate.deployMode !== "cloud" || gate.previewActive === true) return null;
  return gate.previewActive === false
    ? "/preview-expired"
    : "/preview-expired?reason=unavailable";
}

type LinkStatusPayload = {
  linked?: boolean;
  deployMode?: string;
};

type SetupPayload = {
  vectoree_linked?: boolean;
  deploy_mode?: string;
};

async function readPreviewActive(): Promise<boolean | null> {
  try {
    const response = await fetch(withBasePath("/api/v1/preview/status"), {
      cache: "no-store",
      credentials: "include",
    });
    if (!response.ok) return null;
    const payload = (await response.json()) as { active?: unknown };
    return payload.active === true;
  } catch {
    return null;
  }
}

export async function readLinkGate(): Promise<LinkGate> {
  const [local, setup] = await Promise.all([
    fetch(withBasePath("/api/vectoree/link-status"), { cache: "no-store" })
      .then(async (response) =>
        response.ok
          ? ((await response.json()) as LinkStatusPayload)
          : { linked: false },
      )
      .catch(() => ({ linked: false }) as LinkStatusPayload),
    fetch(withBasePath("/api/v1/auth/setup-status"), {
      cache: "no-store",
      credentials: "include",
    })
      .then(async (response) =>
        response.ok ? ((await response.json()) as SetupPayload) : null,
      )
      .catch(() => null),
  ]);
  const gatewayLinked = Boolean(setup?.vectoree_linked);
  if (local.deployMode === "cloud" || setup?.deploy_mode === "cloud") {
    const previewActive = await readPreviewActive();
    return {
      linked: previewActive === true,
      gatewayLinked: previewActive === true && gatewayLinked,
      deployMode: "cloud",
      previewActive,
    };
  }
  return {
    // The Gateway uses the key for chat, tools, and Google login. A key that
    // only exists in the frontend container is not a usable link.
    linked: setup ? gatewayLinked : Boolean(local.linked),
    gatewayLinked,
    deployMode: "local",
  };
}

export async function isProjectLinked(): Promise<boolean> {
  return (await readLinkGate()).linked;
}
