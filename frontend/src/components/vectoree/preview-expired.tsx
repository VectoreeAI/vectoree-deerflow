import type { Translations } from "@/core/i18n/locales";

export function PreviewExpired({
  t,
  reason,
}: {
  t: Translations["previewExpired"];
  reason?: string;
}) {
  const unavailable = reason === "unavailable";
  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <div className="max-w-md space-y-3 text-center">
        <h1 className="text-2xl font-semibold">
          {unavailable ? t.unavailableTitle : t.title}
        </h1>
        <p className="text-muted-foreground">
          {unavailable ? t.unavailableDescription : t.description}
        </p>
      </div>
    </main>
  );
}
