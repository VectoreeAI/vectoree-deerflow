import { describe, expect, test } from "@rstest/core";

import {
  DeployModeError,
  readDeployMode,
  rejectCloudLink,
} from "@/core/vectoree/deploy-mode";
import { needsLinkPage } from "@/core/vectoree/project-linked";

describe("DEPLOY_MODE", () => {
  test("treats an unset or local value as local", () => {
    expect(readDeployMode({})).toBe("local");
    expect(readDeployMode({ DEPLOY_MODE: "" })).toBe("local");
    expect(readDeployMode({ DEPLOY_MODE: " local " })).toBe("local");
  });

  test("accepts cloud and rejects anything else", () => {
    expect(readDeployMode({ DEPLOY_MODE: "Cloud" })).toBe("cloud");
    expect(() => readDeployMode({ DEPLOY_MODE: "preview" })).toThrow(
      DeployModeError,
    );
  });

  test("refuses to start a link in cloud mode", () => {
    expect(() => rejectCloudLink({ DEPLOY_MODE: "cloud" })).toThrow(
      /DEPLOY_MODE=cloud/,
    );
    expect(() => rejectCloudLink({ DEPLOY_MODE: "local" })).not.toThrow();
  });

  test("shows the link page only for an unlinked local deployment", () => {
    expect(needsLinkPage({ deployMode: "cloud", linked: false })).toBe(false);
    expect(needsLinkPage({ deployMode: "cloud", linked: true })).toBe(false);
    expect(needsLinkPage({ deployMode: "local", linked: true })).toBe(false);
    expect(needsLinkPage({ deployMode: "local", linked: false })).toBe(true);
  });
});
