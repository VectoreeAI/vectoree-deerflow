import { execFile } from "node:child_process";
import { createHash, randomBytes, randomUUID } from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";

import {
  ConfigError,
  DEFAULT_API_URL,
  apiBaseFor,
  normalizeApiUrl,
  resolveWritableRepoRoot,
  writeLinkedConfig,
} from "./link-files";

const PROJECT_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const KEY_SCOPES = [
  "gateway:chat",
  "gateway:models",
  "tools:*",
  "database:*",
  "storage:*",
  "auth:*",
];

export type ConnectPublic = {
  status: "idle" | "pending" | "linked" | "error";
  authorizeUrl?: string;
  message?: string;
  apiUrl?: string;
  projectId?: string;
  projectName?: string;
};

type Loopback = {
  port: number;
  close: (reason?: string) => void;
  code: Promise<string>;
};

export type ConsoleLinkerOptions = {
  root: string;
  fetchImpl?: typeof fetch;
  openUrl?: (url: string) => Promise<void>;
  timeoutMs?: number;
};

export function createConsoleLinker(options: ConsoleLinkerOptions) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const openUrl = options.openUrl ?? openSystemBrowser;
  const timeoutMs = options.timeoutMs ?? 180_000;
  let state: ConnectPublic = { status: "idle" };
  let loopback: Loopback | null = null;
  let generation = 0;

  return {
    snapshot(): ConnectPublic {
      return { ...state };
    },
    async start(input: {
      apiUrl?: string;
      projectId?: string;
    }): Promise<ConnectPublic> {
      const apiUrl = normalizeApiUrl(input.apiUrl?.trim() || DEFAULT_API_URL);
      const projectId = input.projectId?.trim() ?? "";
      if (!PROJECT_UUID.test(projectId)) {
        throw new ConfigError(
          "projectId must be a UUID from the Vectoree console",
        );
      }
      cancelLoopback();
      const attempt = ++generation;
      const { verifier, challenge } = pkcePair();
      const stateValue = randomBytes(16).toString("hex");
      const bind = callbackBind();
      const callback = await listenForCode(stateValue, bind.host, bind.port);
      loopback = callback;
      const authorize = new URL(`${apiUrl}/api/system/auth/cli/authorize`);
      authorize.searchParams.set("response_type", "code");
      authorize.searchParams.set("code_challenge", challenge);
      authorize.searchParams.set("code_challenge_method", "S256");
      authorize.searchParams.set(
        "redirect_uri",
        `http://127.0.0.1:${callback.port}/callback`,
      );
      authorize.searchParams.set("state", stateValue);
      const authorizeUrl = authorize.toString();
      state = { status: "pending", authorizeUrl, apiUrl, projectId };
      void finish({
        attempt,
        apiUrl,
        projectId,
        verifier,
        redirectUri: `http://127.0.0.1:${callback.port}/callback`,
        code: callback.code,
      });
      await openUrl(authorizeUrl).catch(() => undefined);
      return { ...state };
    },
  };

  function cancelLoopback(reason = "Login cancelled"): void {
    loopback?.close(reason);
    loopback = null;
  }

  async function finish(job: {
    attempt: number;
    apiUrl: string;
    projectId: string;
    verifier: string;
    redirectUri: string;
    code: Promise<string>;
  }): Promise<void> {
    const timer = setTimeout(() => {
      if (generation !== job.attempt) return;
      cancelLoopback("Console login timed out. Try connecting again.");
    }, timeoutMs);
    try {
      const code = await job.code;
      if (generation !== job.attempt) return;
      const session = await exchangeCode(fetchImpl, job.apiUrl, {
        code,
        codeVerifier: job.verifier,
        redirectUri: job.redirectUri,
      });
      const projectName = await lookupProjectName(
        fetchImpl,
        job.apiUrl,
        session.accessToken,
        job.projectId,
      );
      const minted = await mintProjectKey(
        fetchImpl,
        job.apiUrl,
        session.accessToken,
        {
          projectId: job.projectId,
          projectName,
          root: options.root,
        },
      );
      writeLinkedConfig(options.root, {
        apiUrl: job.apiUrl,
        accessToken: session.accessToken,
        refreshToken: session.refreshToken,
        apiKey: minted.apiKey,
        projectId: job.projectId,
        projectName,
        keyId: minted.keyId,
      });
      await saveGatewayProject({
        apiUrl: job.apiUrl,
        apiKey: minted.apiKey,
        apiBase: apiBaseFor(job.apiUrl),
        accessToken: session.accessToken,
        refreshToken: session.refreshToken,
        projectId: job.projectId,
        projectName,
        keyId: minted.keyId,
      });
      if (generation !== job.attempt) return;
      state = {
        status: "linked",
        apiUrl: job.apiUrl,
        projectId: job.projectId,
        projectName,
      };
    } catch (error) {
      if (generation !== job.attempt) return;
      state = {
        status: "error",
        apiUrl: job.apiUrl,
        projectId: job.projectId,
        message:
          error instanceof Error ? error.message : "Could not connect Vectoree",
      };
    } finally {
      clearTimeout(timer);
      if (generation === job.attempt) cancelLoopback();
    }
  }
}

