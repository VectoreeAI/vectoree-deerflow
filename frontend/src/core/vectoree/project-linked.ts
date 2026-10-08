export type LinkGate = {
  linked: boolean;
  deployMode: "local" | "cloud";
};

export function needsLinkPage(gate: LinkGate): boolean {
  return gate.deployMode !== "cloud" && !gate.linked;
}

type LinkStatusPayload = {
  linked?: boolean;
  deployMode?: string;
};

type SetupPayload = {
  vectoree_linked?: boolean;
};

export async function readLinkGate(): Promise<LinkGate> {
  const [local, setup] = await Promise.all([
    fetch("/api/vectoree/link-status")
      .then(async (response) =>
        response.ok
          ? ((await response.json()) as LinkStatusPayload)
          : { linked: false },
      )
      .catch(() => ({ linked: false }) as LinkStatusPayload),
    fetch("/api/v1/auth/setup-status", {
      cache: "no-store",
      credentials: "include",
    })
      .then(async (response) =>
        response.ok
          ? ((await response.json()) as SetupPayload)
          : { vectoree_linked: false },
      )
      .catch(() => ({ vectoree_linked: false })),
  ]);
  return {
    linked: Boolean(local.linked || setup.vectoree_linked),
    deployMode: local.deployMode === "cloud" ? "cloud" : "local",
  };
}

export async function isProjectLinked(): Promise<boolean> {
  return (await readLinkGate()).linked;
}
