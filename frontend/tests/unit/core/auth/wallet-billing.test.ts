import { describe, expect, it } from "@rstest/core";

import { readWalletBillingUrl } from "@/core/auth/wallet-billing";

describe("readWalletBillingUrl", () => {
  it("returns the billing page for an inactive wallet", () => {
    expect(
      readWalletBillingUrl({
        detail: {
          code: "billing_wallet_not_activated",
          billing_url: "https://vectoree.ai/dashboard/organization/billing",
        },
      }),
    ).toBe("https://vectoree.ai/dashboard/organization/billing");
  });

  it("ignores other errors and unsafe urls", () => {
    expect(
      readWalletBillingUrl({
        detail: { code: "invalid_credentials", message: "Incorrect email or password" },
      }),
    ).toBeNull();
    expect(
      readWalletBillingUrl({
        detail: {
          code: "billing_wallet_not_activated",
          billing_url: "javascript:alert(1)",
        },
      }),
    ).toBeNull();
  });
});