let linker: ReturnType<typeof createConsoleLinker> | null = null;

export function getConsoleLinker(): ReturnType<typeof createConsoleLinker> {
  if (linker) return linker;
  const root = resolveWritableRepoRoot();
  linker = createConsoleLinker({ root });
  return linker;
}

export function resetConsoleLinkerForTests(): void {
  linker = null;
}

async function saveGatewayProject(input: {
  apiUrl: string;
  apiKey: string;
  apiBase: string;
  accessToken: string;
  refreshToken?: string;
  projectId: string;
  projectName?: string;
  keyId?: string;
}): Promise<void> {
  const base = process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL?.trim();
  if (!base) return;
  const token = process.env.DEER_FLOW_INTERNAL_AUTH_TOKEN?.trim();
  if (!token) {
    throw new ConfigError(
      "DEER_FLOW_INTERNAL_AUTH_TOKEN is required to save Vectoree credentials in the gateway container",
    );
  }
  const response = await fetch(
    `${base.replace(/\/+$/, "")}/api/internal/vectoree/project-credentials`,
    {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-DeerFlow-Internal-Token": token,
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        apiUrl: input.apiUrl,
        apiKey: input.apiKey,
        apiBase: input.apiBase,
        accessToken: input.accessToken,
        refreshToken: input.refreshToken,
        projectId: input.projectId,
        projectName: input.projectName,
        keyId: input.keyId,
      }),
    },
  );
  if (!response.ok) {
    throw new ConfigError(
      "Could not save Vectoree credentials in the gateway container",
      502,
    );
  }
}

function pkcePair(): { verifier: string; challenge: string } {
  const verifier = randomBytes(32).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  return { verifier, challenge };
}

async function exchangeCode(
  fetchImpl: typeof fetch,
  apiUrl: string,
  body: { code: string; codeVerifier: string; redirectUri: string },
): Promise<{ accessToken: string; refreshToken?: string }> {
  const response = await fetchImpl(`${apiUrl}/api/system/auth/cli/token`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({
      grant_type: "authorization_code",
      code: body.code,
      code_verifier: body.codeVerifier,
      redirect_uri: body.redirectUri,
    }),
  });
  const data = await readBody(response);
  if (!response.ok) {
    throw new Error(
      readErrorMessage(data, `Console login failed (${response.status})`),
    );
  }
  const record =
    data && typeof data === "object" ? (data as Record<string, unknown>) : {};
  if (typeof record.accessToken !== "string" || !record.accessToken) {
    throw new Error("Console login did not return a session");
  }
  return {
    accessToken: record.accessToken,
    refreshToken:
      typeof record.refreshToken === "string" ? record.refreshToken : undefined,
  };
}

async function lookupProjectName(
  fetchImpl: typeof fetch,
  apiUrl: string,
  accessToken: string,
  projectId: string,
): Promise<string> {
  const response = await fetchImpl(`${apiUrl}/api/projects`, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
  });
  const data = await readBody(response);
  if (!response.ok) {
    throw new Error(
      readErrorMessage(data, `Could not list projects (${response.status})`),
    );
  }
  const projects = Array.isArray(data) ? data : [];
  const match = projects.find(
    (item) =>
      item &&
      typeof item === "object" &&
      (item as { id?: unknown }).id === projectId,
  ) as { name?: unknown } | undefined;
  if (!match) {
    throw new Error("That project was not found on this Vectoree account");
  }
  return typeof match.name === "string" && match.name.trim()
    ? match.name.trim()
    : projectId;
}

