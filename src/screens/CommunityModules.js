import React, { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Linking,
  Platform,
  SafeAreaView,
  ScrollView,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import Constants from "expo-constants";
import * as Notifications from "expo-notifications";
import { AndroidImportance, IosAuthorizationStatus } from "expo-notifications";

import {
  getNotifications,
  getPushDeviceStatus,
  getRailwayAssistance,
  markAllNotificationsRead,
  markNotificationRead,
  registerPushDevice,
  unregisterPushDevices,
} from "../services/api";

const DEEP_PINK = "#d47b8f";
const LIGHT_PINK = "#fff6f9";

async function openNotificationTarget(item, navigation) {
  if (item.kind === "safety_buddy_alert") {
    navigation.navigate("SafetyBuddy");
  } else if (item.kind === "community_report_status") {
    navigation.navigate("SafetyMap", { reportMode: true });
  } else if (item.kind === "admin_sos_alert" || item.kind === "community_report_new") {
    const adminUrl = process.env.EXPO_PUBLIC_ADMIN_URL;
    if (!adminUrl || !adminUrl.startsWith("https://")) {
      throw new Error("A secure SheRail admin dashboard URL is not configured in this app.");
    }
    await Linking.openURL(adminUrl);
  } else {
    navigation.navigate("SafetyDashboard");
  }
}

export function NotificationsScreen({ navigation }) {
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [pushEnabled, setPushEnabled] = useState(false);
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [inboxResult, deviceResult] = await Promise.allSettled([
        getNotifications(),
        getPushDeviceStatus(),
      ]);
      if (inboxResult.status === "rejected") throw inboxResult.reason;
      setNotifications(inboxResult.value);
      if (deviceResult.status === "fulfilled") {
        setPushEnabled(deviceResult.value.enabled);
        setMessage("");
      } else {
        setMessage(deviceResult.reason.message || "Couldn't load push-device status.");
      }
    } catch (error) {
      setMessage(error.message || "Couldn't load your notifications.");
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      refresh();
    }, [refresh])
  );

  const enablePush = async () => {
    if (Platform.OS === "web") {
      setMessage("Push notifications are available in the iOS and Android SheRail apps.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      if (Platform.OS === "android") {
        await Notifications.setNotificationChannelAsync("sherail-safety", {
          name: "SheRail safety alerts",
          importance: AndroidImportance.HIGH,
          vibrationPattern: [0, 250, 250, 250],
          lightColor: DEEP_PINK,
        });
      }
      const current = await Notifications.getPermissionsAsync();
      const permission = current.granted
        || current.ios?.status === IosAuthorizationStatus.PROVISIONAL
        ? current
        : await Notifications.requestPermissionsAsync();
      if (
        !permission.granted
        && permission.ios?.status !== IosAuthorizationStatus.PROVISIONAL
      ) {
        throw new Error("Notification permission was not granted.");
      }
      const projectId = Constants.expoConfig?.extra?.eas?.projectId
        || Constants.easConfig?.projectId;
      if (!projectId) {
        throw new Error("The Expo project ID is missing from this app configuration.");
      }
      const token = await Notifications.getExpoPushTokenAsync({ projectId });
      await registerPushDevice(token.data, Platform.OS);
      setPushEnabled(true);
      setMessage("Push alerts are enabled for this device.");
    } catch (error) {
      setMessage(error.message || "Couldn't enable push alerts.");
    } finally {
      setBusy(false);
    }
  };

  const disablePush = async () => {
    setBusy(true);
    setMessage("");
    try {
      await unregisterPushDevices();
      setPushEnabled(false);
      setMessage("Push alerts were disabled for your account.");
    } catch (error) {
      setMessage(error.message || "Couldn't disable push alerts.");
    } finally {
      setBusy(false);
    }
  };

  const markRead = async (item) => {
    try {
      if (!item.read_at) {
        const updated = await markNotificationRead(item.id);
        setNotifications((current) => current.map((entry) => (
          entry.id === updated.id ? updated : entry
        )));
      }
      await openNotificationTarget(item, navigation);
    } catch (error) {
      setMessage(error.message || "Couldn't mark this notification as read.");
    }
  };

  const markAllRead = async () => {
    setBusy(true);
    try {
      await markAllNotificationsRead();
      await refresh();
    } catch (error) {
      setMessage(error.message || "Couldn't mark notifications as read.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.root}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Notifications</Text>
        <Text style={styles.body}>
          Your SheRail alerts are stored in your account. Push delivery requires notification permission and a configured Expo push service.
        </Text>
        <View style={styles.actions}>
          <TouchableOpacity style={styles.button} onPress={pushEnabled ? disablePush : enablePush} disabled={busy}>
            <Text style={styles.buttonText}>
              {busy ? "Updating..." : pushEnabled ? "Disable push alerts" : "Enable push alerts"}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.secondaryButton} onPress={markAllRead} disabled={busy}>
            <Text style={styles.secondaryText}>Mark all read</Text>
          </TouchableOpacity>
        </View>
        {loading ? <ActivityIndicator color={DEEP_PINK} /> : null}
        {!loading && notifications.length === 0 ? (
          <Text style={styles.muted}>No notifications have been recorded yet.</Text>
        ) : notifications.map((item) => (
          <TouchableOpacity
            key={item.id}
            style={[styles.card, !item.read_at && styles.unread]}
            onPress={() => markRead(item)}
          >
            <Text style={styles.heading}>{item.title}</Text>
            <Text style={styles.body}>{item.body}</Text>
            <Text style={styles.muted}>{new Date(item.created_at).toLocaleString()}</Text>
            <Text style={styles.status}>
              {item.push_status === "accepted"
                ? "Accepted by Expo; waiting for the push-provider receipt"
                : item.push_status === "receipt_ok"
                  ? "Accepted by APNs/FCM (device delivery is not guaranteed)"
                : item.push_status === "no_device"
                  ? "Saved to inbox; no push-enabled device"
                  : item.push_status === "failed"
                    ? "Saved to inbox; push delivery failed"
                    : item.push_status === "unknown"
                      ? "Saved to inbox; push delivery could not be confirmed"
                    : item.push_status === "pending" || item.push_status === "processing"
                      ? "Saved to inbox; push queued"
                      : "Saved to inbox"}
            </Text>
            {!item.read_at ? <Text style={styles.action}>Open alert</Text> : null}
          </TouchableOpacity>
        ))}
        {message ? <Text style={styles.message}>{message}</Text> : null}
      </ScrollView>
    </SafeAreaView>
  );
}

