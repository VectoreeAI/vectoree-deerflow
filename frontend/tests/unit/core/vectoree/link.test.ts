import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { describe, expect, test } from "@rstest/core";

import {
  apiBaseFor,
  publicJson,
  readPublicLinkStatus,
  resolveWritableRepoRoot,
  upsertEnv,
  writeLinkedConfig,
} from "@/core/vectoree/link-files";
import { extractProjectId } from "@/core/vectoree/project-id";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";

function tempRoot(): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "vectoree-link-"));
  fs.writeFileSync(path.join(root, "config.example.yaml"), "models: []\n");
  return root;
}

describe("vectoree link files", () => {
  test("treats a missing key as unlinked even when the API URL is blank", () => {
    const root = tempRoot();
    fs.writeFileSync(
      path.join(root, ".env"),
      "VECTOREE_API_URL=\nVECTOREE_API_BASE=\nVECTOREE_API_KEY=\n",
    );
    expect(readPublicLinkStatus(root)).toEqual({ linked: false });
  });

  test("links when either the config file or .env has a project key", () => {
    const fromEnv = tempRoot();
    fs.writeFileSync(
      path.join(fromEnv, ".env"),
      "OTHER=keep\nVECTOREE_API_KEY=sk-ve-v1-from-env\n",
    );
    expect(readPublicLinkStatus(fromEnv)).toEqual({ linked: true });

    const fromFile = tempRoot();
    fs.mkdirSync(path.join(fromFile, ".vectoree"));
    fs.writeFileSync(
      path.join(fromFile, ".vectoree", "config.json"),
      JSON.stringify({
        apiKey: "sk-ve-v1-from-file",
        projectName: "Demo",
        apiUrl: "https://vectoree.ai",
        accessToken: "jwt-secret",
      }),
    );
    expect(readPublicLinkStatus(fromFile)).toEqual({
      linked: true,
      projectName: "Demo",
      apiUrl: "https://vectoree.ai",
    });
    expect(JSON.stringify(readPublicLinkStatus(fromFile))).not.toContain(
      "jwt-secret",
    );
    expect(JSON.stringify(readPublicLinkStatus(fromFile))).not.toContain(
      "sk-ve-",
    );
  });

  test("public responses drop secrets", () => {
    expect(
      publicJson({
        linked: true,
        apiKey: "sk-ve-v1-secret",
        accessToken: "jwt",
        projectName: "Demo",
      }),
    ).toEqual({ linked: true, projectName: "Demo" });
  });

  test("extracts a project id from a paste or console URL", () => {
    expect(extractProjectId(`project (${PROJECT_ID})`)).toBe(PROJECT_ID);
    expect(
      extractProjectId(`https://vectoree.ai/console?projectId=${PROJECT_ID}`),
    ).toBe(PROJECT_ID);
    expect(extractProjectId("no id here")).toBeNull();
  });

  test("upsert keeps unrelated env lines and sets the Vectoree base URL", () => {
    const next = upsertEnv("# comment\nOTHER=keep\nVECTOREE_API_KEY=\n", {
      VECTOREE_API_KEY: "sk-ve-v1-new",
      VECTOREE_API_BASE: apiBaseFor("https://vectoree.ai"),
    });
    expect(next).toContain("# comment");
    expect(next).toContain("OTHER=keep");
    expect(next).toContain("VECTOREE_API_KEY=sk-ve-v1-new");
    expect(next).toContain("VECTOREE_API_BASE=https://vectoree.ai/api/v1");
  });

  test("writes the project key to config.json and .env without a JWT in .env", () => {
    const root = tempRoot();
    fs.writeFileSync(path.join(root, ".env"), "OTHER=keep\n");
    writeLinkedConfig(root, {
      apiUrl: "https://vectoree.ai",
      projectId: PROJECT_ID,
      projectName: "Demo",
      apiKey: "sk-ve-v1-minted",
      accessToken: "jwt-secret",
      refreshToken: "refresh-secret",
    });
    const config = fs.readFileSync(
      path.join(root, ".vectoree", "config.json"),
      "utf8",
    );
    const env = fs.readFileSync(path.join(root, ".env"), "utf8");
    expect(config).toContain("sk-ve-v1-minted");
    expect(env).toContain("VECTOREE_API_KEY=sk-ve-v1-minted");
    expect(env).toContain("VECTOREE_API_URL=https://vectoree.ai");
    expect(env).toContain("VECTOREE_API_BASE=https://vectoree.ai/api/v1");
    expect(env).toContain("OTHER=keep");
    expect(env).not.toContain("jwt-secret");
    expect(env).not.toContain("refresh-secret");
    expect(readPublicLinkStatus(root).linked).toBe(true);
  });

  test("accepts an explicit writable project root", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "explicit-root-"));
    expect(
      resolveWritableRepoRoot(dir, {
        ...process.env,
        DEER_FLOW_PROJECT_ROOT: dir,
      }),
    ).toBe(path.resolve(dir));
  });

  test("uses the container project directory when the process is inside it", () => {
    const app = fs.mkdtempSync(path.join(os.tmpdir(), "container-app-"));
    const nested = path.join(app, "frontend");
    fs.mkdirSync(nested);
    const env = { ...process.env };
    delete env.DEER_FLOW_PROJECT_ROOT;
    expect(resolveWritableRepoRoot(nested, env, app)).toBe(path.resolve(app));
  });

  test("rejects discovery outside a repository", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "not-a-repo-"));
    const env = { ...process.env };
    delete env.DEER_FLOW_PROJECT_ROOT;
    expect(() => resolveWritableRepoRoot(dir, env)).toThrow(
      /writable project directory/,
    );
  });
});
