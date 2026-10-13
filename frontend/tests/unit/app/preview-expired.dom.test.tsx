import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { PreviewExpired } from "@/components/vectoree/preview-expired";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";

afterEach(() => {
  cleanup();
});

describe("PreviewExpired", () => {
  it("explains an expired preview without offering a link entry", () => {
    render(<PreviewExpired t={zhCN.previewExpired} />);
    expect(screen.getByRole("heading", { name: "预览已过期" })).toBeTruthy();
    expect(screen.getByText(/Vectoree 控制台重新打开预览/)).toBeTruthy();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("uses the unavailable copy when Vectoree could not be reached", () => {
    render(<PreviewExpired t={enUS.previewExpired} reason="unavailable" />);
    expect(
      screen.getByRole("heading", { name: "Preview temporarily unavailable" }),
    ).toBeTruthy();
  });

  it("falls back to the expired copy for unknown reasons", () => {
    render(<PreviewExpired t={enUS.previewExpired} reason="nope" />);
    expect(
      screen.getByRole("heading", { name: "This preview has expired" }),
    ).toBeTruthy();
  });
});
