/**
 * Session management for Langfuse tracking.
 * Uses FingerprintJS for stable device identification.
 */

import FingerprintJS from "@fingerprintjs/fingerprintjs";

const SESSION_KEY = "pathway-missionary-assistant-session";
const DEVICE_KEY = "pathway-missionary-assistant-device";

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
 * - Returns existing session ID from localStorage if available
 * - Creates and stores a new UUID if not
 */
export function getSessionId(): string {
  if (typeof window === "undefined") {
    return "";
  }

  let sessionId = localStorage.getItem(SESSION_KEY);

  if (!sessionId) {
    sessionId = crypto.randomUUID();
    localStorage.setItem(SESSION_KEY, sessionId);
  }

  return sessionId;
}

/**
 * Clear the current session (e.g., when user wants to start fresh)
 */
export function clearSession(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(SESSION_KEY);
}

/**
 * Create a new session (clears old and generates new)
 */
export function newSession(): string {
  clearSession();
  return getSessionId();
}
