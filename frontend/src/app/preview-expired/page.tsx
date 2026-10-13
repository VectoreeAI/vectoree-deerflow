import { PreviewExpired } from "@/components/vectoree/preview-expired";
import { getI18n } from "@/core/i18n/server";

export const dynamic = "force-dynamic";

export default async function PreviewExpiredPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const [{ t }, params] = await Promise.all([getI18n(), searchParams]);
  const reason = typeof params.reason === "string" ? params.reason : undefined;
  return <PreviewExpired t={t.previewExpired} reason={reason} />;
}
