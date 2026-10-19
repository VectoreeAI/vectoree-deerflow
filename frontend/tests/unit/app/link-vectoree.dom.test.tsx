import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ replace: rs.fn(), push: rs.fn() }),
}));
rs.mock("next-themes", () => ({
  useTheme: () => ({ theme: "light", resolvedTheme: "light" }),
}));
rs.mock("@/components/ui/flickering-grid", () => ({
  FlickeringGrid: () => null,
}));

import LinkVectoreePage from "@/app/link/page";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const AUTHORIZE_URL = "https://vectoree.ai/api/system/auth/cli/authorize?state=abc";

function jsonResponse(body: unknown) {
  return {
    ok: true,
    json: async () => body,
  } as Response;
}

function requestUrl(input: RequestInfo | URL) {
  if (typeof input === "string") return input;
  return input instanceof URL ? input.href : input.url;
}

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

function fillProject() {
  fireEvent.change(
    screen.getByPlaceholderText("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"),
    { target: { value: PROJECT_ID } },
  );
}

describe("Vectoree link page", () => {
  it("opens the Vectoree login during the click", async () => {
    let resolveStart: (response: Response) => void = () => undefined;
    const start = new Promise<Response>((resolve) => {
      resolveStart = resolve;
    });
    const popup = {
      closed: false,
      location: { replace: rs.fn() },
      close: rs.fn(),
      opener: window,
    };
    rs.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
    rs.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = requestUrl(input);
      if (url.includes("link-status")) {
        return jsonResponse({ linked: false, deployMode: "local" });
      }
      if (url.includes("setup-status")) {
        return jsonResponse({ vectoree_linked: false });
      }
      if (url.includes("link/start")) return start;
      return jsonResponse({ status: "pending", authorizeUrl: AUTHORIZE_URL });
    });

    render(<LinkVectoreePage />);
    fillProject();
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(window.open).toHaveBeenCalledWith("", "_blank");
    resolveStart(
      jsonResponse({ status: "pending", authorizeUrl: AUTHORIZE_URL }),
    );
    await waitFor(() => {
      expect(popup.location.replace).toHaveBeenCalledWith(AUTHORIZE_URL);
    });
  });

  it("leaves the waiting state after the browser login finishes", async () => {
    const popup = {
      closed: false,
      location: { replace: rs.fn() },
      close: rs.fn(),
      opener: window,
    };
    rs.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
    rs.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = requestUrl(input);
      if (url.includes("link-status")) {
        return jsonResponse({ linked: false, deployMode: "local" });
      }
      if (url.includes("setup-status")) {
        return jsonResponse({ vectoree_linked: false });
      }
      if (url.includes("link/start")) {
        return jsonResponse({ status: "pending", authorizeUrl: AUTHORIZE_URL });
      }
      expect(init).toMatchObject({ cache: "no-store" });
      return jsonResponse({ status: "linked", projectName: "Demo" });
    });

    render(<LinkVectoreePage />);
    fillProject();
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(await screen.findByRole("button", { name: "Continue to sign in" })).toBeTruthy();
    expect(screen.queryByText(/Waiting for browser login/)).toBeNull();
  });
});