export function RailwayAssistanceScreen() {
  const [items, setItems] = useState([]);
  const [station, setStation] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");

  const search = useCallback(async (value = "") => {
    setLoading(true);
    setMessage("");
    try {
      setItems(await getRailwayAssistance(value));
    } catch (error) {
      setItems([]);
      setMessage(error.message || "Railway assistance information is unavailable.");
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      search();
    }, [search])
  );

  const openContact = async (item) => {
    const url = item.contact_url || (item.phone ? `tel:${item.phone}` : null);
    if (!url) return;
    try {
      await Linking.openURL(url);
    } catch (error) {
      setMessage(error.message || "Could not open this assistance contact.");
    }
  };

  return (
    <SafeAreaView style={styles.root}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Railway Assistance</Text>
        <Text style={styles.body}>
          This optional directory contains railway assistance details configured by SheRail administrators. Other transport and safety features work independently.
        </Text>
        <TextInput
          style={styles.input}
          accessibilityLabel="Railway station search"
          placeholder="Filter by station (optional)"
          value={station}
          onChangeText={setStation}
          onSubmitEditing={() => {
            setQuery(station.trim());
            search(station);
          }}
          returnKeyType="search"
        />
        <TouchableOpacity
          style={styles.button}
          onPress={() => {
            setQuery(station.trim());
            search(station);
          }}
        >
          <Text style={styles.buttonText}>Search assistance</Text>
        </TouchableOpacity>
        {query ? <Text style={styles.muted}>Showing published records for “{query}”.</Text> : null}
        {loading ? <ActivityIndicator color={DEEP_PINK} /> : null}
        {!loading && items.length === 0 ? (
          <Text style={styles.muted}>
            {message ? "No railway assistance records could be loaded." : "No railway assistance records have been published."}
          </Text>
        ) : items.map((item) => (
          <View style={styles.card} key={item.id}>
            <Text style={styles.heading}>{item.title}</Text>
            <Text style={styles.body}>{item.description}</Text>
            {item.station_name ? <Text style={styles.muted}>Station: {item.station_name}</Text> : null}
            {item.availability ? <Text style={styles.muted}>Availability: {item.availability}</Text> : null}
            {item.phone ? <Text style={styles.muted}>Contact: {item.phone}</Text> : null}
            {item.contact_url || item.phone ? (
              <TouchableOpacity onPress={() => openContact(item)}>
                <Text style={styles.action}>{item.contact_url ? "Open assistance details" : "Call assistance contact"}</Text>
              </TouchableOpacity>
            ) : null}
          </View>
        ))}
        {message ? <Text style={styles.message}>{message}</Text> : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = {
  root: { flex: 1, backgroundColor: LIGHT_PINK },
  content: { padding: 16, paddingBottom: 36 },
  title: { color: DEEP_PINK, fontSize: 23, fontWeight: "800", marginBottom: 8 },
  heading: { color: "#222", fontSize: 16, fontWeight: "800", marginBottom: 6 },
  body: { color: "#333", lineHeight: 21, marginBottom: 8 },
  muted: { color: "#555", lineHeight: 19, marginBottom: 7 },
  card: { backgroundColor: "#fff", padding: 14, borderRadius: 12, marginTop: 10 },
  unread: { borderWidth: 1, borderColor: DEEP_PINK },
  actions: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 8 },
  button: {
    backgroundColor: DEEP_PINK,
    padding: 12,
    borderRadius: 10,
    alignItems: "center",
    marginTop: 8,
    minHeight: 44,
    justifyContent: "center",
  },
  buttonText: { color: "#fff", fontWeight: "800" },
  secondaryButton: {
    backgroundColor: "#fff",
    padding: 12,
    borderRadius: 10,
    alignItems: "center",
    marginTop: 8,
    minHeight: 44,
    justifyContent: "center",
    borderColor: DEEP_PINK,
    borderWidth: 1,
  },
  secondaryText: { color: DEEP_PINK, fontWeight: "800" },
  input: {
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#f0d7df",
    borderRadius: 10,
    padding: 12,
    marginTop: 8,
    marginBottom: 8,
  },
  action: { color: DEEP_PINK, fontWeight: "800", marginTop: 8 },
  status: { color: "#555", fontSize: 12, marginTop: 4 },
  message: { color: "#a32121", marginTop: 12, lineHeight: 20 },
};
