import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

const replace = rs.fn();

rs.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: rs.fn() }),
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
  return { ok: true, json: async () => body } as Response;
}

function mount(previewActive: boolean | Error) {
  rs.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = input instanceof Request ? input.url : input.toString();
    if (url.includes("link-status")) {
      return jsonResponse({ linked: false, deployMode: "cloud" });
    }
    if (url.includes("setup-status")) {
      return jsonResponse({
        needs_setup: false,
        registration_enabled: previewActive === true,
        vectoree_linked: previewActive === true,
        deploy_mode: "cloud",
      });
    }
    if (url.includes("preview/status")) {
      if (previewActive instanceof Error) throw previewActive;
      return jsonResponse({ active: previewActive });
    }
    if (url.includes("/api/v1/auth/providers")) {
      return jsonResponse({ providers: [] });
    }
    return jsonResponse({});
  });
  return render(
    <I18nProvider initialLocale="en-US">
      <LoginPage />
    </I18nProvider>,
  );
}

afterEach(() => {
  cleanup();
  replace.mockReset();
  rs.restoreAllMocks();
});

describe("login page in cloud preview mode", () => {
  it("offers Google and email login for a live preview", async () => {
    mount(true);
    const google = await screen.findByRole("link", {
      name: "Continue with Google",
    });
    expect(google.getAttribute("href")).toContain(
      "/api/v1/auth/vectoree/google/start",
    );
    expect(screen.getByPlaceholderText("you@example.com")).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it("sends a visitor without a live preview to the expired page", async () => {
    mount(false);
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/preview-expired"),
    );
    expect(replace).not.toHaveBeenCalledWith("/link");
    expect(
      screen.queryByRole("link", { name: "Continue with Google" }),
    ).toBeNull();
  });

  it("marks the preview unavailable when its status cannot be read", async () => {
    mount(new Error("down"));
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(
        "/preview-expired?reason=unavailable",
      ),
    );
  });
});
