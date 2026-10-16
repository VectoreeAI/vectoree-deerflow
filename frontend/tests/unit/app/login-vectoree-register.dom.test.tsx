import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const push = rs.fn();

rs.mock("next/navigation", () => ({
  useRouter: () => ({ replace: rs.fn(), push }),
  useSearchParams: () => new URLSearchParams(),
}));
rs.mock("next-themes", () => ({
  useTheme: () => ({ theme: "light", resolvedTheme: "light" }),
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ isAuthenticated: false }),
}));
rs.mock("@/components/ui/flickering-grid", () => ({
  FlickeringGrid: () => null,
}));

import LoginPage from "@/app/(auth)/login/page";
import { I18nProvider } from "@/core/i18n/context";

function jsonResponse(body: unknown, ok = true) {
  return { ok, status: ok ? 200 : 400, json: async () => body } as Response;
}

function routeResponse(value: unknown): Response {
  if (
    typeof value === "object" &&
    value !== null &&
    "body" in value &&
    "ok" in value &&
    typeof (value as { ok: unknown }).ok === "boolean"
  ) {
    const routed = value as { body: unknown; ok: boolean };
    return jsonResponse(routed.body, routed.ok);
  }
  return jsonResponse(value);
}

type Call = { url: string; body: unknown };

function mockGateway(routes: Record<string, unknown>) {
  const calls: Call[] = [];
  rs.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = input instanceof Request ? input.url : input.toString();
    const raw = init?.body;
    calls.push({
      url,
      body:
        typeof raw === "string" && raw.startsWith("{") ? JSON.parse(raw) : raw,
    });
    if (url.includes("link-status")) {
      return jsonResponse({ linked: true, deployMode: "local" });
    }
    if (url.includes("setup-status")) {
      return jsonResponse({ needs_setup: false, vectoree_linked: true });
    }
    const route = Object.keys(routes).find((path) => url.includes(path));
    if (route) return routeResponse(routes[route]);
    return jsonResponse({ providers: [] });
  });
  return calls;
}

function renderPage() {
  render(
    <I18nProvider initialLocale="en-US">
      <LoginPage />
    </I18nProvider>,
  );
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

afterEach(() => {
  cleanup();
  push.mockReset();
  rs.restoreAllMocks();
});

describe("Vectoree email registration", () => {
  it("collects everything on one form and returns to sign-in without logging in", async () => {
    const calls = mockGateway({
      "/vectoree/register/code": { code_sent: true },
      "/vectoree/register/complete": { created: true },
    });
    renderPage();

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Don't have an account? Sign up",
      }),
    );
    type("Email", "new@example.com");
    type("Password", "password123");
    type("Confirm password", "password123");

    fireEvent.click(screen.getByRole("button", { name: "Send code" }));
    expect(
      await screen.findByRole("button", { name: /Resend in \d+s/ }),
    ).toBeTruthy();
    expect(
      calls.find((call) => call.url.includes("/vectoree/register/code"))?.body,
    ).toEqual({ email: "new@example.com", password: "password123" });

    type("Verification code", "12345678");
    fireEvent.click(screen.getByRole("button", { name: "Create Account" }));

    expect(
      await screen.findByText("Account created. Please sign in."),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sign In" })).toBeTruthy();
    expect(screen.getByLabelText<HTMLInputElement>("Email").value).toBe(
      "new@example.com",
    );
    expect(
      calls.find((call) => call.url.includes("/vectoree/register/complete"))
        ?.body,
    ).toEqual({ email: "new@example.com", otp: "12345678" });
    expect(calls.some((call) => call.url.includes("/vectoree/verify"))).toBe(
      false,
    );
    expect(push).not.toHaveBeenCalled();
  });

  it("does not send a code when the passwords differ", async () => {
    const calls = mockGateway({});
    renderPage();

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Don't have an account? Sign up",
      }),
    );
    type("Email", "new@example.com");
    type("Password", "password123");
    type("Confirm password", "password124");
    fireEvent.click(screen.getByRole("button", { name: "Send code" }));

    expect(await screen.findByText("Passwords do not match")).toBeTruthy();
    expect(calls.some((call) => call.url.includes("/register/code"))).toBe(
      false,
    );
  });
});

