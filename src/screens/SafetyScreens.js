import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Linking,
  Platform,
  SafeAreaView,
  ScrollView,
  Text,
  TextInput,
  TouchableOpacity,
  useColorScheme,
  View,
} from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import * as Location from "expo-location";
import * as SecureStore from "expo-secure-store";

import {
  cancelSafetyAlert,
  checkInJourney,
  confirmSafetyEvent,
  createSOSAlert,
  dismissSafetyEvent,
  getJourneys,
  getSafetyAlert,
  getSafetyAlerts,
  getSafetyEvents,
  retrySafetyAlert,
  updateJourneySafety,
} from "../services/api";
import { getThemeTokens } from "../theme";
import {
  cancelSafetyCheckinNotification,
  reconcileSafetyCheckinNotification,
  requestSafetyNotificationPermission,
} from "../services/safetyNotifications";

const DEEP_PINK = "#d47b8f";
const LIGHT_PINK = "#fff6f9";
const WHITE = "#fff";
const CHECKIN_INTERVALS = [5, 10, 15, 30, 60];
const UUID_PATTERN = "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx";
const PENDING_SOS_REQUEST_KEY = "sherail_pending_sos_request_id";

const formatDate = (value) => value ? new Date(value).toLocaleString() : "—";
const formatRemaining = (milliseconds) => {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
};

function alertStatusText(alert) {
  if (alert.status === "pending") return "Saved; waiting for the SMS provider.";
  if (alert.status === "queued") return "Accepted by the SMS provider; delivery receipt pending.";
  if (alert.status === "delivered") return "SMS delivery confirmed.";
  if (alert.status === "partial") return "Some contacts were notified; at least one delivery failed.";
  if (alert.status === "unconfigured") return "SMS delivery is not configured on the server.";
  if (alert.status === "unknown") return "The SMS provider outcome is unknown. Check before retrying to avoid duplicate messages.";
  if (alert.status === "cancelled") return "Cancelled as a false alarm.";
  return "SMS delivery failed. Call emergency services if you need immediate help.";
}

function getSafetyStyles(theme) {
  return {
    ...baseStyles,
    root: { ...baseStyles.root, backgroundColor: theme.background },
    title: { ...baseStyles.title, color: theme.accent },
    heading: { ...baseStyles.heading, color: theme.text },
    body: { ...baseStyles.body, color: theme.text },
    muted: { ...baseStyles.muted, color: theme.muted },
    status: { ...baseStyles.status, color: theme.text },
    countdown: { ...baseStyles.countdown, color: theme.accent },
    label: { ...baseStyles.label, color: theme.text },
    input: {
      ...baseStyles.input,
      backgroundColor: theme.surfaceMuted,
      borderColor: theme.border,
      color: theme.text,
    },
    card: {
      ...baseStyles.card,
      backgroundColor: theme.surface,
      borderColor: theme.border,
    },
    chip: { ...baseStyles.chip, borderColor: theme.accent },
    chipSelected: { ...baseStyles.chipSelected, backgroundColor: theme.accent },
    chipText: { ...baseStyles.chipText, color: theme.accent },
    chipTextSelected: { ...baseStyles.chipTextSelected, color: theme.accentForeground },
    button: { ...baseStyles.button, backgroundColor: theme.accent },
    dangerButton: { ...baseStyles.dangerButton, backgroundColor: theme.sos },
    buttonText: { ...baseStyles.buttonText, color: theme.accentForeground },
    outlineButton: { ...baseStyles.outlineButton, borderColor: theme.accent },
    outlineButtonText: { ...baseStyles.outlineButtonText, color: theme.accent },
    deliveryRow: { ...baseStyles.deliveryRow, borderTopColor: theme.border },
    error: { ...baseStyles.error, color: theme.sos },
    message: { ...baseStyles.message, color: theme.sos },
  };
}

function createRequestId() {
  return UUID_PATTERN.replace(/[xy]/g, (character) => {
    const randomValue = Math.floor(Math.random() * 16);
    const value = character === "x" ? randomValue : (randomValue & 0x3) | 0x8;
    return value.toString(16);
  });
}