async function mintProjectKey(
  fetchImpl: typeof fetch,
  apiUrl: string,
  accessToken: string,
  input: { projectId: string; projectName: string; root: string },
): Promise<{ apiKey: string; keyId?: string }> {
  const response = await fetchImpl(`${apiUrl}/api/gateway/keys`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
      "X-Project-Id": input.projectId,
      "User-Agent": "VectoreeCLI",
    },
    body: JSON.stringify({
      name: `CLI — ${os.hostname()}`.slice(0, 128),
      projectId: input.projectId,
      deviceId: readDeviceId(input.root),
      localFolderPath: input.root,
      scopes: KEY_SCOPES,
    }),
  });
  const data = await readBody(response);
  if (!response.ok) {
    throw new Error(
      readErrorMessage(
        data,
        `Could not create a project key (${response.status})`,
      ),
    );
  }
  const record =
    data && typeof data === "object" ? (data as Record<string, unknown>) : {};
  if (typeof record.apiKey !== "string" || !record.apiKey.startsWith("sk-ve-")) {
    throw new Error("Vectoree did not return a project API key");
  }
  return {
    apiKey: record.apiKey,
    keyId: typeof record.id === "string" ? record.id : undefined,
  };
}

function readDeviceId(root: string): string {
  const file = path.join(root, ".vectoree", "device-id");
  try {
    const existing = fs.readFileSync(file, "utf8").trim();
    if (existing.length >= 8) return existing.slice(0, 128);
  } catch {
    // create one below
  }
  const id = randomUUID();
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  fs.writeFileSync(file, `${id}\n`, { encoding: "utf8", mode: 0o600 });
  return id;
}

function callbackBind(): { host: string; port: number } {
  const raw = process.env.VECTOREE_LINK_CALLBACK_PORT?.trim();
  if (!raw) return { host: "127.0.0.1", port: 0 };
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new ConfigError("VECTOREE_LINK_CALLBACK_PORT must be a TCP port");
  }
  // Compose publishes this port on the host loopback. The process must listen
  // on all interfaces so that publish can reach it; the host mapping stays 127.0.0.1.
  return { host: "0.0.0.0", port };
}

function listenForCode(
  expectedState: string,
  host: string,
  port: number,
): Promise<Loopback> {
  return new Promise((resolve, reject) => {
    let settled = false;
    let settleCode: ((code: string) => void) | undefined;
    let failCode: ((error: Error) => void) | undefined;
    const code = new Promise<string>((resolveCode, rejectCode) => {
      settleCode = resolveCode;
      failCode = rejectCode;
    });
    const finishOnce = (action: () => void) => {
      if (settled) return;
      settled = true;
      action();
      server.close();
    };
    const server = http.createServer((req, res) => {
      try {
        const url = new URL(req.url ?? "/", "http://127.0.0.1");
        if (url.pathname !== "/callback") {
          res.writeHead(404).end("Not found");
          return;
        }
        const authCode = url.searchParams.get("code");
        const state = url.searchParams.get("state");
        if (!authCode || state !== expectedState) {
          res.writeHead(400, { "Content-Type": "text/html; charset=utf-8" });
          res.end("<p>Invalid Vectoree login callback.</p>");
          finishOnce(() => failCode?.(new Error("Invalid OAuth callback")));
          return;
        }
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        res.end(
          "<!doctype html><title>Vectoree</title><body style=\"font-family:sans-serif\"><h1>Vectoree connected</h1><p>You can close this window and return to vectoree-deer-flow.</p></body>",
        );
        finishOnce(() => settleCode?.(authCode));
      } catch (error) {
        finishOnce(() =>
          failCode?.(
            error instanceof Error ? error : new Error("Invalid OAuth callback"),
          ),
        );
        if (!res.headersSent) res.writeHead(500).end("Callback failed");
      }
    });
    server.listen(port, host, () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        reject(new Error("Could not open the login callback"));
        return;
      }
      resolve({
        port: address.port,
        code,
        close: (reason = "Login cancelled") => {
          finishOnce(() => failCode?.(new Error(reason)));
        },
      });
    });
    server.on("error", reject);
  });
}

async function readBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return { message: text.slice(0, 500) };
  }
}

function readErrorMessage(data: unknown, fallback: string): string {
  if (!data || typeof data !== "object") return fallback;
  const record = data as Record<string, unknown>;
  if (typeof record.message === "string" && record.message.trim()) {
    return record.message;
  }
  const error = record.error;
  if (typeof error === "string" && error.trim()) return error;
  if (error && typeof error === "object") {
    const nested = (error as { message?: unknown }).message;
    if (typeof nested === "string" && nested.trim()) return nested;
  }
  return fallback;
}

function openSystemBrowser(url: string): Promise<void> {
  const command =
    process.platform === "darwin"
      ? "open"
      : process.platform === "win32"
        ? "cmd"
        : "xdg-open";
  const args = process.platform === "win32" ? ["/c", "start", "", url] : [url];
  return new Promise((resolve) => {
    execFile(command, args, () => resolve());
  });
}