describe("Vectoree email code login", () => {
  it("signs in with an emailed code", async () => {
    const calls = mockGateway({
      "/vectoree/resend": { ok: true },
      "/vectoree/verify": { expires_in: 3600, needs_setup: false },
    });
    renderPage();

    fireEvent.click(await screen.findByRole("tab", { name: "Email code" }));
    expect(screen.queryByLabelText("Password")).toBeNull();
    type("Email", "ada@example.com");
    fireEvent.click(screen.getByRole("button", { name: "Send code" }));
    expect(
      await screen.findByText("A verification code was sent to your email."),
    ).toBeTruthy();

    type("Verification code", "87654321");
    fireEvent.click(screen.getByRole("button", { name: "Sign In" }));

    expect(
      await screen.findByRole("button", { name: "Please wait..." }),
    ).toBeTruthy();
    expect(push).toHaveBeenCalledWith("/workspace");
    expect(
      calls.find((call) => call.url.includes("/vectoree/verify"))?.body,
    ).toMatchObject({ email: "ada@example.com", otp: "87654321" });
  });

  it("links an unfunded wallet to organization billing", async () => {
    mockGateway({
      "/vectoree/resend": {
        ok: false,
        body: {
          detail: {
            code: "billing_wallet_not_activated",
            message: "Organization wallet is not activated",
            billing_url: "https://vectoree.ai/dashboard/organization/billing",
          },
        },
      },
    });
    renderPage();

    fireEvent.click(await screen.findByRole("tab", { name: "Email code" }));
    type("Email", "ada@example.com");
    fireEvent.click(screen.getByRole("button", { name: "Send code" }));

    const link = await screen.findByRole("link", { name: "organization billing" });
    expect(link.getAttribute("href")).toBe(
      "https://vectoree.ai/dashboard/organization/billing",
    );
    expect(screen.getByRole("alert").textContent).toContain(
      "has not been topped up",
    );
    expect(screen.queryByText("Organization wallet is not activated")).toBeNull();
    expect(screen.queryByText("钱包未激活")).toBeNull();
  });

  it("asks an unknown email to sign up before sending a code", async () => {
    mockGateway({
      "/vectoree/resend": {
        ok: false,
        body: {
          detail: {
            code: "account_not_registered",
            message: "This account is not registered. Please sign up.",
          },
        },
      },
    });
    renderPage();

    fireEvent.click(await screen.findByRole("tab", { name: "Email code" }));
    type("Email", "new@example.com");
    fireEvent.click(screen.getByRole("button", { name: "Send code" }));

    expect(
      await screen.findByText("This email is not registered. Please sign up first."),
    ).toBeTruthy();
    expect(screen.queryByText("A verification code was sent to your email.")).toBeNull();
  });
});

describe("Vectoree registration wallet", () => {
  it("links an unfunded wallet to organization billing", async () => {
    mockGateway({
      "/vectoree/register/code": {
        ok: false,
        body: {
          detail: {
            code: "billing_wallet_not_activated",
            message: "Organization wallet is not activated",
            billing_url: "https://vectoree.ai/dashboard/organization/billing",
          },
        },
      },
    });
    renderPage();

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Don't have an account? Sign up",
      }),
    );
    type("Email", "new@example.com");
    type("Password", "password123");
    type("Confirm password", "password123");
    fireEvent.click(screen.getByRole("button", { name: "Send code" }));

    const link = await screen.findByRole("link", { name: "organization billing" });
    expect(link.getAttribute("href")).toBe(
      "https://vectoree.ai/dashboard/organization/billing",
    );
    expect(screen.queryByText("A verification code was sent to your email.")).toBeNull();
  });
});
