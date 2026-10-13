import { afterEach, describe, expect, test } from "@rstest/core";

import {
  getBasePath,
  normalizeBasePath,
  stripBasePath,
  withBasePath,
} from "@/base-path";
import { getBackendBaseURL, getLangGraphBaseURL } from "@/core/config";

const original = process.env.NEXT_PUBLIC_BASE_PATH;

afterEach(() => {
  if (original === undefined) delete process.env.NEXT_PUBLIC_BASE_PATH;
  else process.env.NEXT_PUBLIC_BASE_PATH = original;
});

describe("normalizeBasePath", () => {
  test("accepts the usual spellings", () => {
    expect(normalizeBasePath(undefined)).toBe("");
    expect(normalizeBasePath("")).toBe("");
    expect(normalizeBasePath("/")).toBe("");
    expect(normalizeBasePath("deerflow")).toBe("/deerflow");
    expect(normalizeBasePath(" /deerflow/ ")).toBe("/deerflow");
  });
});

describe("without a base path", () => {
  test("leaves paths alone", () => {
    delete process.env.NEXT_PUBLIC_BASE_PATH;
    expect(getBasePath()).toBe("");
    expect(withBasePath("/api/v1/auth/me")).toBe("/api/v1/auth/me");
    expect(stripBasePath("/workspace")).toBe("/workspace");
    expect(getBackendBaseURL()).toBe("");
  });
});

describe("under /deerflow", () => {
  test("prefixes site paths once", () => {
    process.env.NEXT_PUBLIC_BASE_PATH = "/deerflow";
    expect(withBasePath("/api/v1/auth/me")).toBe("/deerflow/api/v1/auth/me");
    expect(withBasePath("/")).toBe("/deerflow/");
    expect(withBasePath("/deerflow/api/x")).toBe("/deerflow/api/x");
    expect(withBasePath("/deerflow")).toBe("/deerflow");
    expect(withBasePath("/deerflowx")).toBe("/deerflow/deerflowx");
  });

  test("leaves absolute, protocol-relative and data URLs alone", () => {
    process.env.NEXT_PUBLIC_BASE_PATH = "/deerflow";
    expect(withBasePath("https://vectoree.ai/x")).toBe("https://vectoree.ai/x");
    expect(withBasePath("//cdn.example/x")).toBe("//cdn.example/x");
    expect(withBasePath("data:image/png;base64,AA")).toBe(
      "data:image/png;base64,AA",
    );
  });

  test("strips the base from browser pathnames", () => {
    process.env.NEXT_PUBLIC_BASE_PATH = "/deerflow";
    expect(stripBasePath("/deerflow/workspace/chats")).toBe("/workspace/chats");
    expect(stripBasePath("/deerflow")).toBe("/");
    expect(stripBasePath("/other")).toBe("/other");
  });

  test("backend and LangGraph URLs carry the base", () => {
    process.env.NEXT_PUBLIC_BASE_PATH = "/deerflow";
    expect(getBackendBaseURL()).toBe("/deerflow");
    expect(getLangGraphBaseURL()).toMatch(/\/deerflow\/api\/langgraph$/);
    expect(getLangGraphBaseURL(true)).toMatch(/\/deerflow\/mock\/api$/);
  });
});
