import { Platform } from "react-native";
import * as Notifications from "expo-notifications";
import { AndroidImportance, IosAuthorizationStatus } from "expo-notifications";

const CHANNEL_ID = "sherail-safety";
export const CHECKIN_NOTIFICATION_KIND = "sherail-checkin";

export async function requestSafetyNotificationPermission() {
  if (Platform.OS === "web") {
    throw new Error("Safety reminders are available in the SheRail mobile app.");
  }
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync(CHANNEL_ID, {
      name: "Safety reminders",
      importance: AndroidImportance.HIGH,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: "#d47b8f",
    });
  }
  const current = await Notifications.getPermissionsAsync();
  if (current.granted || current.ios?.status === IosAuthorizationStatus.PROVISIONAL) {
    return true;
  }
  const requested = await Notifications.requestPermissionsAsync();
  return requested.granted
    || requested.ios?.status === IosAuthorizationStatus.PROVISIONAL;
}

export async function scheduleSafetyCheckinNotification(dueAt) {
  const result = await reconcileSafetyCheckinNotification(dueAt);
  return result.notificationId || null;
}

export async function reconcileSafetyCheckinNotification(dueAt) {
  if (Platform.OS === "web") return { status: "unavailable", notificationId: null };
  const due = new Date(dueAt);
  if (!Number.isFinite(due.getTime())) {
    await cancelSafetyCheckinNotification();
    return { status: "not_scheduled", notificationId: null };
  }
  if (due.getTime() <= Date.now()) {
    await cancelSafetyCheckinNotification();
    return { status: "expired", notificationId: null };
  }

  const permissions = await Notifications.getPermissionsAsync();
  if (
    !permissions.granted
    && permissions.ios?.status !== IosAuthorizationStatus.PROVISIONAL
  ) {
    await cancelSafetyCheckinNotification();
    return { status: "permission_denied", notificationId: null };
  }

  const dueIso = due.toISOString();
  const scheduled = await Notifications.getAllScheduledNotificationsAsync();
  const existing = scheduled.find((item) =>
    item.content.data?.kind === CHECKIN_NOTIFICATION_KIND
    && item.content.data?.due_at === dueIso
  );
  if (existing) return { status: "scheduled", notificationId: existing.identifier };

  await cancelSafetyCheckinNotification();

  const notificationId = await Notifications.scheduleNotificationAsync({
    content: {
      title: "SheRail safety check-in",
      body: "Please confirm you're safe to keep your journey's safety check-ins active.",
      data: { kind: CHECKIN_NOTIFICATION_KIND, due_at: dueIso },
      sound: true,
    },
    trigger: {
      type: Notifications.SchedulableTriggerInputTypes.DATE,
      date: due,
      channelId: CHANNEL_ID,
    },
  });
  return { status: "scheduled", notificationId };
}

export async function presentSafetyEventNotification(event) {
  if (Platform.OS === "web") return null;
  const permissions = await Notifications.getPermissionsAsync();
  if (
    !permissions.granted
    && permissions.ios?.status !== IosAuthorizationStatus.PROVISIONAL
  ) {
    return null;
  }
  const title = event.event_type === "route_deviation"
    ? "SheRail route check"
    : "SheRail long-stop check";
  return Notifications.scheduleNotificationAsync({
    content: {
      title,
      body: "Please confirm you're safe. Emergency contacts are not notified unless you approve escalation.",
      data: { kind: "sherail-safety-event", event_id: event.id },
      sound: true,
    },
    trigger: null,
  });
}

export async function cancelSafetyCheckinNotification() {
  if (Platform.OS === "web") return;
  const scheduled = await Notifications.getAllScheduledNotificationsAsync();
  await Promise.all(
    scheduled
      .filter((item) => item.content.data?.kind === CHECKIN_NOTIFICATION_KIND)
      .map((item) => Notifications.cancelScheduledNotificationAsync(item.identifier))
  );
}
