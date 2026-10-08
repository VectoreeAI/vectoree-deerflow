"use client";

import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { FlickeringGrid } from "@/components/ui/flickering-grid";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { needsLinkPage, readLinkGate } from "@/core/vectoree/project-linked";
import { extractProjectId } from "@/core/vectoree/project-id";

type ConnectStatus = {
  status?: "idle" | "pending" | "linked" | "error";
  authorizeUrl?: string;
  message?: string;
  projectName?: string;
  linked?: boolean;
};

export default function LinkVectoreePage() {
  const router = useRouter();
  const { theme, resolvedTheme } = useTheme();
  const [apiUrl, setApiUrl] = useState("https://vectoree.ai");
  const [paste, setPaste] = useState("");
  const [projectId, setProjectId] = useState("");
  const [authorizeUrl, setAuthorizeUrl] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [linked, setLinked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void readLinkGate()
      .then((gate) => {
        if (cancelled) return;
        if (!needsLinkPage(gate)) {
          router.replace("/login?next=/workspace");
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [router]);

  useEffect(() => {
    if (!pending) return undefined;
    let cancelled = false;
    const timer = window.setInterval(() => {
      void fetch("/api/vectoree/link")
        .then((response) => response.json() as Promise<ConnectStatus>)
        .then((status) => {
          if (cancelled) return;
          if (status.authorizeUrl) setAuthorizeUrl(status.authorizeUrl);
          if (status.status === "linked") {
            setPending(false);
            setLinked(true);
            setProjectName(status.projectName ?? "");
            setError("");
          } else if (status.status === "error") {
            setPending(false);
            setError(status.message || "Could not connect Vectoree");
          }
        })
        .catch(() => {
          if (cancelled) return;
          setPending(false);
          setError("Could not reach the local link service");
        });
    }, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [pending]);

  function onRecognize() {
    const id = extractProjectId(paste);
    if (!id) {
      setError("Paste a project ID or a Console URL that contains one.");
      return;
    }
    setError("");
    setProjectId(id);
  }

  async function onConnect() {
    setError("");
    setAuthorizeUrl("");
    setPending(true);
    try {
      const response = await fetch("/api/vectoree/link/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ apiUrl, projectId }),
      });
      const status = (await response.json()) as ConnectStatus;
      if (status.authorizeUrl) setAuthorizeUrl(status.authorizeUrl);
      if (!response.ok || status.status === "error") {
        setPending(false);
        setError(status.message || "Could not connect Vectoree");
      }
    } catch {
      setPending(false);
      setError("Could not connect Vectoree");
    }
  }

  const actualTheme = theme === "system" ? resolvedTheme : theme;

  return (
    <div className="bg-background relative flex min-h-screen items-center justify-center overflow-x-hidden overflow-y-auto">
      <FlickeringGrid
        className="absolute inset-0 z-0 mask-[url(/images/deer.svg)] mask-size-[100vw] mask-center mask-no-repeat md:mask-size-[72vh]"
        squareSize={4}
        gridGap={4}
        color={actualTheme === "dark" ? "white" : "black"}
        maxOpacity={0.3}
        flickerChance={0.25}
      />
      <div className="border-border/20 bg-background/5 relative z-10 w-full max-w-lg space-y-6 rounded-3xl border p-8 backdrop-blur-sm">
        <div className="text-center">
          <h1 className="text-foreground font-serif text-3xl">Link Vectoree</h1>
          <ol className="text-muted-foreground mt-3 space-y-1 text-left text-sm">
            <li>1. Paste a project ID or Console URL</li>
            <li>2. Sign in on Vectoree</li>
            <li>3. A project key is minted and saved locally</li>
          </ol>
        </div>

        {linked ? (
          <div className="space-y-4">
            <p className="text-sm">
              Linked{projectName ? ` to ${projectName}` : ""}.
            </p>
            <p className="text-muted-foreground text-sm">
              The project key is saved in this container&apos;s /app directory.
              The Gateway writes the same key into its own /app directory.
            </p>
            <Button className="w-full" onClick={() => router.push("/login?next=/workspace")}>
              Continue to sign in
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            <label className="block space-y-1 text-sm">
              <span>API origin</span>
              <Input
                value={apiUrl}
                onChange={(event) => setApiUrl(event.target.value)}
                autoComplete="off"
                spellCheck={false}
                required
              />
            </label>
            <label className="block space-y-1 text-sm">
              <span>Project ID or Console URL</span>
              <Textarea
                value={paste}
                onChange={(event) => setPaste(event.target.value)}
                spellCheck={false}
                rows={4}
                placeholder="https://vectoree.ai/... or xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              />
            </label>
            <Button
              type="button"
              variant="outline"
              onClick={onRecognize}
              disabled={pending || !paste.trim()}
            >
              Recognize project
            </Button>
            <label className="block space-y-1 text-sm">
              <span>Recognized project ID</span>
              <Input
                value={projectId}
                onChange={(event) => setProjectId(event.target.value)}
                autoComplete="off"
                spellCheck={false}
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              />
            </label>
            {error ? (
              <p className="text-sm text-red-500" role="alert">
                {error}
              </p>
            ) : null}
            {pending ? (
              <p className="text-muted-foreground text-sm">
                Waiting for browser login…
                {authorizeUrl ? (
                  <>
                    {" "}
                    <a
                      className="underline"
                      href={authorizeUrl}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open login
                    </a>
                  </>
                ) : null}
              </p>
            ) : null}
            <Button
              className="w-full"
              type="button"
              onClick={() => void onConnect()}
              disabled={pending || !projectId.trim()}
            >
              {pending ? "Waiting for browser login…" : "Connect"}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
