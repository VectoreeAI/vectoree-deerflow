const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

export function extractProjectId(text: string): string | null {
  const dashboard =
    /Dashboard project:[^\n]*\(([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\)/i.exec(
      text,
    );
  if (dashboard?.[1]) return dashboard[1];
  const fromUrl =
    /[?&](?:projectId|project_id)=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/i.exec(
      text,
    );
  if (fromUrl?.[1]) return fromUrl[1];
  const any = UUID.exec(text);
  return any ? any[0] : null;
}