function SafetyAlertCard({ alert, onCancel, onRetry, busy, themedStyles = baseStyles }) {
  return (
    <View style={themedStyles.card}>
      <Text style={themedStyles.heading}>{alert.alert_type.replace(/_/g, " ")}</Text>
      <Text style={themedStyles.body}>{alert.description}</Text>
      <Text style={themedStyles.status}>Status: {alert.status}</Text>
      <Text style={themedStyles.muted}>Created: {formatDate(alert.created_at)}</Text>
      {alert.journey_snapshot?.transport_mode ? (
        <Text style={themedStyles.muted}>
          Journey: {alert.journey_snapshot.transport_mode}
          {alert.journey_snapshot.origin ? ` · ${alert.journey_snapshot.origin}` : ""}
          {alert.journey_snapshot.destination ? ` → ${alert.journey_snapshot.destination}` : ""}
        </Text>
      ) : null}
      {alert.latitude != null && alert.longitude != null ? (
        <Text style={themedStyles.muted}>
          Location captured: {formatDate(alert.location_captured_at)}
        </Text>
      ) : null}
      {alert.deliveries.map((delivery) => (
        <View key={delivery.id} style={themedStyles.deliveryRow}>
          <Text style={themedStyles.body}>
            {delivery.contact_name} ({delivery.phone}) · {delivery.message_type}: {delivery.status}
          </Text>
          {delivery.last_error ? <Text style={themedStyles.error}>{delivery.last_error}</Text> : null}
        </View>
      ))}
      {alert.deliveries.some((delivery) =>
        ["failed", "unknown", "unconfigured"].includes(delivery.status)
      ) ? (
        <TouchableOpacity
          style={[themedStyles.outlineButton, busy && themedStyles.disabled]}
          onPress={() => onRetry(alert)}
          disabled={busy}
        >
          <Text style={themedStyles.outlineButtonText}>Retry failed/uncertain messages</Text>
        </TouchableOpacity>
      ) : null}
      {alert.status !== "cancelled" ? (
        <TouchableOpacity
          style={[themedStyles.outlineButton, busy && themedStyles.disabled]}
          onPress={() => onCancel(alert)}
          disabled={busy}
        >
          <Text style={themedStyles.outlineButtonText}>Cancel as false alarm</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );
}

export function SafetyDashboard({ navigation }) {
  const theme = getThemeTokens(useColorScheme());
  const styles = getSafetyStyles(theme);
  const themedStyles = styles;
  const [journey, setJourney] = useState(null);
  const [events, setEvents] = useState([]);
  const [checkinHistory, setCheckinHistory] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [form, setForm] = useState(null);
  const [now, setNow] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [reminderStatus, setReminderStatus] = useState("checking");
  const [reminderError, setReminderError] = useState("");
  const formJourneyId = useRef(null);

  const refreshDeviceReminder = React.useCallback(async (dueAt) => {
    try {
      if (dueAt) {
        const result = await reconcileSafetyCheckinNotification(dueAt);
        setReminderStatus(result.status);
        setReminderError("");
        return result.status;
      }
      await cancelSafetyCheckinNotification();
      setReminderStatus("not_scheduled");
      setReminderError("");
      return "not_scheduled";
    } catch (error) {
      setReminderStatus("error");
      setReminderError(error.message || "Device reminder status could not be verified.");
      return "error";
    }
  }, []);

  const refresh = React.useCallback(async (showSpinner = false) => {
    if (showSpinner) {
      setLoading(true);
      setMessage("");
    }
    try {
      const [journeys, pendingEvents, safetyHistory, alertHistory] = await Promise.all([
        getJourneys(),
        getSafetyEvents(true),
        getSafetyEvents(false),
        getSafetyAlerts(),
      ]);
      const activeJourney = journeys.find((item) => item.status === "active") || null;
      setJourney(activeJourney);
      setEvents(pendingEvents);
      setCheckinHistory(safetyHistory.filter((item) =>
        ["checkin_completed", "missed_checkin"].includes(item.event_type)
      ));
      setAlerts(alertHistory);
      if (showSpinner) {
        await refreshDeviceReminder(activeJourney?.checkin_due_at);
      }
      if (activeJourney && formJourneyId.current !== activeJourney.id) {
        formJourneyId.current = activeJourney.id;
        setForm({
          consent: activeJourney.safety_monitoring_consent,
          checkin_interval_minutes: activeJourney.checkin_interval_minutes,
          custom_checkin_interval: CHECKIN_INTERVALS.includes(activeJourney.checkin_interval_minutes)
            ? ""
            : String(activeJourney.checkin_interval_minutes || ""),
          checkin_grace_minutes: String(activeJourney.checkin_grace_minutes || 2),
          route_deviation_enabled: activeJourney.route_deviation_enabled,
          route_deviation_threshold_m: String(activeJourney.route_deviation_threshold_m || 250),
          long_stop_enabled: activeJourney.long_stop_enabled,
          long_stop_minutes: String(activeJourney.long_stop_minutes || 10),
          stop_radius_m: String(activeJourney.stop_radius_m || 50),
        });
      } else if (!activeJourney) {
        formJourneyId.current = null;
        setForm(null);
      }
    } catch (error) {
      setMessage(error.message || "Couldn't load safety monitoring.");
    } finally {
      if (showSpinner) setLoading(false);
    }
  }, [refreshDeviceReminder]);

  useFocusEffect(
    React.useCallback(() => {
      let active = true;
      const load = async (spinner) => {
        if (!active) return;
        await refresh(spinner);
      };
      load(true);
      const timer = setInterval(() => load(false), 8000);
      return () => {
        active = false;
        clearInterval(timer);
      };
    }, [refresh])
  );

  useEffect(() => {
    const refresh = () => setNow(Date.now());
    const initialTimer = setTimeout(refresh, 0);
    const timer = setInterval(refresh, 1000);
    return () => {
      clearTimeout(initialTimer);
      clearInterval(timer);
    };
  }, []);

  const updateForm = (key, value) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const saveSettings = () => {
    if (!journey || !form) return;
    const customInterval = String(form.custom_checkin_interval || "").trim();
    const checkinInterval = customInterval
      ? Number(customInterval)
      : form.checkin_interval_minutes;
    if (
      customInterval
      && (!Number.isInteger(checkinInterval) || checkinInterval < 1 || checkinInterval > 240)
    ) {
      setMessage("Enter a custom check-in interval from 1 to 240 minutes.");
      return;
    }
    const numericSettings = {
      checkin_grace_minutes: Number(form.checkin_grace_minutes),
      route_deviation_threshold_m: Number(form.route_deviation_threshold_m),
      long_stop_minutes: Number(form.long_stop_minutes),
      stop_radius_m: Number(form.stop_radius_m),
    };
    if (
      !Number.isInteger(numericSettings.checkin_grace_minutes)
      || !Number.isFinite(numericSettings.route_deviation_threshold_m)
      || !Number.isInteger(numericSettings.long_stop_minutes)
      || !Number.isFinite(numericSettings.stop_radius_m)
    ) {
      setMessage("Enter valid monitoring thresholds before saving.");
      return;
    }
    if (form.route_deviation_enabled && (journey.expected_route || []).length < 2) {
      setMessage("Set at least two expected-route waypoints before enabling route deviation alerts.");
      return;
    }

    Alert.alert(
      "Enable safety monitoring?",
      "The backend processes missed check-ins after the grace period and attempts delivery to your registered contacts; alert history reports each result. A location is included only when available from your consented journey. Route and long-stop alerts ask you to confirm before notifying contacts.",
      [
        { text: "Not now", style: "cancel" },
        {
          text: "Save with consent",
          onPress: async () => {
            setBusy(true);
            setMessage("");
            let notificationsAllowed = true;
            let notificationWarning = "";
            try {
              if (
                checkinInterval != null
                || form.route_deviation_enabled
                || form.long_stop_enabled
              ) {
                notificationsAllowed = await requestSafetyNotificationPermission();
              }
            } catch (notificationError) {
              notificationsAllowed = false;
              notificationWarning = notificationError.message || "Device notifications could not be enabled.";
            }
            try {
              const updated = await updateJourneySafety(journey.id, {
                consent: true,
                checkin_interval_minutes: checkinInterval,
                ...numericSettings,
                route_deviation_enabled: form.route_deviation_enabled,
                long_stop_enabled: form.long_stop_enabled,
              });
              setJourney(updated);
              const status = await refreshDeviceReminder(updated.checkin_due_at);
              if (status === "permission_denied") {
                notificationWarning = "device notification permission is off";
              } else if (!notificationsAllowed && !notificationWarning) {
                notificationWarning = "device notifications are unavailable";
              } else if (status === "error") {
                notificationWarning = "the device reminder status could not be verified";
              }
              const notificationsConfigured = checkinInterval != null
                || form.route_deviation_enabled
                || form.long_stop_enabled;
              setMessage(notificationWarning
                ? `Settings saved, but ${notificationWarning}`
                : notificationsConfigured && !notificationsAllowed
                  ? "Monitoring is saved. Device reminders are disabled. The backend may process missed check-ins while its safety worker is running; see alert history for delivery status."
                  : "Safety settings and consent were saved.");
              await refresh();
            } catch (error) {
              setMessage(error.message || "Couldn't save the safety settings.");
            } finally {
              setBusy(false);
            }
          },
        },
      ]
    );
  };

  const disableMonitoring = () => {
    if (!journey || !form) return;
    Alert.alert(
      "Turn off safety monitoring?",
      "Check-in schedules and GPS anomaly detection will stop. Existing alert history will remain.",
      [
        { text: "Keep enabled", style: "cancel" },
        {
          text: "Turn off",
          style: "destructive",
          onPress: async () => {
            setBusy(true);
            try {
              const updated = await updateJourneySafety(journey.id, {
                consent: false,
                checkin_interval_minutes: null,
                checkin_grace_minutes: Number(form.checkin_grace_minutes) || 2,
                route_deviation_enabled: false,
                route_deviation_threshold_m: Number(form.route_deviation_threshold_m) || 250,
                long_stop_enabled: false,
                long_stop_minutes: Number(form.long_stop_minutes) || 10,
                stop_radius_m: Number(form.stop_radius_m) || 50,
              });
              setJourney(updated);
              setForm((current) => ({
                ...current,
                consent: false,
                checkin_interval_minutes: null,
                route_deviation_enabled: false,
                long_stop_enabled: false,
              }));
              const reminderState = await refreshDeviceReminder(null);
              setMessage(reminderState === "error"
                ? "Safety monitoring was turned off, but device reminder cancellation could not be verified."
                : "Safety monitoring was turned off.");
              await refresh();
            } catch (error) {
              setMessage(error.message || "Couldn't turn off safety monitoring.");
            } finally {
              setBusy(false);
            }
          },
        },
      ]
    );
  };

  const checkIn = async () => {
    if (!journey) return;
    setBusy(true);
    setMessage("");
    try {
      const lastMissedCheckin = checkinHistory.find(
        (event) => event.event_type === "missed_checkin"
      );
      const idempotencyKey = journey.checkin_due_at
        ? `due:${journey.checkin_due_at}`
        : `resume:${journey.id}:${lastMissedCheckin?.occurred_at || "initial"}`;
      const updated = await checkInJourney(journey.id, idempotencyKey);
      setJourney(updated);
      const status = await refreshDeviceReminder(updated.checkin_due_at);
      setMessage(status === "scheduled"
        ? `Check-in recorded. Device reminder scheduled for ${formatDate(updated.checkin_due_at)}.`
        : status === "permission_denied"
          ? "Check-in recorded. Device notifications are disabled; check-in escalation is handled by the backend while its safety worker is running."
          : status === "error"
            ? "Check-in recorded, but device reminder status could not be verified."
            : "Check-in recorded. No device reminder is scheduled.");
      await refresh();
    } catch (error) {
      setMessage(error.message || "Couldn't record your check-in.");
    } finally {
      setBusy(false);
    }
  };

  const resolveEvent = (event, confirm) => {
    Alert.alert(
      confirm ? "Alert your emergency contacts?" : "Dismiss this safety check?",
      confirm
        ? "The event and latest available consented journey location will be submitted to your registered contacts. SMS delivery can fail; check the status below."
        : "This will close the prompt without contacting your emergency contacts.",
      [
        { text: "Go back", style: "cancel" },
        {
          text: confirm ? "Alert contacts" : "I'm safe",
          style: confirm ? "destructive" : "default",
          onPress: async () => {
            setBusy(true);
            try {
              if (confirm) await confirmSafetyEvent(event.id);
              else await dismissSafetyEvent(event.id);
              setMessage(confirm
                ? "The event was escalated. Check the alert status below for SMS delivery updates."
                : "Safety prompt dismissed.");
              await refresh();
            } catch (error) {
              setMessage(error.message || "Couldn't update this safety event.");
            } finally {
              setBusy(false);
            }
          },
        },
      ]
    );
  };

  const cancelAlert = (alert) => {
    Alert.alert(
      "Cancel as a false alarm?",
      "SheRail will stop any unsent messages and send a correction to contacts who may already have received the alert.",
      [
        { text: "Keep alert", style: "cancel" },
        {
          text: "Cancel alert",
          style: "destructive",
          onPress: async () => {
            setBusy(true);
            try {
              await cancelSafetyAlert(alert.id);
              setMessage("Alert cancellation recorded. Check the delivery rows for correction-message status.");
              await refresh();
            } catch (error) {
              setMessage(error.message || "Couldn't cancel this alert.");
            } finally {
              setBusy(false);
            }
          },
        },
      ]
    );
  };

  const retryAlert = (alert) => {
    Alert.alert(
      "Retry failed messages?",
      "A previous provider request may have been accepted even if its final status was lost. Retrying an uncertain message could notify a contact twice.",
      [
        { text: "Not now", style: "cancel" },
        {
          text: "Retry messages",
          onPress: async () => {
            setBusy(true);
            try {
              await retrySafetyAlert(alert.id);
              setMessage("Retry queued. Delivery status will update when the provider responds.");
              await refresh();
            } catch (error) {
              setMessage(error.message || "Couldn't retry these messages.");
            } finally {
              setBusy(false);
            }
          },
        },
      ]
    );
  };

  const callEmergencyServices = async () => {
    const phoneUrl = Platform.OS === "ios" ? "telprompt:112" : "tel:112";
    try {
      await Linking.openURL(phoneUrl);
    } catch {
      setMessage("Could not open the phone app. Dial 112 directly if you need emergency services.");
    }
  };

  const checkinDeadline = journey?.checkin_due_at
    ? new Date(journey.checkin_due_at).getTime()
    : null;
  const graceDeadline = checkinDeadline && journey?.checkin_grace_minutes
    ? checkinDeadline + journey.checkin_grace_minutes * 60_000
    : null;
  const monitoringEnabled = Boolean(journey?.safety_monitoring_consent);

  return (
    <SafeAreaView style={styles.root}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Text style={styles.title}>Safety Monitoring</Text>
        <Text style={styles.muted}>
          Check-ins and GPS monitoring are optional. Alert history reports whether each contact message was delivered.
        </Text>
        {loading ? <ActivityIndicator color={theme.accent} /> : null}
        {!loading && !journey ? (
          <View style={styles.card}>
            <Text style={styles.body}>Start a journey and enable GPS recording to configure safety monitoring.</Text>
            <TouchableOpacity style={styles.button} onPress={() => navigation.navigate("JourneyManagement")}>
              <Text style={styles.buttonText}>Open Journey Management</Text>
            </TouchableOpacity>
          </View>
        ) : null}

        {journey && form ? (
          <>
            <View style={styles.card}>
              <Text style={styles.heading}>
                {journey.transport_mode.charAt(0).toUpperCase() + journey.transport_mode.slice(1)} journey
              </Text>
              <Text style={styles.muted}>
                {journey.origin || "Starting point"} → {journey.destination || "Destination"}
              </Text>
              {checkinDeadline ? (
                <>
                  <Text style={styles.countdown}>
                    {now === null
                      ? "Loading check-in timer"
                      : now < checkinDeadline
                      ? `Check in in ${formatRemaining(checkinDeadline - now)}`
                      : graceDeadline && now < graceDeadline
                        ? `Check-in overdue · grace period ends in ${formatRemaining(graceDeadline - now)}`
                        : "Grace period ended · check alert history for server status."}
                  </Text>
                  <TouchableOpacity
                    style={[styles.button, busy && styles.disabled]}
                    onPress={checkIn}
                    disabled={busy}
                  >
                    <Text style={styles.buttonText}>I&apos;m safe — Check in now</Text>
                  </TouchableOpacity>
                  {now >= checkinDeadline ? (
                    <>
                      <TouchableOpacity
                        style={styles.outlineButton}
                        onPress={() => navigation.navigate("SOS")}
                        disabled={busy}
                      >
                        <Text style={styles.outlineButtonText}>Alert emergency contacts</Text>
                      </TouchableOpacity>
                      <TouchableOpacity
                        style={[styles.dangerButton, busy && styles.disabled]}
                        onPress={callEmergencyServices}
                        disabled={busy}
                      >
                        <Text style={styles.buttonText}>Call 112</Text>
                      </TouchableOpacity>
                    </>
                  ) : null}
                </>
              ) : monitoringEnabled && journey.checkin_interval_minutes ? (
                <>
                  <Text style={styles.muted}>
                    No check-in is currently scheduled. If a check-in was missed, its alert and delivery status remain in the history below.
                  </Text>
                  <TouchableOpacity
                    style={[styles.button, busy && styles.disabled]}
                    onPress={checkIn}
                    disabled={busy}
                  >
                    <Text style={styles.buttonText}>I&apos;m safe — Resume check-ins</Text>
                  </TouchableOpacity>
                </>
              ) : null}
            </View>

            <View style={styles.card}>
              <Text style={styles.heading}>Periodic check-ins</Text>
              <Text style={styles.muted}>A device reminder appears at the interval. After the grace period, the backend records an alert and reports each contact-delivery result.</Text>
              <Text style={styles.muted}>
                {reminderStatus === "scheduled"
                  ? `Device reminder scheduled for ${formatDate(journey.checkin_due_at)}. This reminder is not proof that an emergency alert was delivered.`
                  : reminderStatus === "permission_denied"
                    ? "Device reminder unavailable because notification permission is off. The backend may process missed check-ins while its safety worker is running; delivery status appears in alert history."
                    : reminderStatus === "unavailable"
                      ? "Device reminders are unavailable on this platform. Backend escalation requires the API safety worker to be running."
                      : reminderStatus === "expired"
                        ? "The reminder time has passed. Check alert history for the backend result; no contact delivery is assumed."
                        : reminderStatus === "error"
                          ? "Device reminder status could not be verified."
                          : reminderStatus === "checking"
                            ? "Checking device reminder status…"
                            : "No device reminder is scheduled."}
              </Text>
              {reminderError ? <Text style={styles.error}>{reminderError}</Text> : null}
              <View style={styles.optionRow}>
                {[null, ...CHECKIN_INTERVALS].map((interval) => (
                  <TouchableOpacity
                    key={interval ?? "off"}
                    style={[
                      styles.chip,
                      form.checkin_interval_minutes === interval && styles.chipSelected,
                    ]}
                    onPress={() => setForm((current) => ({
                      ...current,
                      checkin_interval_minutes: interval,
                      custom_checkin_interval: "",
                    }))}
                  >
                    <Text style={[
                      styles.chipText,
                      form.checkin_interval_minutes === interval && styles.chipTextSelected,
                    ]}>
                      {interval == null ? "Off" : `${interval} min`}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
              <Text style={styles.label}>Or enter a custom interval (1–240 minutes)</Text>
              <TextInput
                style={styles.input}
                value={form.custom_checkin_interval}
                onChangeText={(value) => setForm((current) => ({
                  ...current,
                  custom_checkin_interval: value,
                  checkin_interval_minutes: value.trim() ? Number(value) : null,
                }))}
                keyboardType="number-pad"
                placeholder="e.g. 20"
                placeholderTextColor={theme.muted}
              />
              <Text style={styles.label}>Grace period before escalation (minutes)</Text>
              <TextInput
                style={styles.input}
                value={form.checkin_grace_minutes}
                onChangeText={(value) => updateForm("checkin_grace_minutes", value)}
                keyboardType="number-pad"
                placeholder="2"
                placeholderTextColor={theme.muted}
              />
            </View>

            <View style={styles.card}>
              <Text style={styles.heading}>Route deviation</Text>
              <Text style={styles.muted}>
                Uses a private expected route you draw on the map. A detected deviation prompts you first; contacts are not notified until you confirm.
              </Text>
              <TouchableOpacity
                style={styles.outlineButton}
                onPress={() => navigation.navigate("Map", {
                  journeyId: journey.id,
                  routeEdit: true,
                })}
              >
                <Text style={styles.outlineButtonText}>
                  Set expected route ({(journey.expected_route || []).length} waypoints)
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.chip, form.route_deviation_enabled && styles.chipSelected]}
                onPress={() => updateForm("route_deviation_enabled", !form.route_deviation_enabled)}
              >
                <Text style={[
                  styles.chipText,
                  form.route_deviation_enabled && styles.chipTextSelected,
                ]}>
                  {form.route_deviation_enabled ? "Deviation monitoring on" : "Deviation monitoring off"}
                </Text>
              </TouchableOpacity>
              <Text style={styles.label}>Deviation threshold (meters)</Text>
              <TextInput
                style={styles.input}
                value={form.route_deviation_threshold_m}
                onChangeText={(value) => updateForm("route_deviation_threshold_m", value)}
                keyboardType="decimal-pad"
                placeholder="250"
                placeholderTextColor={theme.muted}
              />
            </View>

            <View style={styles.card}>
              <Text style={styles.heading}>Unexpected long stop</Text>
              <Text style={styles.muted}>
                A stationary GPS reading prompts you after the threshold. Transit stops can cause false alarms; tune or turn this off as needed.
              </Text>
              <TouchableOpacity
                style={[styles.chip, form.long_stop_enabled && styles.chipSelected]}
                onPress={() => updateForm("long_stop_enabled", !form.long_stop_enabled)}
              >
                <Text style={[
                  styles.chipText,
                  form.long_stop_enabled && styles.chipTextSelected,
                ]}>
                  {form.long_stop_enabled ? "Long-stop monitoring on" : "Long-stop monitoring off"}
                </Text>
              </TouchableOpacity>
              <Text style={styles.label}>Stationary duration (minutes)</Text>
              <TextInput
                style={styles.input}
                value={form.long_stop_minutes}
                onChangeText={(value) => updateForm("long_stop_minutes", value)}
                keyboardType="number-pad"
                placeholder="10"
                placeholderTextColor={theme.muted}
              />
              <Text style={styles.label}>Stationary radius (meters)</Text>
              <TextInput
                style={styles.input}
                value={form.stop_radius_m}
                onChangeText={(value) => updateForm("stop_radius_m", value)}
                keyboardType="decimal-pad"
                placeholder="50"
                placeholderTextColor={theme.muted}
              />
            </View>

            <TouchableOpacity
              style={[styles.button, busy && styles.disabled]}
              onPress={saveSettings}
              disabled={busy}
            >
              <Text style={styles.buttonText}>Save Settings & Consent</Text>
            </TouchableOpacity>
            {monitoringEnabled ? (
              <TouchableOpacity
                style={styles.outlineButton}
                onPress={disableMonitoring}
                disabled={busy}
              >
                <Text style={styles.outlineButtonText}>Turn off safety monitoring</Text>
              </TouchableOpacity>
            ) : null}

          </>
        ) : null}

        <View style={styles.card}>
          <Text style={styles.heading}>Voice-activated SOS</Text>
          <Text style={styles.muted}>
            Unavailable in this build. No wake-word model or Android microphone foreground service is installed, so SheRail is not listening to or recording audio.
          </Text>
          <Text style={styles.muted}>
            Enabling this safely requires a compatible native wake-word engine and model, explicit microphone consent, and an Android development build. Manual SOS remains available.
          </Text>
          <TouchableOpacity
            style={styles.outlineButton}
            onPress={() => navigation.navigate("SOS")}
          >
            <Text style={styles.outlineButtonText}>Open manual SOS</Text>
          </TouchableOpacity>
        </View>

        {events.length > 0 ? (
          <View style={styles.section}>
            <Text style={styles.heading}>Please confirm these safety prompts</Text>
            {events.map((event) => (
              <View style={styles.card} key={event.id}>
                <Text style={styles.heading}>{event.event_type.replace(/_/g, " ")}</Text>
                <Text style={styles.body}>
                  {event.event_type === "route_deviation"
                    ? `GPS is ${Math.round(event.details.distance_from_route_m || 0)}m from the expected route.`
                    : `GPS indicates you may have been stationary for about ${event.details.duration_minutes || "several"} minutes.`}
                </Text>
                <Text style={styles.muted}>Detected: {formatDate(event.occurred_at)}</Text>
                <TouchableOpacity
                  style={[styles.button, busy && styles.disabled]}
                  onPress={() => resolveEvent(event, false)}
                  disabled={busy}
                >
                  <Text style={styles.buttonText}>I&apos;m safe — Dismiss</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.dangerButton, busy && styles.disabled]}
                  onPress={() => resolveEvent(event, true)}
                  disabled={busy}
                >
                  <Text style={styles.buttonText}>Alert emergency contacts</Text>
                </TouchableOpacity>
              </View>
            ))}
          </View>
        ) : null}

        <View style={styles.section}>
          <Text style={styles.heading}>Alert history & delivery status</Text>
          {alerts.length === 0 ? (
            <Text style={styles.muted}>No safety alerts have been recorded.</Text>
          ) : alerts.map((alert) => (
            <SafetyAlertCard
              key={alert.id}
              alert={alert}
              onCancel={cancelAlert}
              onRetry={retryAlert}
              busy={busy}
              themedStyles={themedStyles}
            />
          ))}
        </View>

        <View style={styles.section}>
          <Text style={styles.heading}>Check-in history</Text>
          {checkinHistory.length === 0 ? (
            <Text style={styles.muted}>No check-ins or missed check-in events are recorded yet.</Text>
          ) : checkinHistory.map((event) => {
            const relatedAlert = alerts.find((alert) => alert.safety_event_id === event.id);
            return (
              <View style={styles.card} key={event.id}>
                <Text style={styles.heading}>
                  {event.event_type === "missed_checkin" ? "Missed check-in" : "Check-in confirmed"}
                </Text>
                <Text style={styles.muted}>Recorded: {formatDate(event.occurred_at)}</Text>
                {event.event_type === "missed_checkin" ? (
                  <Text style={styles.muted}>
                    Contact alert: {relatedAlert
                      ? `${relatedAlert.status}; see alert history for per-contact delivery`
                      : "No alert record is available"}
                  </Text>
                ) : null}
              </View>
            );
          })}
        </View>

        {message ? <Text style={styles.message}>{message}</Text> : null}
      </ScrollView>
    </SafeAreaView>
  );
}

export function SafetySOS({ navigation, route }) {
  const theme = getThemeTokens(useColorScheme());
  const styles = getSafetyStyles(theme);
  const themedStyles = styles;
  const { username } = route.params || {};
  const [activeAlert, setActiveAlert] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const requestIdRef = useRef(null);
  const requestIdPersistedRef = useRef(false);

  const getSOSRequestId = async () => {
    if (requestIdRef.current) {
      return {
        requestId: requestIdRef.current,
        persisted: requestIdPersistedRef.current,
      };
    }
    try {
      const stored = await SecureStore.getItemAsync(PENDING_SOS_REQUEST_KEY);
      const requestId = stored || createRequestId();
      if (!stored) {
        await SecureStore.setItemAsync(PENDING_SOS_REQUEST_KEY, requestId);
      }
      requestIdRef.current = requestId;
      requestIdPersistedRef.current = true;
      return { requestId, persisted: true };
    } catch {
      const requestId = createRequestId();
      requestIdRef.current = requestId;
      requestIdPersistedRef.current = false;
      return { requestId, persisted: false };
    }
  };

  useFocusEffect(
    React.useCallback(() => {
      let active = true;
      getSafetyAlerts()
        .then((items) => {
          if (!active) return;
          const current = items.find((item) => item.alert_type === "sos" && item.status !== "cancelled");
          const currentWindow = current
            && Date.now() - new Date(current.created_at).getTime() < 24 * 60 * 60 * 1000;
          setActiveAlert(currentWindow ? current : null);
        })
        .catch((error) => {
          if (active) setMessage(error.message || "Couldn't load SOS status.");
        });
      return () => {
        active = false;
      };
    }, [])
  );

  useEffect(() => {
    const hasPendingDelivery = activeAlert?.deliveries.some((delivery) =>
      ["pending", "sending", "queued", "sent"].includes(delivery.status)
    );
    if (!activeAlert || !hasPendingDelivery) return undefined;
    let active = true;
    const timer = setInterval(() => {
      getSafetyAlert(activeAlert.id)
        .then((updated) => {
          if (active) setActiveAlert(updated);
        })
        .catch((error) => {
          if (active) setMessage(error.message || "Couldn't refresh alert delivery status.");
        });
    }, 5000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [activeAlert]);

  const sendSOS = async (shareLocation) => {
    setBusy(true);
    setMessage("");
    try {
      let locationPayload = {};
      if (shareLocation) {
        const permission = await Location.requestForegroundPermissionsAsync();
        if (permission.status !== "granted") {
          setBusy(false);
          Alert.alert(
            "Location not shared",
            "SheRail couldn't access your location. You can still notify contacts without including location.",
            [
              { text: "Don't send", style: "cancel" },
              { text: "Send without location", onPress: () => sendSOS(false) },
            ]
          );
          return;
        }
        const current = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.High,
        });
        locationPayload = {
          latitude: current.coords.latitude,
          longitude: current.coords.longitude,
          location_captured_at: new Date(current.timestamp).toISOString(),
        };
      }

      const request = await getSOSRequestId();
      const created = await createSOSAlert({
        request_id: request.requestId,
        share_location: shareLocation,
        ...(shareLocation ? locationPayload : {}),
      });
      setActiveAlert(created);
      setMessage(request.persisted
        ? alertStatusText(created)
        : `${alertStatusText(created)} Secure retry protection is unavailable; a retry after app restart could create another alert.`);
      requestIdRef.current = null;
      requestIdPersistedRef.current = false;
      if (request.persisted) {
        try {
          await SecureStore.deleteItemAsync(PENDING_SOS_REQUEST_KEY);
        } catch {
          setMessage(`${alertStatusText(created)} Its retry key could not be cleared; another request may reopen this same alert.`);
        }
      }
    } catch (error) {
      setMessage(error.message || "Couldn't create the SOS alert. Call emergency services if you need immediate help.");
    } finally {
      setBusy(false);
    }
  };

  const confirmSOS = () => {
    Alert.alert(
      "Send SOS to your emergency contacts?",
      "The alert includes your journey details. Choose separately whether SheRail may include a fresh GPS location in the SMS.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Share location & alert", style: "destructive", onPress: () => sendSOS(true) },
        { text: "Alert without location", onPress: () => sendSOS(false) },
      ]
    );
  };

  const cancelFalseAlarm = () => {
    if (!activeAlert) return;
    Alert.alert(
      "Cancel this SOS as a false alarm?",
      "Unsent messages will be stopped. Contacts who may have received the SOS will get a correction.",
      [
        { text: "Keep SOS active", style: "cancel" },
        {
          text: "Cancel SOS",
          style: "destructive",
          onPress: async () => {
            setBusy(true);
            try {
              const cancelled = await cancelSafetyAlert(activeAlert.id);
              setActiveAlert(cancelled);
              setMessage("False alarm recorded. Check correction-message delivery status below.");
            } catch (error) {
              setMessage(error.message || "Couldn't cancel the SOS alert.");
            } finally {
              setBusy(false);
            }
          },
        },
      ]
    );
  };

  const callEmergencyServices = async () => {
    const phoneUrl = Platform.OS === "ios" ? "telprompt:112" : "tel:112";
    try {
      await Linking.openURL(phoneUrl);
    } catch {
      setMessage("Could not open the phone app. Dial 112 directly if you need emergency services.");
    }
  };

  return (
    <SafeAreaView style={styles.root}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Emergency SOS</Text>
        <Text style={styles.body}>For {username || "your account"}, SheRail can alert the emergency contacts on your profile by SMS. SMS delivery is not a substitute for emergency services.</Text>
        <TouchableOpacity
          style={[styles.dangerButton, busy && styles.disabled]}
          onPress={confirmSOS}
          disabled={busy}
        >
          <Text style={styles.buttonText}>{busy ? "Creating alert..." : "Send SOS to Emergency Contacts"}</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.button, { marginTop: 12 }]}
          onPress={callEmergencyServices}
        >
          <Text style={styles.buttonText}>Call Emergency Services (112)</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={styles.outlineButton}
          onPress={() => navigation.navigate("UserProfile")}
        >
          <Text style={styles.outlineButtonText}>Manage Emergency Contacts</Text>
        </TouchableOpacity>

        {activeAlert ? (
          <View style={styles.section}>
            <Text style={styles.heading}>Current SOS delivery</Text>
            <Text style={styles.status}>{alertStatusText(activeAlert)}</Text>
            <SafetyAlertCard
              alert={activeAlert}
              onCancel={cancelFalseAlarm}
              onRetry={async (alert) => {
                try {
                  setBusy(true);
                  setActiveAlert(await retrySafetyAlert(alert.id));
                  setMessage("Retry queued. Delivery status will update when the provider responds.");
                } catch (error) {
                  setMessage(error.message || "Couldn't retry these messages.");
                } finally {
                  setBusy(false);
                }
              }}
              busy={busy}
              themedStyles={themedStyles}
            />
          </View>
        ) : null}
        {message ? <Text style={styles.message}>{message}</Text> : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const baseStyles = {
  root: { flex: 1, backgroundColor: LIGHT_PINK },
  content: { padding: 16, paddingBottom: 32 },
  title: { color: DEEP_PINK, fontSize: 23, fontWeight: "800", marginBottom: 8 },
  heading: { color: "#222", fontSize: 17, fontWeight: "800", marginBottom: 7 },
  body: { color: "#333", lineHeight: 21, marginBottom: 8 },
  muted: { color: "#555", lineHeight: 19, marginBottom: 7 },
  status: { color: "#333", fontWeight: "700", marginTop: 8 },
  countdown: { color: DEEP_PINK, fontSize: 20, fontWeight: "800", marginTop: 14 },
  label: { color: "#333", fontWeight: "700", marginTop: 10, marginBottom: 6 },
  input: {
    backgroundColor: WHITE,
    borderWidth: 1,
    borderColor: "#f0d7df",
    borderRadius: 10,
    padding: 12,
    marginBottom: 10,
  },
  card: { backgroundColor: WHITE, padding: 14, borderRadius: 12, marginTop: 12 },
  section: { marginTop: 20 },
  optionRow: { flexDirection: "row", flexWrap: "wrap", marginTop: 10 },
  chip: {
    alignSelf: "flex-start",
    borderColor: DEEP_PINK,
    borderWidth: 1,
    borderRadius: 18,
    paddingVertical: 9,
    paddingHorizontal: 13,
    marginRight: 7,
    marginTop: 9,
  },
  chipSelected: { backgroundColor: DEEP_PINK },
  chipText: { color: DEEP_PINK, fontWeight: "700" },
  chipTextSelected: { color: WHITE },
  button: {
    backgroundColor: DEEP_PINK,
    padding: 14,
    borderRadius: 10,
    alignItems: "center",
    marginTop: 10,
  },
  dangerButton: {
    backgroundColor: "#a32121",
    padding: 16,
    borderRadius: 12,
    alignItems: "center",
    marginTop: 12,
  },
  buttonText: { color: WHITE, fontWeight: "800", textAlign: "center" },
  outlineButton: {
    borderColor: DEEP_PINK,
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    alignItems: "center",
    marginTop: 10,
  },
  outlineButtonText: { color: DEEP_PINK, fontWeight: "700" },
  deliveryRow: { borderTopWidth: 1, borderTopColor: "#f5e5ea", paddingTop: 8, marginTop: 7 },
  error: { color: "#a32121", marginTop: 4 },
  message: { color: "#a32121", marginTop: 12 },
  disabled: { opacity: 0.6 },
};
