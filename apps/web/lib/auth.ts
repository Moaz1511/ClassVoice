export const SESSION_STORAGE_KEY = "classvoice.session";

export type SessionState = "checking" | "signed-in" | "signed-out";

export function hasStoredSession(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(SESSION_STORAGE_KEY) === "active";
}

export function signOut(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
  }
}

export function beginLocalSession(): void {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(SESSION_STORAGE_KEY, "active");
  }
}
