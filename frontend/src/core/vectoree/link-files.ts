import fs from "node:fs";
import path from "node:path";

export const DEFAULT_API_URL = "https://vectoree.ai";

export const ROOT_ERROR =
  "Could not find a writable project directory for Vectoree credentials.";

export class ConfigError extends Error {
  readonly status: 400 | 502;

  constructor(message: string, status: 400 | 502 = 400) {
    super(message);
    this.name = "ConfigError";
    this.status = status;
  }
}

export type PublicLinkStatus = {
  linked: boolean;
  projectName?: string;
  apiUrl?: string;
  message?: string;
};

const PUBLIC_FIELDS = new Set([
  "linked",
  "deployMode",
  "status",
  "authorizeUrl",
  "message",
  "apiUrl",
  "projectId",
  "projectName",
]);

export function publicJson(value: object): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (item !== undefined && PUBLIC_FIELDS.has(key)) out[key] = item;
  }
  return out;
}

export function normalizeApiUrl(input: string): string {
  const trimmed = input.trim();
  if (!trimmed) throw new ConfigError("apiUrl is required");
  let url: URL;
  try {
    url = new URL(trimmed);
  } catch {
    throw new ConfigError(
      "apiUrl must be an http(s) origin, for example https://vectoree.ai",
    );
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new ConfigError("apiUrl must use http or https");
  }
  if (url.username || url.password) {
    throw new ConfigError("apiUrl must not include credentials");
  }
  if (url.search || url.hash) {
    throw new ConfigError("apiUrl must be an origin, without a query or hash");
  }
  if (url.pathname !== "/" && url.pathname !== "") {
    throw new ConfigError(
      "Use the API origin only, for example https://vectoree.ai",
    );
  }
  return url.origin;
}

export function apiBaseFor(apiUrl: string): string {
  return `${apiUrl.replace(/\/+$/, "")}/api/v1`;
}

export function resolveWritableRepoRoot(
  start = process.cwd(),
  env: NodeJS.ProcessEnv = process.env,
  containerRoot = "/app",
): string {
  const configured = env.DEER_FLOW_PROJECT_ROOT?.trim();
  const discovered = configured ? null : findRepoRoot(start);
  const insideContainer = isInside(start, containerRoot);
  const candidate = configured
    ? path.resolve(configured)
    : (discovered ??
      (insideContainer ? path.resolve(containerRoot) : null));
  // Host `pnpm dev` finds the repository by config.example.yaml.
  // The Docker image has no repository checkout; /app is the project
  // directory in the container and the process can write there directly.
  if (!candidate) {
    throw new ConfigError(ROOT_ERROR);
  }
  try {
    fs.accessSync(candidate, fs.constants.W_OK);
  } catch {
    throw new ConfigError(ROOT_ERROR);
  }
  return candidate;
}

export function readPublicLinkStatus(root: string): PublicLinkStatus {
  const file = readConfigFile(root);
  const disk = parseEnvFile(path.join(root, ".env"));
  const fileKey = file.apiKey?.trim() ?? "";
  const envKey = disk.VECTOREE_API_KEY?.trim() ?? "";
  if (!fileKey && !envKey) return { linked: false };

  const status: PublicLinkStatus = { linked: true };
  const projectName = file.projectName?.trim();
  if (projectName) status.projectName = projectName;
  const apiUrl = (file.apiUrl || disk.VECTOREE_API_URL || "").trim();
  if (apiUrl) status.apiUrl = apiUrl;
  return status;
}

export type LinkedCredentials = {
  apiUrl: string;
  projectId: string;
  projectName?: string;
  apiKey: string;
  keyId?: string;
  accessToken?: string;
  refreshToken?: string;
};

