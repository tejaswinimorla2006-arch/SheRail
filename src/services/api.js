import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";

const TOKEN_KEY = "sherail_access_token";
const PUSH_TOKEN_KEY = "sherail_push_token";
let webAccessToken = null;

async function getAccessToken() {
  return Platform.OS === "web"
    ? webAccessToken
    : SecureStore.getItemAsync(TOKEN_KEY);
}

function getApiBaseUrl() {
  const value = process.env.EXPO_PUBLIC_API_URL;
  if (!value) {
    throw new Error("Set EXPO_PUBLIC_API_URL to the SheRail API address before signing in.");
  }
  return value.replace(/\/+$/, "");
}

function getErrorMessage(payload, status) {
  const detail = payload && payload.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg).filter(Boolean).join(" ");
  }
  return `Request failed (${status}). Please try again.`;
}

async function request(path, { method = "GET", body, authenticated = false, headers: extraHeaders } = {}) {
  const headers = { Accept: "application/json", ...extraHeaders };
  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !isFormData) headers["Content-Type"] = "application/json";
  if (authenticated) {
    const token = await getAccessToken();
    if (!token) throw new Error("Your session has expired. Please sign in again.");
    headers.Authorization = `Bearer ${token}`;
  }

  const url = `${getApiBaseUrl()}${path}`;
  let response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : isFormData ? body : JSON.stringify(body),
    });
  } catch {
    throw new Error("Could not reach SheRail. Check your connection and API address.");
  }

  if (response.status === 204) return null;

  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(getErrorMessage(payload, response.status));
  return payload;
}

async function saveToken(token) {
  if (Platform.OS === "web") {
    webAccessToken = token;
    return;
  }
  await SecureStore.setItemAsync(TOKEN_KEY, token);
}

export async function registerUser(details) {
  const result = await request("/auth/register", {
    method: "POST",
    body: details,
  });
  await saveToken(result.access_token);
  return result.user;
}

export async function loginUser(details) {
  const result = await request("/auth/login", {
    method: "POST",
    body: details,
  });
  await saveToken(result.access_token);
  return result.user;
}

export async function clearSession() {
  if (Platform.OS === "web") {
    webAccessToken = null;
    return;
  }
  const pushToken = await SecureStore.getItemAsync(PUSH_TOKEN_KEY);
  let pushRevocationError = null;
  if (pushToken) {
    try {
      await unregisterPushDevices();
    } catch (error) {
      pushRevocationError = error;
    }
  }
  await SecureStore.deleteItemAsync(TOKEN_KEY);
  await SecureStore.deleteItemAsync(PUSH_TOKEN_KEY);
  return pushRevocationError
    ? "Push alerts could not be revoked on the server while offline. Disable them from Notifications when you reconnect."
    : null;
}

export function getProfile() {
  return request("/users/me", { authenticated: true });
}

export function updateProfile(changes) {
  return request("/users/me", {
    method: "PATCH",
    body: changes,
    authenticated: true,
  });
}

export function getEmergencyContacts() {
  return request("/users/me/emergency-contacts", { authenticated: true });
}

export function createEmergencyContact(contact) {
  return request("/users/me/emergency-contacts", {
    method: "POST",
    body: contact,
    authenticated: true,
  });
}

