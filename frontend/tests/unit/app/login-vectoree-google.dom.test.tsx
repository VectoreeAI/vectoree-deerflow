import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ replace: rs.fn(), push: rs.fn() }),
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

function jsonResponse(body: unknown) {
  return {
    ok: true,
    json: async () => body,
  };
}

function mount(linked: boolean, gatewayLinked = linked) {
  rs.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = input instanceof Request ? input.url : input.toString();
    if (url.includes("link-status")) {
      return jsonResponse({ linked, deployMode: "local" }) as Response;
    }
    if (url.includes("setup-status")) {
      return jsonResponse({
        needs_setup: false,
        vectoree_linked: gatewayLinked,
      }) as Response;
    }
    if (url.includes("/api/v1/auth/providers")) {
      return jsonResponse({
        providers: [{ id: "okta", display_name: "Okta", type: "oidc" }],
      }) as Response;
    }
    return jsonResponse({}) as Response;
  });
  return render(
    <I18nProvider initialLocale="en-US">
      <LoginPage />
    </I18nProvider>,
  );
}

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("Vectoree Google login button", () => {
  it("shows Google only when a project is linked and keeps email login", async () => {
    mount(true);
    expect(await screen.findByPlaceholderText("you@example.com")).toBeTruthy();
    expect(screen.getByPlaceholderText("•••••••")).toBeTruthy();
    const google = await screen.findByRole("link", { name: "Continue with Google" });
    expect(google.getAttribute("href")).toContain("/api/v1/auth/vectoree/google/start");
    expect(screen.queryByRole("button", { name: "Continue with Okta" })).toBeNull();
  });

  it("hides Google when only the frontend container has the project key", async () => {
    mount(true, false);
    expect(await screen.findByPlaceholderText("you@example.com")).toBeTruthy();
    await waitFor(() => {
      const urls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } })
        .mock.calls.map((call) => String(call[0]));
      expect(urls.some((url) => url.includes("setup-status"))).toBe(true);
      expect(urls.some((url) => url.includes("link-status"))).toBe(true);
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("link", { name: "Continue with Google" })).toBeNull();
  });

  it("hides the Google button when the project is not linked", async () => {
    mount(false);
    expect(await screen.findByPlaceholderText("you@example.com")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Continue with Okta" })).toBeTruthy();
    });
    expect(screen.queryByRole("link", { name: "Continue with Google" })).toBeNull();
  });
});
