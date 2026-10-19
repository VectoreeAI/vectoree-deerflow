/**
 * Public URL prefix when DeerFlow is mounted below a shared domain, e.g.
 * `https://<host>/deerflow` next to Vectoree and the starter.
 *
 * Fixed at build time: Next.js bakes `basePath` into the build output, so the
 * image is built with `NEXT_PUBLIC_BASE_PATH=/deerflow`. Shared with
 * `next.config.js`, which is why this is plain JavaScript.
 */

/**
 * @param {string | undefined} raw
 * @returns {string} `"/deerflow"` style prefix, or `""` for the site root
 */
export function normalizeBasePath(raw) {
  const trimmed = (raw ?? "").trim().replace(/^\/+|\/+$/g, "");
  return trimmed ? `/${trimmed}` : "";
}

/** @returns {string} */
export function getBasePath() {
  return normalizeBasePath(process.env.NEXT_PUBLIC_BASE_PATH);
}

/**
 * Prefix a site path such as `/api/v1/auth/me` with the public base.
 *
 * Only for hand-built addresses: `fetch`, `window.location`, native `<a>` and
 * `<img>`. Next's `Link`, `router.push` and `redirect()` add the prefix
 * themselves and must not receive it twice.
 *
 * @param {string} path
 * @returns {string}
 */
export function withBasePath(path) {
  const base = getBasePath();
  if (!base || !path.startsWith("/") || path.startsWith("//")) return path;
  if (
    path === base ||
    path.startsWith(`${base}/`) ||
    path.startsWith(`${base}?`)
  )
    return path;
  return `${base}${path}`;
}

/**
 * Remove the public base from a browser pathname (`window.location.pathname`),
 * giving the app-relative path that Next navigation expects.
 *
 * @param {string} pathname
 * @returns {string}
 */
export function stripBasePath(pathname) {
  const base = getBasePath();
  if (!base) return pathname;
  if (pathname === base) return "/";
  return pathname.startsWith(`${base}/`)
    ? pathname.slice(base.length)
    : pathname;
}
