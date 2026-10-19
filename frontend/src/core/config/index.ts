import { getBasePath, stripBasePath, withBasePath } from "@/base-path";
import { env } from "@/env";

export { getBasePath, stripBasePath, withBasePath };

function getBaseOrigin() {
  if (typeof window !== "undefined") {
    return window.location.origin;
  }
  // Fallback for SSR
  return "http://localhost:2026";
}

export function getBackendBaseURL() {
  if (env.NEXT_PUBLIC_BACKEND_BASE_URL) {
    return new URL(env.NEXT_PUBLIC_BACKEND_BASE_URL, getBaseOrigin())
      .toString()
      .replace(/\/+$/, "");
  } else {
    return getBasePath();
  }
}

export function getLangGraphBaseURL(isMock?: boolean) {
  if (env.NEXT_PUBLIC_LANGGRAPH_BASE_URL) {
    return new URL(
      env.NEXT_PUBLIC_LANGGRAPH_BASE_URL,
      getBaseOrigin(),
    ).toString();
  } else if (isMock) {
    if (typeof window !== "undefined") {
      return `${window.location.origin}${withBasePath("/mock/api")}`;
    }
    return `http://localhost:3000${withBasePath("/mock/api")}`;
  } else {
    // LangGraph SDK requires a full URL, construct it from current origin
    if (typeof window !== "undefined") {
      return `${window.location.origin}${withBasePath("/api/langgraph")}`;
    }
    // Fallback for SSR
    return `http://localhost:2026${withBasePath("/api/langgraph")}`;
  }
}