export function updateEmergencyContact(id, changes) {
  return request(`/users/me/emergency-contacts/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: changes,
    authenticated: true,
  });
}

export function deleteEmergencyContact(id) {
  return request(`/users/me/emergency-contacts/${encodeURIComponent(id)}`, {
    method: "DELETE",
    authenticated: true,
  });
}

export function getJourneys() {
  return request("/journeys", { authenticated: true });
}

export function createJourney(details) {
  return request("/journeys", {
    method: "POST",
    body: details,
    authenticated: true,
  });
}

export function getJourney(id) {
  return request(`/journeys/${encodeURIComponent(id)}`, { authenticated: true });
}

export function startJourney(id) {
  return request(`/journeys/${encodeURIComponent(id)}/start`, {
    method: "POST",
    body: { consent: true },
    authenticated: true,
  });
}

export function pauseJourney(id) {
  return request(`/journeys/${encodeURIComponent(id)}/pause`, {
    method: "POST",
    authenticated: true,
  });
}

export function resumeJourney(id) {
  return request(`/journeys/${encodeURIComponent(id)}/resume`, {
    method: "POST",
    body: { consent: true },
    authenticated: true,
  });
}

export function setJourneyTracking(id, consent) {
  return request(`/journeys/${encodeURIComponent(id)}/tracking`, {
    method: "PATCH",
    body: { consent },
    authenticated: true,
  });
}

export function endJourney(id) {
  return request(`/journeys/${encodeURIComponent(id)}/end`, {
    method: "POST",
    authenticated: true,
  });
}

export function getSharedJourneys() {
  return request("/journeys/shared-with-me", { authenticated: true });
}

export function getSharedJourney(id) {
  return request(`/journeys/shared-with-me/${encodeURIComponent(id)}`, {
    authenticated: true,
  });
}

export function getJourneyShares(id) {
  return request(`/journeys/${encodeURIComponent(id)}/shares`, {
    authenticated: true,
  });
}

export function shareJourney(id, recipientEmail) {
  return request(`/journeys/${encodeURIComponent(id)}/shares`, {
    method: "POST",
    body: { recipient_email: recipientEmail },
    authenticated: true,
  });
}

export function revokeJourneyShare(id, recipientId) {
  return request(
    `/journeys/${encodeURIComponent(id)}/shares/${encodeURIComponent(recipientId)}`,
    { method: "DELETE", authenticated: true }
  );
}

export function revokeAllJourneyShares(id) {
  return request(`/journeys/${encodeURIComponent(id)}/shares`, {
    method: "DELETE",
    authenticated: true,
  });
}

export function updateJourneySafety(id, settings) {
  return request(`/journeys/${encodeURIComponent(id)}/safety`, {
    method: "PATCH",
    body: settings,
    authenticated: true,
  });
}

export function updateExpectedRoute(id, points) {
  return request(`/journeys/${encodeURIComponent(id)}/expected-route`, {
    method: "PUT",
    body: { points },
    authenticated: true,
  });
}

export function checkInJourney(id, idempotencyKey) {
  return request(`/journeys/${encodeURIComponent(id)}/check-in`, {
    method: "POST",
    headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
    authenticated: true,
  });
}

export function getSafetyEvents(pendingOnly = true) {
  return request(`/safety/events?pending_only=${pendingOnly ? "true" : "false"}`, {
    authenticated: true,
  });
}

export function dismissSafetyEvent(id) {
  return request(`/safety/events/${encodeURIComponent(id)}/dismiss`, {
    method: "POST",
    authenticated: true,
  });
}

export function confirmSafetyEvent(id) {
  return request(`/safety/events/${encodeURIComponent(id)}/confirm`, {
    method: "POST",
    authenticated: true,
  });
}

export function createSOSAlert(details) {
  return request("/safety/alerts/sos", {
    method: "POST",
    body: details,
    authenticated: true,
  });
}

export function getSafetyAlerts() {
  return request("/safety/alerts?limit=50", { authenticated: true });
}

export function getSafetyAlert(id) {
  return request(`/safety/alerts/${encodeURIComponent(id)}`, { authenticated: true });
}

export function cancelSafetyAlert(id) {
  return request(`/safety/alerts/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
    authenticated: true,
  });
}

export function retrySafetyAlert(id) {
  return request(`/safety/alerts/${encodeURIComponent(id)}/retry`, {
    method: "POST",
    authenticated: true,
  });
}

export function getSafetyBuddyOverview() {
  return request("/safety-buddies", { authenticated: true });
}

export function inviteSafetyBuddy(email) {
  return request("/safety-buddies/invitations", {
    method: "POST",
    body: { email },
    authenticated: true,
  });
}

export function respondToSafetyBuddyInvitation(id, accept) {
  return request(`/safety-buddies/invitations/${encodeURIComponent(id)}/respond`, {
    method: "POST",
    body: { accept },
    authenticated: true,
  });
}

export function removeSafetyBuddy(id) {
  return request(`/safety-buddies/${encodeURIComponent(id)}`, {
    method: "DELETE",
    authenticated: true,
  });
}

export function shareJourneyWithSafetyBuddy(journeyId, buddyUserId) {
  return request(
    `/safety-buddies/${encodeURIComponent(buddyUserId)}/journeys/${encodeURIComponent(journeyId)}`,
    {
      method: "POST",
      body: { location_consent: true },
      authenticated: true,
    }
  );
}

export function revokeSafetyBuddyJourneyShare(journeyId, buddyUserId) {
  return request(
    `/safety-buddies/${encodeURIComponent(buddyUserId)}/journeys/${encodeURIComponent(journeyId)}`,
    { method: "DELETE", authenticated: true }
  );
}

export function getSafetyBuddyAlerts() {
  return request("/safety-buddies/alerts?limit=100", { authenticated: true });
}

export function markSafetyBuddyAlertRead(id) {
  return request(`/safety-buddies/alerts/${encodeURIComponent(id)}/read`, {
    method: "POST",
    authenticated: true,
  });
}

export function getNearbyHelp({ latitude, longitude, radius_m = 5000 }) {
  return request("/map/nearby", {
    method: "POST",
    body: { latitude, longitude, radius_m, location_consent: true },
    authenticated: true,
  });
}

export function getNearbyAssistancePoints({ latitude, longitude, radius_m = 5000 }) {
  return request("/map/assistance-points/nearby", {
    method: "POST",
    body: { latitude, longitude, radius_m, location_consent: true },
    authenticated: true,
  });
}

export function getVerifiedCommunityReports({ latitude, longitude, radius_m = 5000 }) {
  return request("/map/reports/search", {
    method: "POST",
    body: { latitude, longitude, radius_m, location_consent: true },
    authenticated: true,
  });
}