export function writeLinkedConfig(
  root: string,
  input: LinkedCredentials,
): void {
  const dir = path.join(root, ".vectoree");
  const file = path.join(dir, "config.json");
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const existing = readConfigFile(root);
  const next: Record<string, string | undefined> = {
    ...existing,
    apiUrl: input.apiUrl,
    accessToken: input.accessToken ?? existing.accessToken,
    refreshToken: input.refreshToken ?? existing.refreshToken,
    apiKey: input.apiKey,
    projectId: input.projectId,
    projectName: input.projectName ?? existing.projectName,
    keyId: input.keyId ?? existing.keyId,
  };
  for (const alias of [
    "api_url",
    "api_key",
    "project_id",
    "project_name",
    "key_id",
  ]) {
    delete next[alias];
  }
  const ordered: Record<string, string> = {};
  for (const key of [
    "apiUrl",
    "accessToken",
    "refreshToken",
    "apiKey",
    "projectId",
    "projectName",
    "keyId",
  ]) {
    const value = next[key];
    if (value) ordered[key] = value;
    delete next[key];
  }
  for (const [key, value] of Object.entries(next)) {
    if (value) ordered[key] = value;
  }
  const tmp = path.join(dir, `.config.json.${process.pid}.tmp`);
  fs.writeFileSync(tmp, `${JSON.stringify(ordered, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  fs.renameSync(tmp, file);
  try {
    fs.chmodSync(dir, 0o700);
    fs.chmodSync(file, 0o600);
  } catch {
    // chmod can fail on some filesystems; the file is still written.
  }
  syncEnvFile(root, {
    VECTOREE_API_URL: input.apiUrl,
    VECTOREE_API_KEY: input.apiKey,
    VECTOREE_API_BASE: apiBaseFor(input.apiUrl),
  });
}

export function syncEnvFile(
  root: string,
  updates: Record<string, string>,
): void {
  const file = path.join(root, ".env");
  const current = fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "";
  fs.writeFileSync(file, upsertEnv(current, updates), {
    encoding: "utf8",
    mode: 0o600,
  });
  try {
    fs.chmodSync(file, 0o600);
  } catch {
    // ignore
  }
}

export function upsertEnv(
  content: string,
  updates: Record<string, string>,
): string {
  const lines = content.split("\n");
  const seen = new Set<string>();
  const next = lines.map((line) => {
    const key = /^([A-Za-z_][A-Za-z0-9_]*)=/.exec(line)?.[1];
    if (!key) return line;
    const value = updates[key];
    if (value === undefined) return line;
    seen.add(key);
    return `${key}=${value}`;
  });
  for (const [key, value] of Object.entries(updates)) {
    if (!seen.has(key)) next.push(`${key}=${value}`);
  }
  while (next.length > 0 && next[next.length - 1] === "") next.pop();
  return `${next.join("\n")}\n`;
}

function isInside(start: string, root: string): boolean {
  const resolvedStart = path.resolve(start);
  const resolvedRoot = path.resolve(root);
  return (
    resolvedStart === resolvedRoot ||
    resolvedStart.startsWith(resolvedRoot + path.sep)
  );
}

function findRepoRoot(start: string): string | null {
  let dir = path.resolve(start);
  for (let i = 0; i < 8; i += 1) {
    if (isRepoRoot(dir)) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

function isRepoRoot(dir: string): boolean {
  return fs.existsSync(path.join(dir, "config.example.yaml"));
}

function readConfigFile(root: string): Record<string, string | undefined> {
  const file = path.join(root, ".vectoree", "config.json");
  if (!fs.existsSync(file)) return {};
  try {
    const raw = JSON.parse(fs.readFileSync(file, "utf8")) as unknown;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
    const record = raw as Record<string, unknown>;
    const out: Record<string, string | undefined> = {};
    for (const [key, value] of Object.entries(record)) {
      if (typeof value === "string") out[key] = value;
    }
    out.apiUrl = firstString(out, "apiUrl", "api_url");
    out.projectId = firstString(out, "projectId", "project_id");
    out.apiKey = firstString(out, "apiKey", "api_key");
    out.projectName = firstString(out, "projectName", "project_name");
    out.keyId = firstString(out, "keyId", "key_id");
    out.accessToken = firstString(out, "accessToken", "access_token");
    out.refreshToken = firstString(out, "refreshToken", "refresh_token");
    return out;
  } catch {
    return {};
  }
}

function firstString(
  record: Record<string, string | undefined>,
  ...keys: string[]
): string | undefined {
  for (const key of keys) {
    const value = record[key]?.trim();
    if (value) return value;
  }
  return undefined;
}

function parseEnvFile(file: string): Record<string, string> {
  if (!fs.existsSync(file)) return {};
  const out: Record<string, string> = {};
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (key) out[key] = value;
  }
  return out;
}
