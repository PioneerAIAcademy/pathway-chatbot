/**
 * Session management for Langfuse tracking.
 * Uses FingerprintJS for stable device identification.
 */

import FingerprintJS from "@fingerprintjs/fingerprintjs";

const SESSION_KEY = "pathway-missionary-assistant-session";
const SESSION_TS_KEY = "pathway-missionary-assistant-session-ts";
const DEVICE_KEY = "pathway-missionary-assistant-device";

/** Rotate the session after 30 minutes of inactivity. */
const SESSION_TTL_MS = 30 * 60 * 1000;

// Initialize FingerprintJS once
const fpPromise = typeof window !== "undefined" ? FingerprintJS.load() : null;

/**
 * Get or create a device fingerprint using FingerprintJS.
 * Highly stable across sessions, VPN changes, timezone changes, etc.
 */
export async function getDeviceId(): Promise<string> {
  if (typeof window === "undefined" || !fpPromise) return "";

  // Check cache first
  const cached = localStorage.getItem(DEVICE_KEY);
  if (cached) return cached;

  // Generate fingerprint
  const fp = await fpPromise;
  const result = await fp.get();
  const deviceId = result.visitorId;

  // Cache it
  localStorage.setItem(DEVICE_KEY, deviceId);
  return deviceId;
}

/**
 * Get or create a session ID.
 * - Returns the existing session ID if it was active within the last 30 minutes.
 * - Creates and stores a new UUID if none exists or the previous session expired.
 * - Each call refreshes the activity timestamp so the session stays alive
 *   as long as the user keeps interacting.
 */
export function getSessionId(): string {
  if (typeof window === "undefined") {
    return "";
  }

  const now = Date.now();
  const storedId = localStorage.getItem(SESSION_KEY);
  const storedTs = localStorage.getItem(SESSION_TS_KEY);

  // Reuse the existing session if it's still within the TTL window.
  if (storedId && storedTs && now - Number(storedTs) < SESSION_TTL_MS) {
    // Refresh the timestamp on every access (sliding window).
    localStorage.setItem(SESSION_TS_KEY, String(now));
    return storedId;
  }

  // Either no session exists or it expired — create a fresh one.
  const sessionId = crypto.randomUUID();
  localStorage.setItem(SESSION_KEY, sessionId);
  localStorage.setItem(SESSION_TS_KEY, String(now));
  return sessionId;
}

/**
 * Clear the current session (e.g., when user wants to start fresh)
 */
export function clearSession(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(SESSION_KEY);
  localStorage.removeItem(SESSION_TS_KEY);
}

/**
 * Create a new session (clears old and generates new)
 */
export function newSession(): string {
  clearSession();
  return getSessionId();
}
