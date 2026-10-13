"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useRef, useState } from "react";

import { RememberSessionOption } from "@/components/auth/remember-session-option";
import { Button } from "@/components/ui/button";
import { FlickeringGrid } from "@/components/ui/flickering-grid";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/core/auth/AuthProvider";
import { resolveAuthNextPath } from "@/core/auth/next-path";
import {
  loadRememberLoginPreference,
  saveRememberLoginPreference,
} from "@/core/auth/remember-login";
import {
  canCreateRegularAccount,
  fetchSetupStatus,
  type SetupStatusResponse,
} from "@/core/auth/setup";
import { parseAuthError } from "@/core/auth/types";
import { withBasePath } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import {
  needsLinkPage,
  previewExpiredPath,
  readLinkGate,
} from "@/core/vectoree/project-linked";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isAuthenticated } = useAuth();
  const { theme, resolvedTheme } = useTheme();
  const { t } = useI18n();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(true);
  const [isLogin, setIsLogin] = useState(true);
  const [ssoProviders, setSsoProviders] = useState<
    { id: string; display_name: string; type: string }[]
  >([]);
  const [setupStatus, setSetupStatus] = useState<SetupStatusResponse | null>(
    null,
  );
  const [setupStatusPhase, setSetupStatusPhase] = useState<
    "checking" | "ready" | "unavailable"
  >("checking");
  const [setupStatusAttempt, setSetupStatusAttempt] = useState(0);

  // Extract error from query params (e.g., ?error=sso_failed)
  const errorParam = searchParams.get("error");
  const [submitError, setError] = useState("");
  const [showErrorParam, setShowErrorParam] = useState(Boolean(errorParam));
  // Translate at render time: the locale can switch after the first render.
  const error =
    submitError ||
    (showErrorParam && errorParam
      ? (t.login.errors[errorParam as keyof typeof t.login.errors] ??
        t.login.authFailed)
      : "");
  // Soft hint shown after a failed login when SSO is configured: an SSO-only
  // account has no local password, so the backend returns a generic
  // "incorrect email or password" (deliberately, to avoid account enumeration).
  // Nudge the user toward the SSO buttons without confirming the account exists.
  const [showSsoHint, setShowSsoHint] = useState(false);
  const [loading, setLoading] = useState(false);
  const [needsCode, setNeedsCode] = useState(false);
  const [otp, setOtp] = useState("");
  const [vectoreeLinked, setVectoreeLinked] = useState(false);
  const [vectoreeGoogle, setVectoreeGoogle] = useState(false);
  const [loginMethod, setLoginMethod] = useState<"password" | "code">(
    "password",
  );
  const [confirmPassword, setConfirmPassword] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [notice, setNotice] = useState("");
  const formRef = useRef<HTMLFormElement>(null);

  const vectoreeRegister = !isLogin && vectoreeLinked;
  const emailCodeLogin = isLogin && vectoreeLinked && loginMethod === "code";
  const showCodeField = needsCode || vectoreeRegister || emailCodeLogin;
  const showPasswordField = !needsCode && !emailCodeLogin;

  // Get next parameter for validated redirect
  const nextParam = searchParams.get("next");
  const redirectPath = resolveAuthNextPath(nextParam);
  const regularSignupAllowed =
    vectoreeLinked ||
    canCreateRegularAccount({
      // A failed probe must not expose registration while the system's setup
      // state is unknown. Existing users can still sign in normally.
      checked: setupStatusPhase === "ready",
      status: setupStatus,
    });
  const systemNeedsAdminSetup =
    setupStatus?.needs_setup === true && !vectoreeLinked;
  const showSetupStatusUnavailable =
    setupStatusPhase === "unavailable" ||
    (setupStatusAttempt > 0 && setupStatusPhase === "checking");

  useEffect(() => {
    let cancelled = false;
    void readLinkGate()
      .then((gate) => {
        if (cancelled) return;
        const expired = previewExpiredPath(gate);
        if (expired) {
          router.replace(expired);
          return;
        }
        if (needsLinkPage(gate)) {
          router.replace("/link");
          return;
        }
        setVectoreeLinked(gate.linked);
        setVectoreeGoogle(gate.gatewayLinked);
      })
      .catch(() => {
        if (!cancelled) router.replace("/link");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  // Redirect if already authenticated (client-side, post-login)
  useEffect(() => {
    if (isAuthenticated) {
      router.push(redirectPath);
    }
  }, [isAuthenticated, redirectPath, router]);

  useEffect(() => {
    const preference = loadRememberLoginPreference();
    setRememberMe(preference.rememberMe);
    if (preference.email) {
      setEmail(preference.email);
    }
  }, []);

  // Fetch setup state independently so retrying a slow Gateway does not also
  // refetch unrelated auth-provider configuration.
  useEffect(() => {
    let cancelled = false;
    setSetupStatusPhase("checking");

    void fetchSetupStatus()
      .then((data) => {
        if (cancelled) return;
        setSetupStatus(data);
        setSetupStatusPhase("ready");
        if (data.needs_setup) {
          setIsLogin(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSetupStatus(null);
          setSetupStatusPhase("unavailable");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [setupStatusAttempt]);

  // SSO providers are static for the page lifetime and should not be coupled to
  // setup-status retries.
  useEffect(() => {
    let cancelled = false;

    void fetch(withBasePath("/api/v1/auth/providers"))
      .then((r) => r.json())
      .then(
        (data: {
          providers: { id: string; display_name: string; type: string }[];
        }) => {
          if (!cancelled) {
            setSsoProviders(data.providers ?? []);
          }
        },
      )
      .catch(() => {
        // Ignore errors; no SSO providers shown
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  const resetCodeState = () => {
    setNeedsCode(false);
    setOtp("");
    setCodeSent(false);
    setCooldown(0);
  };

  const finishRegistration = () => {
    setIsLogin(true);
    setLoginMethod("password");
    setPassword("");
    setConfirmPassword("");
    resetCodeState();
    setNotice(t.login.registerSuccess);
  };

  const sendCode = async () => {
    setError("");
    setNotice("");
    setShowErrorParam(false);
    const fields = vectoreeRegister ? ["email", "password"] : ["email"];
    for (const id of fields) {
      const input = formRef.current?.querySelector<HTMLInputElement>(`#${id}`);
      if (input && !input.reportValidity()) return;
    }
    if (vectoreeRegister) {
      if (password !== confirmPassword) {
        setError(t.login.passwordMismatch);
        return;
      }
    }
    setSendingCode(true);
    try {
      const res = await fetch(
        vectoreeRegister
          ? withBasePath("/api/v1/auth/vectoree/register/code")
          : withBasePath("/api/v1/auth/vectoree/resend"),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify(
            vectoreeRegister ? { email, password } : { email },
          ),
        },
      );
      const data = (await res.json().catch(() => ({}))) as {
        created?: boolean;
      };
      if (!res.ok) {
        setError(parseAuthError(data).message || t.login.networkError);
        return;
      }
      if (vectoreeRegister && data.created) {
        finishRegistration();
        return;
      }
      setCodeSent(true);
      setCooldown(60);
      setNotice(t.login.codeSent);
    } catch {
      setError(t.login.networkError);
    } finally {
      setSendingCode(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setNotice("");
    setShowErrorParam(false);
    setShowSsoHint(false);

    if (!isLogin && !regularSignupAllowed) {
      setError(t.login.adminSetupRequiredDescription);
      return;
    }
    if (!isLogin && password !== confirmPassword) {
      setError(t.login.passwordMismatch);
      return;
    }
    if (vectoreeRegister && !codeSent) {
      setError(t.login.sendCodeFirst);
      return;
    }

    setLoading(true);
    // A first visit to the target route can compile for minutes in dev. Keep
    // the button busy until the page leaves so success does not look ignored.
    let navigating = false;
    try {
      if (vectoreeRegister) {
        const res = await fetch(
          withBasePath("/api/v1/auth/vectoree/register/complete"),
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ email, otp }),
          },
        );
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          setError(parseAuthError(data).message);
          return;
        }
        finishRegistration();
        return;
      }

      if (needsCode || emailCodeLogin) {
        const verifyRes = await fetch(
          withBasePath("/api/v1/auth/vectoree/verify"),
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ email, otp, remember_me: rememberMe }),
          },
        );
        const verifyData = await verifyRes.json().catch(() => ({}));
        if (!verifyRes.ok) {
          setError(parseAuthError(verifyData).message);
          return;
        }
        saveRememberLoginPreference({ email, rememberMe });
        navigating = true;
        router.push(redirectPath);
        return;
      }

      const endpoint = isLogin
        ? withBasePath("/api/v1/auth/login/local")
        : withBasePath("/api/v1/auth/register");
      const body = isLogin
        ? new URLSearchParams({
            password,
            remember_me: String(rememberMe),
            username: email,
          })
        : JSON.stringify({ email, password, remember_me: rememberMe });

      const headers: HeadersInit = isLogin
        ? { "Content-Type": "application/x-www-form-urlencoded" }
        : { "Content-Type": "application/json" };

      const res = await fetch(endpoint, {
        method: "POST",
        headers,
        body,
        credentials: "include", // Important: include HttpOnly cookie
      });
      const data = (await res.json().catch(() => ({}))) as {
        require_email_verification?: boolean;
        message?: string;
      };
      if (data.require_email_verification) {
        setNeedsCode(true);
        setError("");
        return;
      }

      if (!res.ok) {
        const authError = parseAuthError(data);
        setError(authError.message);
        // On a failed login with SSO configured, surface a hint pointing at the
        // SSO buttons — the "wrong password" may really mean "this is an SSO account".
        if (isLogin && !vectoreeLinked && ssoProviders.length > 0) {
          setShowSsoHint(true);
        }
        return;
      }

      saveRememberLoginPreference({ email, rememberMe });

      // Both login and register set a cookie — redirect to workspace
      navigating = true;
      router.push(redirectPath);
    } catch {
      setError(t.login.networkError);
    } finally {
      if (!navigating) setLoading(false);
    }
  };

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
      <div className="border-border/20 bg-background/5 w-full max-w-md space-y-6 rounded-3xl border p-8 backdrop-blur-sm">
        <div className="text-center">
          <h1 className="text-foreground font-serif text-3xl">
            vectoree-deer-flow
          </h1>
          <p className="text-muted-foreground mt-2">
            {isLogin ? t.login.signInTitle : t.login.createAccountTitle}
          </p>
        </div>

        {showSetupStatusUnavailable && (
          <div
            role="status"
            aria-live="polite"
            className="border-l-2 border-amber-500 ps-3 text-sm"
          >
            <p className="font-medium">{t.login.serviceUnavailableTitle}</p>
            <p className="text-muted-foreground mt-1">
              {t.login.serviceUnavailableDescription}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-3"
              disabled={setupStatusPhase === "checking"}
              onClick={() => {
                setSetupStatusPhase("checking");
                setSetupStatusAttempt((attempt) => attempt + 1);
              }}
            >
              {setupStatusPhase === "checking"
                ? t.login.pleaseWait
                : t.login.retry}
            </Button>
          </div>
        )}

        {systemNeedsAdminSetup && (
          <div className="border-l-2 border-blue-500 ps-3 text-sm">
            <p className="font-medium">{t.login.adminSetupRequiredTitle}</p>
            <p className="text-muted-foreground mt-1">
              {t.login.adminSetupRequiredDescription}
            </p>
            <Link
              href="/setup"
              className="mt-2 inline-block font-medium text-blue-500 hover:underline"
            >
              {t.login.createAdminAccount}
            </Link>
          </div>
        )}

        <form ref={formRef} onSubmit={handleSubmit} className="space-y-2">
          {isLogin && vectoreeLinked && !needsCode && (
            <div
              role="tablist"
              className="bg-muted grid grid-cols-2 gap-1 rounded-lg p-1 text-sm"
            >
              {(["password", "code"] as const).map((method) => (
                <button
                  key={method}
                  type="button"
                  role="tab"
                  aria-selected={loginMethod === method}
                  onClick={() => {
                    setLoginMethod(method);
                    setError("");
                    setNotice("");
                    resetCodeState();
                  }}
                  className={
                    loginMethod === method
                      ? "bg-background rounded-md py-1.5 font-medium shadow-sm"
                      : "text-muted-foreground rounded-md py-1.5"
                  }
                >
                  {method === "password"
                    ? t.login.passwordLogin
                    : t.login.emailCodeLogin}
                </button>
              ))}
            </div>
          )}
          <div className="flex flex-col space-y-1">
            <label htmlFor="email" className="text-sm font-medium">
              {t.login.email}
            </label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t.login.emailPlaceholder}
              required
            />
          </div>
          {showPasswordField && (
            <div className="flex flex-col space-y-1">
              <label htmlFor="password" className="text-sm font-medium">
                {t.login.password}
              </label>
              <Input
                id="password"
                type="password"
                autoComplete={isLogin ? "current-password" : "new-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t.login.passwordPlaceholder}
                required
                minLength={isLogin ? 6 : 8}
              />
            </div>
          )}
          {!isLogin && (
            <div className="flex flex-col space-y-1">
              <label htmlFor="confirm-password" className="text-sm font-medium">
                {t.login.confirmPassword}
              </label>
              <Input
                id="confirm-password"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder={t.login.passwordPlaceholder}
                required
                minLength={8}
              />
            </div>
          )}
          {showCodeField && (
            <div className="flex flex-col space-y-1">
              <label htmlFor="otp" className="text-sm font-medium">
                {t.login.verificationCode}
              </label>
              <div className="flex gap-2">
                <Input
                  id="otp"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={otp}
                  onChange={(e) =>
                    setOtp(e.target.value.replace(/\D/g, "").slice(0, 8))
                  }
                  placeholder="00000000"
                  required
                  minLength={8}
                  maxLength={8}
                  pattern="\d{8}"
                />
                <Button
                  type="button"
                  variant="outline"
                  className="shrink-0"
                  disabled={loading || sendingCode || cooldown > 0}
                  onClick={() => void sendCode()}
                >
                  {cooldown > 0
                    ? t.login.resendCodeIn(cooldown)
                    : codeSent
                      ? t.login.resendCode
                      : t.login.sendCode}
                </Button>
              </div>
            </div>
          )}

          {(isLogin || !vectoreeLinked) && (
            <RememberSessionOption
              checked={rememberMe}
              onCheckedChange={setRememberMe}
            />
          )}

          {needsCode && (
            <p className="text-muted-foreground text-sm">
              {t.login.verificationTitle}
            </p>
          )}

          {notice && !error && (
            <p role="status" className="text-sm text-green-600">
              {notice}
            </p>
          )}
          {error && <p className="text-sm text-red-500">{error}</p>}

          <Button type="submit" className="w-full" disabled={loading}>
            {loading
              ? t.login.pleaseWait
              : isLogin
                ? t.login.signIn
                : t.login.createAccount}
          </Button>
        </form>

        {vectoreeGoogle && isLogin && (
          <Button asChild variant="outline" className="w-full">
            <a
              href={withBasePath(
                `/api/v1/auth/vectoree/google/start?next=${encodeURIComponent(redirectPath)}&remember_me=${String(rememberMe)}`,
              )}
            >
              {t.login.continueWith("Google")}
            </a>
          </Button>
        )}

        {ssoProviders.length > 0 && !vectoreeLinked && (
          <div className="space-y-2">
            {isLogin && (
              <div className="relative my-4">
                <div className="absolute inset-0 flex items-center">
                  <span className="w-full border-t" />
                </div>
                <div className="relative flex justify-center text-xs uppercase">
                  <span className="bg-background text-muted-foreground px-2">
                    {t.login.orContinueWith}
                  </span>
                </div>
              </div>
            )}
            {showSsoHint && (
              <p className="text-muted-foreground text-center text-sm">
                {t.login.ssoHint}
              </p>
            )}
            {ssoProviders.map((provider) => (
              <Button
                key={provider.id}
                type="button"
                variant="outline"
                className="w-full"
                disabled={loading}
                onClick={() => {
                  window.location.href = withBasePath(
                    `/api/v1/auth/oauth/${provider.id}?next=${encodeURIComponent(redirectPath)}&remember_me=${String(rememberMe)}`,
                  );
                }}
              >
                {t.login.continueWith(provider.display_name)}
              </Button>
            ))}
          </div>
        )}

        {regularSignupAllowed && (
          <div className="text-center text-sm">
            <button
              type="button"
              onClick={() => {
                setIsLogin(!isLogin);
                setError("");
                setNotice("");
                setShowErrorParam(false);
                setShowSsoHint(false);
                setConfirmPassword("");
                resetCodeState();
              }}
              className="text-blue-500 hover:underline"
            >
              {isLogin ? t.login.noAccountSignUp : t.login.haveAccountSignIn}
            </button>
          </div>
        )}

        <div className="text-muted-foreground text-center text-xs">
          <Link href="/" className="hover:underline">
            {t.login.backToHome}
          </Link>
        </div>
      </div>
    </div>
  );
}
