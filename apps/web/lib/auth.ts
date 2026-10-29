import { z } from "zod";

export const SESSION_STORAGE_KEY = "classvoice.session.active";
const AUTH_EVENT = "classvoice-auth-change";

export const signUpSchema = z
  .object({
    email: z.string().trim().email("Enter a valid email address."),
    displayName: z.string().trim().min(1, "Enter your name.").max(120, "Use 120 characters or fewer."),
    password: z.string().min(12, "Use at least 12 characters.").regex(/^\S+$/, "Password cannot contain spaces."),
    confirmPassword: z.string(),
    termsAccepted: z.literal(true, { error: "Accept the terms to create an account." }),
  })
  .refine((value) => value.password === value.confirmPassword, {
    message: "Passwords do not match.",
    path: ["confirmPassword"],
  });

export const signInSchema = z.object({
  email: z.string().trim().email("Enter a valid email address."),
  password: z.string().min(1, "Enter your password."),
});

export const passwordSchema = z
  .object({
    password: z.string().min(12, "Use at least 12 characters.").regex(/^\S+$/, "Password cannot contain spaces."),
    confirmPassword: z.string(),
  })
  .refine((value) => value.password === value.confirmPassword, {
    message: "Passwords do not match.",
    path: ["confirmPassword"],
  });

export type AuthUser = {
  id: string;
  email: string;
  displayName: string;
  emailVerified: boolean;
};

export type AuthSession = {
  user: AuthUser;
  expiresAt: number;
  /** Access tokens stay in memory; they are never persisted in browser storage. */
  accessToken: string;
};

export type SessionStatus = "active" | "expired" | "missing";
export type SessionState = "checking" | "signed-in" | "signed-out";

type LocalUser = AuthUser & { password: string };

const localUsers = new Map<string, LocalUser>();
let currentSession: AuthSession | null = null;
let pendingVerificationEmail: string | null = null;
let pendingResetEmail: string | null = null;

function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

function notifyAuthChange(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(AUTH_EVENT));
}

function setActiveMarker(expiresAt: number | null): void {
  if (typeof window === "undefined") return;
  if (expiresAt !== null) window.sessionStorage.setItem(SESSION_STORAGE_KEY, String(expiresAt));
  else window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
}

function createSession(user: LocalUser): AuthSession {
  const session: AuthSession = {
    user: {
      id: user.id,
      email: user.email,
      displayName: user.displayName,
      emailVerified: user.emailVerified,
    },
    expiresAt: Date.now() + 60 * 60 * 1_000,
    accessToken: crypto.randomUUID(),
  };
  currentSession = session;
  setActiveMarker(session.expiresAt);
  notifyAuthChange();
  return session;
}

export function getCurrentSession(): AuthSession | null {
  if (currentSession && currentSession.expiresAt > Date.now()) return currentSession;
  if (currentSession) {
    currentSession = null;
    setActiveMarker(null);
    notifyAuthChange();
  }
  return null;
}

export function hasStoredSession(): boolean {
  return getSessionStatus() === "active";
}

export function getSessionStatus(): SessionStatus {
  if (currentSession && currentSession.expiresAt > Date.now()) return "active";
  if (currentSession && currentSession.expiresAt <= Date.now()) {
    currentSession = null;
    setActiveMarker(null);
    notifyAuthChange();
    return "expired";
  }
  if (typeof window === "undefined") return "missing";
  const expiresAt = Number(window.sessionStorage.getItem(SESSION_STORAGE_KEY));
  if (Number.isFinite(expiresAt) && expiresAt > Date.now()) return "active";
  const hadMarker = window.sessionStorage.getItem(SESSION_STORAGE_KEY) !== null;
  window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
  return hadMarker ? "expired" : "missing";
}

export function subscribeAuth(listener: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener(AUTH_EVENT, listener);
  return () => window.removeEventListener(AUTH_EVENT, listener);
}

export function signOut(): void {
  currentSession = null;
  setActiveMarker(null);
  notifyAuthChange();
}

export async function signUp(input: z.input<typeof signUpSchema>): Promise<{ email: string }> {
  const parsed = signUpSchema.parse(input);
  const email = normalizeEmail(parsed.email);
  if (localUsers.has(email)) throw new Error("An account already exists. Sign in or reset your password.");
  localUsers.set(email, {
    id: crypto.randomUUID(),
    email,
    displayName: parsed.displayName,
    emailVerified: false,
    password: parsed.password,
  });
  pendingVerificationEmail = email;
  return { email };
}

export async function verifyEmail(email = pendingVerificationEmail): Promise<AuthUser> {
  const normalized = email ? normalizeEmail(email) : "";
  const user = localUsers.get(normalized);
  if (!user) throw new Error("This verification link is invalid or expired.");
  user.emailVerified = true;
  pendingVerificationEmail = null;
  return user;
}

export async function signIn(input: z.input<typeof signInSchema>): Promise<AuthSession> {
  const parsed = signInSchema.parse(input);
  const user = localUsers.get(normalizeEmail(parsed.email));
  if (!user || user.password !== parsed.password) throw new Error("Email or password is incorrect.");
  if (!user.emailVerified) throw new Error("Verify your email before signing in.");
  return createSession(user);
}

export async function signInWithDemo(): Promise<AuthSession> {
  const email = "teacher@classvoice.local";
  const user = localUsers.get(email) ?? {
    id: crypto.randomUUID(),
    email,
    displayName: "Demo teacher",
    emailVerified: true,
    password: crypto.randomUUID(),
  };
  user.emailVerified = true;
  localUsers.set(email, user);
  return createSession(user);
}

export async function requestPasswordReset(email: string): Promise<void> {
  const normalized = normalizeEmail(email);
  pendingResetEmail = localUsers.has(normalized) ? normalized : null;
}

export async function resetPassword(password: string): Promise<void> {
  const parsed = passwordSchema.parse({ password, confirmPassword: password });
  if (!pendingResetEmail) throw new Error("This password reset link is invalid or expired.");
  const user = localUsers.get(pendingResetEmail);
  if (!user) throw new Error("This password reset link is invalid or expired.");
  user.password = parsed.password;
  user.emailVerified = true;
  pendingResetEmail = null;
}

export function getPendingVerificationEmail(): string | null {
  return pendingVerificationEmail;
}

export function getPendingResetEmail(): string | null {
  return pendingResetEmail;
}
