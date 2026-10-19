import { afterEach, describe, expect, it, rs } from "@rstest/core";

import {
  previewExpiredPath,
  readLinkGate,
} from "@/core/vectoree/project-linked";

function mockStatus(
  local: object,
  setup: object | Error,
  preview: object | Error = new Error("not cloud"),
) {
  rs.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = input instanceof Request ? input.url : input.toString();
    if (url.includes("link-status")) {
      return { ok: true, json: async () => local } as Response;
    }
    if (url.includes("preview/status")) {
      if (preview instanceof Error) throw preview;
      return { ok: true, json: async () => preview } as Response;
    }
    if (setup instanceof Error) throw setup;
    return { ok: true, json: async () => setup } as Response;
  });
}

afterEach(() => {
  rs.restoreAllMocks();
});

describe("readLinkGate", () => {
  it("treats a frontend-only key as unlinked when the Gateway has none", async () => {
    mockStatus(
      { linked: true, deployMode: "local" },
      { needs_setup: false, vectoree_linked: false },
    );
    expect(await readLinkGate()).toEqual({
      linked: false,
      gatewayLinked: false,
      deployMode: "local",
    });
  });

  it("is linked when the Gateway has the key", async () => {
    mockStatus(
      { linked: false, deployMode: "local" },
      { needs_setup: false, vectoree_linked: true },
    );
    expect(await readLinkGate()).toEqual({
      linked: true,
      gatewayLinked: true,
      deployMode: "local",
    });
  });

  it("falls back to the frontend status when the Gateway is unreachable", async () => {
    mockStatus({ linked: true, deployMode: "local" }, new Error("down"));
    expect(await readLinkGate()).toEqual({
      linked: true,
      gatewayLinked: false,
      deployMode: "local",
    });
  });

  it("uses the preview status in cloud mode", async () => {
    mockStatus(
      { linked: false, deployMode: "cloud" },
      { vectoree_linked: true, deploy_mode: "cloud" },
      { active: true },
    );
    expect(await readLinkGate()).toEqual({
      linked: true,
      gatewayLinked: true,
      deployMode: "cloud",
      previewActive: true,
    });
  });

  it("detects cloud mode from the Gateway alone", async () => {
    mockStatus(
      { linked: false, deployMode: "local" },
      { vectoree_linked: false, deploy_mode: "cloud" },
      { active: false },
    );
    expect(await readLinkGate()).toEqual({
      linked: false,
      gatewayLinked: false,
      deployMode: "cloud",
      previewActive: false,
    });
  });

  it("reports an unknown preview when the status probe fails", async () => {
    mockStatus(
      { linked: false, deployMode: "cloud" },
      { vectoree_linked: false, deploy_mode: "cloud" },
      new Error("down"),
    );
    expect((await readLinkGate()).previewActive).toBeNull();
  });
});

describe("previewExpiredPath", () => {
  it("only redirects cloud visitors without a live preview", () => {
    expect(previewExpiredPath({ deployMode: "local" })).toBeNull();
    expect(
      previewExpiredPath({ deployMode: "cloud", previewActive: true }),
    ).toBeNull();
    expect(
      previewExpiredPath({ deployMode: "cloud", previewActive: false }),
    ).toBe("/preview-expired");
    expect(
      previewExpiredPath({ deployMode: "cloud", previewActive: null }),
    ).toBe("/preview-expired?reason=unavailable");
  });
});
