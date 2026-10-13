import {
  afterEach,
  beforeEach,
  describe,
  expect,
  test,
  rs,
} from "@rstest/core";

import { AUTH_DISABLED_USER } from "@/core/auth/auth-disabled-user";
import { STATIC_WEBSITE_USER } from "@/core/auth/static-user";

rs.mock("next/headers", () => ({
  cookies: rs.fn(() => {
    throw new Error("cookies should not be read in static website mode");
  }),
}));

const ENV_KEYS = [
  "DEER_FLOW_AUTH_DISABLED",
  "DEER_FLOW_ENV",
  "ENVIRONMENT",
  "NEXT_PUBLIC_STATIC_WEBSITE_ONLY",
] as const;

type EnvSnapshot = Partial<
  Record<(typeof ENV_KEYS)[number], string | undefined>
>;

function snapshotEnv(): EnvSnapshot {
  const snapshot: EnvSnapshot = {};
  for (const key of ENV_KEYS) {
    snapshot[key] = process.env[key];
  }
  return snapshot;
}

function setEnv(key: (typeof ENV_KEYS)[number], value: string | undefined) {
  const env = process.env as Record<string, string | undefined>;
  if (value === undefined) {
    delete env[key];
  } else {
    env[key] = value;
  }
}

function restoreEnv(snapshot: EnvSnapshot) {
  for (const key of ENV_KEYS) {
    setEnv(key, snapshot[key]);
  }
}

async function loadFreshServerAuth() {
  rs.resetModules();
  return await import("@/core/auth/server");
}

describe("getServerSideUser", () => {
  let saved: EnvSnapshot;

  beforeEach(() => {
    saved = snapshotEnv();
    setEnv("DEER_FLOW_AUTH_DISABLED", undefined);
    setEnv("DEER_FLOW_ENV", undefined);
    setEnv("ENVIRONMENT", undefined);
    setEnv("NEXT_PUBLIC_STATIC_WEBSITE_ONLY", undefined);
  });

  afterEach(() => {
    restoreEnv(saved);
    rs.unstubAllGlobals();
  });

  test("bypasses gateway auth in static website mode", async () => {
    setEnv("NEXT_PUBLIC_STATIC_WEBSITE_ONLY", "true");
    const fetchSpy = rs.fn(() => {
      throw new Error("fetch should not be called in static website mode");
    });
    rs.stubGlobal("fetch", fetchSpy);

    const { getServerSideUser } = await loadFreshServerAuth();

    await expect(getServerSideUser()).resolves.toEqual({
      tag: "authenticated",
      user: STATIC_WEBSITE_USER,
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("bypasses gateway auth in auth-disabled mode", async () => {
    setEnv("DEER_FLOW_AUTH_DISABLED", "1");
    const fetchSpy = rs.fn(() => {
      throw new Error("fetch should not be called in auth-disabled mode");
    });
    rs.stubGlobal("fetch", fetchSpy);

    const { getServerSideUser } = await loadFreshServerAuth();

    await expect(getServerSideUser()).resolves.toEqual({
      tag: "authenticated",
      user: AUTH_DISABLED_USER,
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("does not enable auth-disabled mode in explicit production environments", async () => {
    setEnv("DEER_FLOW_AUTH_DISABLED", "1");
    setEnv("DEER_FLOW_ENV", "production");

    const { isAuthDisabledMode } =
      await import("@/core/auth/auth-disabled-user");

    expect(isAuthDisabledMode()).toBe(false);
  });
});

describe("getServerSideUser — gateway_unavailable contract (issue #3493)", () => {
  let saved: EnvSnapshot;

  beforeEach(() => {
    saved = snapshotEnv();
    setEnv("DEER_FLOW_AUTH_DISABLED", undefined);
    setEnv("NEXT_PUBLIC_STATIC_WEBSITE_ONLY", undefined);
  });

  afterEach(() => {
    restoreEnv(saved);
    rs.unstubAllGlobals();
    rs.doUnmock("next/headers");
  });

  test("returns gateway_unavailable when /auth/me fetch rejects (e.g. AbortError)", async () => {
    rs.doMock("next/headers", () => ({
      cookies: rs.fn(async () => ({
        get: (name: string) =>
          name === "access_token" ? { value: "stub-token" } : undefined,
      })),
    }));
    const abortErr = new DOMException("Aborted", "AbortError");
    rs.stubGlobal(
      "fetch",
      rs.fn(() => Promise.reject(abortErr)),
    );

    const { getServerSideUser } = await loadFreshServerAuth();

    await expect(getServerSideUser()).resolves.toEqual({
      tag: "gateway_unavailable",
    });
  });

  test("returns gateway_unavailable when /auth/me responds with a 5xx", async () => {
    rs.doMock("next/headers", () => ({
      cookies: rs.fn(async () => ({
        get: (name: string) =>
          name === "access_token" ? { value: "stub-token" } : undefined,
      })),
    }));
    rs.stubGlobal(
      "fetch",
      rs.fn(() =>
        Promise.resolve(
          new Response("upstream error", {
            status: 503,
            statusText: "Service Unavailable",
          }),
        ),
      ),
    );

    const { getServerSideUser } = await loadFreshServerAuth();

    await expect(getServerSideUser()).resolves.toEqual({
      tag: "gateway_unavailable",
    });
  });
});

describe("getServerSideUser — forwarded cookies", () => {
  let saved: EnvSnapshot;

  beforeEach(() => {
    saved = snapshotEnv();
    setEnv("DEER_FLOW_AUTH_DISABLED", undefined);
    setEnv("NEXT_PUBLIC_STATIC_WEBSITE_ONLY", undefined);
  });

  afterEach(() => {
    restoreEnv(saved);
    rs.unstubAllGlobals();
    rs.doUnmock("next/headers");
  });

  async function forwardedCookie(jar: Record<string, string>) {
    rs.doMock("next/headers", () => ({
      cookies: rs.fn(async () => ({
        get: (name: string) => (name in jar ? { value: jar[name] } : undefined),
      })),
    }));
    const fetchSpy = rs.fn(
      async (_url: string, _init?: RequestInit) =>
        new Response("{}", { status: 401 }),
    );
    rs.stubGlobal("fetch", fetchSpy);
    const { getServerSideUser } = await loadFreshServerAuth();
    await getServerSideUser();
    const init = fetchSpy.mock.calls[0]?.[1];
    return (init?.headers as Record<string, string>).Cookie;
  }

  test("sends the cloud preview cookie along with the session", async () => {
    await expect(
      forwardedCookie({
        access_token: "session",
        deerflow_preview: "preview-id",
        other: "ignored",
      }),
    ).resolves.toBe("access_token=session; deerflow_preview=preview-id");
  });

  test("sends only the session outside a preview", async () => {
    await expect(forwardedCookie({ access_token: "session" })).resolves.toBe(
      "access_token=session",
    );
  });
});