export function submitCommunitySafetyReport(details) {
  return request("/map/reports", {
    method: "POST",
    body: { ...details, location_consent: true },
    authenticated: true,
  });
}

export function submitCommunitySafetyReportWithImages(details, images) {
  const body = new FormData();
  body.append("report_type", details.report_type);
  body.append("description", details.description);
  body.append("latitude", String(details.latitude));
  body.append("longitude", String(details.longitude));
  body.append("location_consent", "true");
  images.forEach((image, index) => {
    body.append("images", {
      uri: image.uri,
      name: image.fileName || `community-report-${index + 1}.jpg`,
      type: image.mimeType || "image/jpeg",
    });
  });
  return request("/map/reports/submit", {
    method: "POST",
    body,
    authenticated: true,
  });
}

export function getMyCommunityReports() {
  return request("/map/reports/mine", { authenticated: true });
}

export async function getAuthenticatedImageSource(path) {
  const token = await getAccessToken();
  if (!token) throw new Error("Your session has expired. Please sign in again.");
  return {
    uri: `${getApiBaseUrl()}${path}`,
    headers: { Authorization: `Bearer ${token}` },
  };
}

export function getSafetyMapModeratorAccess() {
  return request("/map/moderation/access", { authenticated: true });
}

export function getPendingSafetyMapReports() {
  return request("/map/moderation/reports", { authenticated: true });
}

export function reviewCommunitySafetyReport(id, status, moderator_note) {
  return request(`/map/moderation/reports/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: { status, moderator_note },
    authenticated: true,
  });
}

export function getRailwayAssistance(station = "") {
  const query = station.trim()
    ? `?station=${encodeURIComponent(station.trim())}`
    : "";
  return request(`/railway-assistance${query}`, { authenticated: true });
}

export function getNotifications(unreadOnly = false) {
  return request(`/notifications?unread_only=${unreadOnly ? "true" : "false"}`, {
    authenticated: true,
  });
}

export async function registerPushDevice(expo_push_token, platform) {
  await request("/notifications/devices", {
    method: "POST",
    body: { expo_push_token, platform },
    authenticated: true,
  });
  if (Platform.OS !== "web") {
    await SecureStore.setItemAsync(PUSH_TOKEN_KEY, expo_push_token);
  }
}

export function getPushDeviceStatus() {
  return request("/notifications/devices", { authenticated: true });
}

export async function unregisterPushDevices() {
  await request("/notifications/devices/revoke-all", {
    method: "POST",
    authenticated: true,
  });
  if (Platform.OS !== "web") {
    await SecureStore.deleteItemAsync(PUSH_TOKEN_KEY);
  }
}

export function markNotificationRead(id) {
  return request(`/notifications/${encodeURIComponent(id)}/read`, {
    method: "POST",
    authenticated: true,
  });
}

export function markAllNotificationsRead() {
  return request("/notifications/read-all", {
    method: "POST",
    authenticated: true,
  });
}

export async function connectJourneySocket(
  journeyId,
  { trackingConsent = false, onMessage, onDisconnect } = {}
) {
  const token = await getAccessToken();
  if (!token) throw new Error("Your session has expired. Please sign in again.");

  const websocketUrl = getApiBaseUrl()
    .replace(/^https:/i, "wss:")
    .replace(/^http:/i, "ws:");
  const url = `${websocketUrl}/ws/journeys/${encodeURIComponent(journeyId)}`;

  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url);
    let authenticated = false;
    let finished = false;
    const timeout = setTimeout(() => {
      socket.close();
      reject(new Error("Live location connection timed out. Please try again."));
      finished = true;
    }, 12000);

    socket.onopen = () => {
      socket.send(JSON.stringify({
        type: "authenticate",
        access_token: token,
        tracking_consent: trackingConsent,
      }));
    };

    socket.onmessage = (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }

      if (message.type === "authenticated" && !authenticated) {
        authenticated = true;
        finished = true;
        clearTimeout(timeout);
        resolve({
          sendLocation(location) {
            if (socket.readyState !== WebSocket.OPEN) return false;
            socket.send(JSON.stringify({ type: "location", ...location }));
            return true;
          },
          close() {
            socket.close();
          },
        });
        return;
      }

      if (message.type === "error" && !authenticated) {
        clearTimeout(timeout);
        finished = true;
        socket.close();
        reject(new Error(message.detail || "Live location connection was rejected."));
        return;
      }
      if (authenticated && onMessage) onMessage(message);
    };

    socket.onerror = () => {
      if (!authenticated && !finished) {
        finished = true;
        clearTimeout(timeout);
        reject(new Error("Could not connect to live location sharing."));
      }
    };

    socket.onclose = (event) => {
      clearTimeout(timeout);
      if (!authenticated && !finished) {
        finished = true;
        reject(new Error(event.reason || "Live location connection was closed."));
      } else if (authenticated && onDisconnect) {
        onDisconnect(event);
      }
    };
  });
}
