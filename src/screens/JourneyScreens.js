import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  SafeAreaView,
  ScrollView,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import MapView, { Marker, Polyline } from "react-native-maps";
import * as Location from "expo-location";

import {
  connectJourneySocket,
  createJourney,
  endJourney,
  getJourney,
  getJourneyShares,
  getJourneys,
  getSharedJourney,
  getSharedJourneys,
  pauseJourney,
  resumeJourney,
  revokeAllJourneyShares,
  revokeJourneyShare,
  setJourneyTracking,
  shareJourney,
  startJourney,
  updateExpectedRoute,
} from "../services/api";
import { presentSafetyEventNotification } from "../services/safetyNotifications";

const DEEP_PINK = "#d47b8f";
const LIGHT_PINK = "#fff6f9";
const WHITE = "#fff";
const MODES = ["walking", "bus", "train", "metro", "cab"];
const MODE_DETAILS = {
  walking: { label: "Route notes (optional)", placeholder: "e.g. Parkside path" },
  bus: { label: "Bus route or operator", placeholder: "e.g. Route 24" },
  train: { label: "Train number or service", placeholder: "e.g. 12001" },
  metro: { label: "Metro line", placeholder: "e.g. Blue Line" },
  cab: { label: "Cab or operator", placeholder: "e.g. booked cab" },
};

const formatMode = (mode) => mode.charAt(0).toUpperCase() + mode.slice(1);
const formatDate = (value) => value ? new Date(value).toLocaleString() : "—";

function JourneyManagement({ navigation }) {
  const [journey, setJourney] = useState(null);
  const [mode, setMode] = useState("train");
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [transportDetail, setTransportDetail] = useState("");
  const [sharingEmail, setSharingEmail] = useState("");
  const [shares, setShares] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [tracking, setTracking] = useState(false);
  const [message, setMessage] = useState("");
  const trackerRef = useRef(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setMessage("");
    try {
      const journeys = await getJourneys();
      const current = journeys.find((item) => item.status !== "completed") || null;
      setJourney(current);
      setTracking(Boolean(trackerRef.current));
      if (current) {
        setShares(await getJourneyShares(current.id));
      } else {
        setShares([]);
      }
    } catch (error) {
      setMessage(error.message || "Couldn't load your journeys.");
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    React.useCallback(() => {
      refresh();
    }, [refresh])
  );

  useEffect(() => () => {
    const activeTracker = trackerRef.current;
    if (activeTracker) {
      activeTracker.subscription?.remove();
      activeTracker.socket.close();
      trackerRef.current = null;
    }
  }, []);

  const create = async () => {
    if (mode !== "walking" && !transportDetail.trim()) {
      setMessage(`Enter the ${MODE_DETAILS[mode].label.toLowerCase()}.`);
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const details = transportDetail.trim()
        ? { service: transportDetail.trim() }
        : {};
      const created = await createJourney({
        transport_mode: mode,
        origin: origin.trim() || null,
        destination: destination.trim() || null,
        transport_details: details,
      });
      setJourney(created);
      setShares([]);
      setOrigin("");
      setDestination("");
      setTransportDetail("");
    } catch (error) {
      setMessage(error.message || "Couldn't create this journey.");
    } finally {
      setBusy(false);
    }
  };

  const clearTracker = () => {
    const activeTracker = trackerRef.current;
    trackerRef.current = null;
    setTracking(false);
    if (activeTracker) {
      activeTracker.subscription?.remove();
      activeTracker.socket.close();
    }
  };

  const beginTracking = async (action) => {
    if (!journey) return;
    setBusy(true);
    setMessage("");
    let updatedJourney = null;
    let socket = null;
    let subscription = null;

    try {
      const permission = await Location.requestForegroundPermissionsAsync();
      if (permission.status !== "granted") {
        throw new Error("Location permission is needed to record this journey. You can continue without tracking.");
      }
      if (!await Location.hasServicesEnabledAsync()) {
        throw new Error("Turn on location services to track this journey.");
      }

      if (action === "start") updatedJourney = await startJourney(journey.id);
      else if (action === "resume") updatedJourney = await resumeJourney(journey.id);
      else updatedJourney = await setJourneyTracking(journey.id, true);
      setJourney(updatedJourney);

      socket = await connectJourneySocket(journey.id, {
        trackingConsent: true,
        onMessage: (event) => {
          if (event.type === "safety_event" && event.event) {
            setMessage("A safety prompt needs your confirmation. Open Check-ins & Safety Alerts.");
            presentSafetyEventNotification(event.event).catch((error) => {
              setMessage(error.message || "A safety prompt needs your confirmation.");
            });
            return;
          }
          if (event.type !== "location" || !event.location) return;
          setJourney((current) => {
            if (!current || current.id !== journey.id) return current;
            const locations = current.locations || [];
            if (locations[locations.length - 1]?.captured_at === event.location.captured_at) {
              return current;
            }
            return { ...current, locations: [...locations, event.location] };
          });
        },
        onDisconnect: () => {
          if (trackerRef.current?.socket === socket) {
            trackerRef.current.subscription?.remove();
            trackerRef.current = null;
            setTracking(false);
            setMessage("Live tracking disconnected. Reconnect to continue recording your route.");
          }
        },
      });
      trackerRef.current = { socket, subscription: null };

      subscription = await Location.watchPositionAsync(
        {
          accuracy: Location.Accuracy.Balanced,
          timeInterval: 5000,
          distanceInterval: 10,
        },
        (position) => {
          const sent = socket.sendLocation({
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            accuracy_m: position.coords.accuracy,
            captured_at: new Date(position.timestamp).toISOString(),
          });
          if (!sent) setMessage("Live connection lost. Reconnect to continue recording.");
        },
        (reason) => setMessage(`Location updates stopped: ${reason}`)
      );

      if (trackerRef.current?.socket !== socket) {
        subscription.remove();
        throw new Error("Live tracking disconnected before location updates could start.");
      }
      trackerRef.current.subscription = subscription;
      setTracking(true);
      setJourney((current) => current ? { ...current, location_recording_enabled: true } : current);
      setMessage("Location is being recorded while SheRail is open. It stays private unless you share it.");
    } catch (error) {
      subscription?.remove();
      socket?.close();
      if (trackerRef.current?.socket === socket) trackerRef.current = null;
      setTracking(false);
      if (updatedJourney) {
        try {
          const stopped = action === "tracking"
            ? await setJourneyTracking(journey.id, false)
            : await pauseJourney(journey.id);
          setJourney(stopped);
        } catch (stopError) {
          setJourney(updatedJourney);
          setMessage(
            `${error.message || "Couldn't start location tracking."} The journey may still be active. ${stopError.message || ""}`
          );
          setBusy(false);
          return;
        }
      }
      setMessage(error.message || "Couldn't start location tracking.");
    } finally {
      setBusy(false);
    }
  };

  const confirmTracking = (action) => {
    Alert.alert(
      "Record this journey's location?",
      "SheRail will request foreground location permission and save GPS points to this journey. Your location is not live-shared with anyone unless you separately share it with a SheRail account.",
      [
        { text: "Not now", style: "cancel" },
        { text: "Continue", onPress: () => beginTracking(action) },
      ]
    );
  };

  const pause = async () => {
    if (!journey) return;
    clearTracker();
    setBusy(true);
    setMessage("");
    try {
      setJourney(await pauseJourney(journey.id));
      setMessage("Journey paused. GPS recording and live updates have stopped.");
    } catch (error) {
      setMessage(error.message || "Couldn't pause the journey. Location updates were stopped on this device.");
    } finally {
      setBusy(false);
    }
  };

  const finish = async () => {
    if (!journey) return;
    const wasPlanned = journey.status === "planned";
    clearTracker();
    setBusy(true);
    setMessage("");
    try {
      setJourney(await endJourney(journey.id));
      setJourney(null);
      setShares([]);
      setMessage(wasPlanned
        ? "Planned journey cancelled."
        : "Journey ended. Live sharing has been revoked.");
    } catch (error) {
      setMessage(error.message || (wasPlanned
        ? "Couldn't cancel the planned journey."
        : "Couldn't end the journey. Location updates were stopped on this device."));
    } finally {
      setBusy(false);
    }
  };

  const addShare = () => {
    const email = sharingEmail.trim();
    if (!email || !journey) {
      setMessage("Enter the email address of a SheRail account.");
      return;
    }
    Alert.alert(
      "Share live location?",
      `This SheRail account will be able to view your live location during this journey: ${email}. You can revoke access at any time.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Share",
          onPress: async () => {
            setBusy(true);
            setMessage("");
            try {
              const share = await shareJourney(journey.id, email);
              setShares((current) => current.some((item) => item.recipient_user_id === share.recipient_user_id)
                ? current
                : [...current, share]);
              setSharingEmail("");
              setMessage("Live location is now shared with the selected account.");
            } catch (error) {
              setMessage(error.message || "Couldn't share this journey.");
            } finally {
              setBusy(false);
            }
          },
        },
      ]
    );
  };

  const removeShare = (recipientId) => {
    if (!journey) return;
    Alert.alert(
      "Revoke location access?",
      "This person will no longer be able to view this journey's live location.",
      [
        { text: "Keep access", style: "cancel" },
        {
          text: "Revoke",
          style: "destructive",
          onPress: async () => {
            try {
              await revokeJourneyShare(journey.id, recipientId);
              const remaining = shares.filter((item) => item.recipient_user_id !== recipientId);
              setShares(remaining);
              setJourney((current) => current
                ? { ...current, sharing_enabled: remaining.length > 0 }
                : current);
            } catch (error) {
              setMessage(error.message || "Couldn't revoke access.");
            }
          },
        },
      ]
    );
  };

  const stopSharing = () => {
    if (!journey) return;
    Alert.alert(
      "Stop live sharing?",
      "Everyone currently viewing this journey will lose access to live updates.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Stop sharing",
          style: "destructive",
          onPress: async () => {
            try {
              await revokeAllJourneyShares(journey.id);
              setShares([]);
              setJourney((current) => current ? { ...current, sharing_enabled: false } : current);
              setMessage("Live sharing has stopped.");
            } catch (error) {
              setMessage(error.message || "Couldn't stop live sharing.");
            }
          },
        },
      ]
    );
  };

  const modeDetail = MODE_DETAILS[mode];

  return (
    <SafeAreaView style={styles.root}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Text style={styles.title}>Journey Management</Text>
        <Text style={styles.hint}>Create a trip, choose a transport mode, then start tracking when you&apos;re ready.</Text>

        {loading ? <ActivityIndicator color={DEEP_PINK} /> : null}
        {!journey && !loading ? (
          <View style={styles.card}>
            <Text style={styles.sectionTitle}>New Journey</Text>
            <Text style={styles.label}>Transport mode *</Text>
            <View style={styles.modeRow}>
              {MODES.map((item) => (
                <TouchableOpacity
                  key={item}
                  style={[styles.modeChip, mode === item && styles.modeChipSelected]}
                  onPress={() => setMode(item)}
                >
                  <Text style={[styles.modeChipText, mode === item && styles.modeChipTextSelected]}>
                    {formatMode(item)}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            <Text style={styles.label}>From (optional)</Text>
            <TextInput
              style={styles.input}
              placeholder="Starting point"
              value={origin}
              onChangeText={setOrigin}
            />
            <Text style={styles.label}>To (optional)</Text>
            <TextInput
              style={styles.input}
              placeholder="Destination"
              value={destination}
              onChangeText={setDestination}
            />
            <Text style={styles.label}>{modeDetail.label}{mode === "walking" ? "" : " *"}</Text>
            <TextInput
              style={styles.input}
              placeholder={modeDetail.placeholder}
              value={transportDetail}
              onChangeText={setTransportDetail}
            />
            <TouchableOpacity
              style={[styles.button, busy && styles.disabled]}
              onPress={create}
              disabled={busy}
            >
              <Text style={styles.buttonText}>{busy ? "Creating..." : "Create Journey"}</Text>
            </TouchableOpacity>
          </View>
        ) : null}

        {journey ? (
          <View style={styles.card}>
            <Text style={styles.sectionTitle}>{formatMode(journey.transport_mode)} journey</Text>
            <Text style={styles.summary}>
              {journey.origin || "Starting point"} → {journey.destination || "Destination"}
            </Text>
            {Object.entries(journey.transport_details || {}).map(([key, value]) => (
              <Text key={key} style={styles.hint}>{key}: {value}</Text>
            ))}
            <Text style={styles.hint}>Status: {journey.status}</Text>
            <Text style={styles.hint}>Started: {formatDate(journey.started_at)}</Text>
            <Text style={styles.hint}>Ended: {formatDate(journey.ended_at)}</Text>

            {journey.status === "planned" ? (
              <TouchableOpacity
                style={[styles.button, busy && styles.disabled]}
                onPress={() => confirmTracking("start")}
                disabled={busy}
              >
                <Text style={styles.buttonText}>{busy ? "Starting..." : "Start Journey"}</Text>
              </TouchableOpacity>
            ) : null}
            {journey.status === "paused" ? (
              <TouchableOpacity
                style={[styles.button, busy && styles.disabled]}
                onPress={() => confirmTracking("resume")}
                disabled={busy}
              >
                <Text style={styles.buttonText}>{busy ? "Resuming..." : "Resume Journey"}</Text>
              </TouchableOpacity>
            ) : null}
            {journey.status === "active" ? (
              <>
                {!tracking ? (
                  <TouchableOpacity
                    style={[styles.button, busy && styles.disabled]}
                    onPress={() => confirmTracking("tracking")}
                    disabled={busy}
                  >
                    <Text style={styles.buttonText}>{busy ? "Connecting..." : "Resume GPS Updates"}</Text>
                  </TouchableOpacity>
                ) : (
                  <View style={styles.recordingBadge}>
                    <View style={styles.recordingDot} />
                    <Text style={styles.recordingText}>Recording GPS while app is open</Text>
                  </View>
                )}
                <TouchableOpacity
                  style={styles.secondaryButton}
                  onPress={pause}
                  disabled={busy}
                >
                  <Text style={styles.secondaryButtonText}>Pause Journey</Text>
                </TouchableOpacity>
              </>
            ) : null}
            {journey.status === "active" || journey.status === "paused" ? (
              <TouchableOpacity
                style={styles.secondaryButton}
                onPress={finish}
                disabled={busy}
              >
                <Text style={styles.secondaryButtonText}>End Journey</Text>
              </TouchableOpacity>
            ) : null}
            {journey.status === "planned" ? (
              <TouchableOpacity
                style={styles.secondaryButton}
                onPress={() => Alert.alert(
                  "Cancel planned journey?",
                  "This journey will be removed from your active journeys.",
                  [
                    { text: "Keep journey", style: "cancel" },
                    { text: "Cancel journey", style: "destructive", onPress: finish },
                  ]
                )}
                disabled={busy}
              >
                <Text style={styles.secondaryButtonText}>Cancel Planned Journey</Text>
              </TouchableOpacity>
            ) : null}

            <TouchableOpacity
              style={styles.secondaryButton}
              onPress={() => navigation.navigate("Map", { journeyId: journey.id })}
            >
              <Text style={styles.secondaryButtonText}>Open Journey Map</Text>
            </TouchableOpacity>

            {journey.status === "active" ? (
              <View style={styles.shareSection}>
                <Text style={styles.sectionTitle}>Share live location</Text>
                <Text style={styles.hint}>
                  Only registered SheRail accounts you choose can view live updates.
                </Text>
                <TextInput
                  style={styles.input}
                  placeholder="Recipient's SheRail email"
                  value={sharingEmail}
                  onChangeText={setSharingEmail}
                  keyboardType="email-address"
                  autoCapitalize="none"
                />
                <TouchableOpacity
                  style={styles.secondaryButton}
                  onPress={addShare}
                  disabled={!tracking || busy}
                >
                  <Text style={styles.secondaryButtonText}>
                    {tracking ? "Share with this account" : "Resume GPS updates to share"}
                  </Text>
                </TouchableOpacity>
                {shares.map((share) => (
                  <View style={styles.shareRow} key={share.id}>
                    <View style={styles.shareRecipient}>
                      <Text style={styles.summary}>{share.recipient_name}</Text>
                      <Text style={styles.hint}>{share.recipient_email}</Text>
                    </View>
                    <TouchableOpacity onPress={() => removeShare(share.recipient_user_id)}>
                      <Text style={styles.removeText}>Revoke</Text>
                    </TouchableOpacity>
                  </View>
                ))}
                {shares.length > 0 ? (
                  <TouchableOpacity style={styles.stopSharingButton} onPress={stopSharing}>
                    <Text style={styles.removeText}>Stop sharing with everyone</Text>
                  </TouchableOpacity>
                ) : null}
              </View>
            ) : null}
          </View>
        ) : null}

        {message ? <Text style={styles.message}>{message}</Text> : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function JourneyHistory({ navigation }) {
  const [journeys, setJourneys] = useState([]);
  const [shared, setShared] = useState([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");

  useFocusEffect(
    React.useCallback(() => {
      let active = true;
      setLoading(true);
      setMessage("");
      Promise.all([getJourneys(), getSharedJourneys()])
        .then(([own, received]) => {
          if (!active) return;
          setJourneys(own);
          setShared(received);
        })
        .catch((error) => {
          if (active) setMessage(error.message || "Couldn't load journey history.");
        })
        .finally(() => {
          if (active) setLoading(false);
        });
      return () => {
        active = false;
      };
    }, [])
  );

  const renderJourney = (journey, isShared = false) => (
    <TouchableOpacity
      style={styles.historyCard}
      key={`${isShared ? "shared" : "own"}-${journey.id}`}
      onPress={() => navigation.navigate("Map", {
        journeyId: journey.id,
        isShared,
      })}
    >
      <Text style={styles.sectionTitle}>
        {formatMode(journey.transport_mode)} · {journey.status}
      </Text>
      <Text style={styles.summary}>
        {journey.origin || "Starting point"} → {journey.destination || "Destination"}
      </Text>
      {journey.owner_name ? <Text style={styles.hint}>Shared by {journey.owner_name}</Text> : null}
      {Object.entries(journey.transport_details || {}).map(([key, value]) => (
        <Text style={styles.hint} key={key}>{key}: {value}</Text>
      ))}
      <Text style={styles.hint}>Created: {formatDate(journey.created_at)}</Text>
      <Text style={styles.hint}>Started: {formatDate(journey.started_at)}</Text>
      <Text style={styles.hint}>Paused: {formatDate(journey.paused_at)}</Text>
      <Text style={styles.hint}>Ended: {formatDate(journey.ended_at)}</Text>
      <Text style={styles.historyAction}>View route</Text>
    </TouchableOpacity>
  );

  return (
    <SafeAreaView style={styles.root}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Journey History</Text>
        {loading ? <ActivityIndicator color={DEEP_PINK} /> : null}
        <Text style={styles.sectionTitle}>My Journeys</Text>
        {!loading && journeys.length === 0 ? (
          <Text style={styles.hint}>Your completed and active journeys will appear here.</Text>
        ) : journeys.map((journey) => renderJourney(journey))}

        <Text style={styles.sectionTitle}>Shared with Me</Text>
        {!loading && shared.length === 0 ? (
          <Text style={styles.hint}>No one is sharing an active journey with you.</Text>
        ) : shared.map((journey) => renderJourney(journey, true))}
        {message ? <Text style={styles.message}>{message}</Text> : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function JourneyMap({ navigation, route }) {
  const { journeyId, isShared = false, routeEdit = false } = route.params || {};
  const [journey, setJourney] = useState(null);
  const [expectedRoute, setExpectedRoute] = useState([]);
  const [savingRoute, setSavingRoute] = useState(false);
  const [region, setRegion] = useState({
    latitude: 12.9716,
    longitude: 77.5946,
    latitudeDelta: 0.05,
    longitudeDelta: 0.05,
  });
  const [message, setMessage] = useState("");
  const [live, setLive] = useState(false);

  useFocusEffect(
    React.useCallback(() => {
      let active = true;
      let socketSession = null;
      setMessage("");
      setLive(false);
      setJourney(null);
      setExpectedRoute([]);
      setRegion({
        latitude: 12.9716,
        longitude: 77.5946,
        latitudeDelta: 0.05,
        longitudeDelta: 0.05,
      });

      const updateFromLocation = (location) => {
        setJourney((current) => {
          if (!current) return current;
          const locations = current.locations || [];
          if (locations[locations.length - 1]?.captured_at === location.captured_at) {
            return current;
          }
          return { ...current, locations: [...locations, location] };
        });
        setRegion((current) => ({
          ...current,
          latitude: location.latitude,
          longitude: location.longitude,
        }));
      };

      const clearSharedLocation = () => {
        setJourney((current) => current ? { ...current, locations: [] } : current);
        setRegion({
          latitude: 12.9716,
          longitude: 77.5946,
          latitudeDelta: 0.05,
          longitudeDelta: 0.05,
        });
      };

      const loadJourneyMap = async () => {
        if (!journeyId) {
          const permission = await Location.requestForegroundPermissionsAsync();
          if (permission.status !== "granted") {
            if (active) {
              setMessage("Location permission was not granted. The map is centered on its default view.");
            }
            return;
          }
          const location = await Location.getCurrentPositionAsync({});
          if (active) {
            setRegion({
              latitude: location.coords.latitude,
              longitude: location.coords.longitude,
              latitudeDelta: 0.01,
              longitudeDelta: 0.01,
            });
          }
          return;
        }

        if (routeEdit) {
          const permission = await Location.requestForegroundPermissionsAsync();
          if (permission.status === "granted") {
            const location = await Location.getCurrentPositionAsync({});
            if (active) {
              setRegion((current) => ({
                ...current,
                latitude: location.coords.latitude,
                longitude: location.coords.longitude,
                latitudeDelta: 0.02,
                longitudeDelta: 0.02,
              }));
            }
          }
        }

        const detail = isShared
          ? await getSharedJourney(journeyId)
          : await getJourney(journeyId);
        if (!active) return;
        const initialPoint = isShared
          ? detail.latest_location
          : detail.locations?.[detail.locations.length - 1];
        setJourney(isShared
          ? { ...detail, locations: detail.latest_location ? [detail.latest_location] : [] }
          : detail);
        setExpectedRoute(detail.expected_route || []);
        const routeCenter = routeEdit && detail.expected_route?.length
          ? detail.expected_route[0]
          : initialPoint;
        if (routeCenter) {
          setRegion((current) => ({
            ...current,
            latitude: routeCenter.latitude,
            longitude: routeCenter.longitude,
            latitudeDelta: 0.01,
            longitudeDelta: 0.01,
          }));
        }

        if (detail.status === "active" && !routeEdit) {
          socketSession = await connectJourneySocket(journeyId, {
            onMessage: (event) => {
              if (!active) return;
              if (event.type === "location" && event.location) {
                updateFromLocation(event.location);
                setLive(true);
              }
              if (event.type === "safety_event" && event.event) {
                setMessage("A safety prompt needs your confirmation in Check-ins & Safety Alerts.");
                presentSafetyEventNotification(event.event).catch((error) => {
                  setMessage(error.message || "A safety prompt needs your confirmation.");
                });
              }
              if (event.type === "safety_buddy_alert" && event.alert) {
                Alert.alert(
                  "Safety Buddy alert",
                  event.alert.description || "A shared journey needs your attention."
                );
              }
              if (event.type === "tracking_paused") {
                setLive(false);
                setMessage("Location updates are paused.");
              }
              if (event.type === "tracking_resumed") {
                setLive(true);
                setMessage("");
              }
              if (event.type === "journey_ended") {
                setLive(false);
                setMessage("This journey has ended.");
                if (isShared) clearSharedLocation();
              }
              if (event.type === "sharing_stopped") {
                setLive(false);
                setMessage("The journey owner stopped sharing this location.");
                clearSharedLocation();
              }
            },
            onDisconnect: () => {
              if (active) setLive(false);
            },
          });
          if (active) setLive(true);
          else socketSession.close();
        }
      };

      loadJourneyMap().catch((error) => {
        if (active) setMessage(error.message || "Couldn't load this map.");
      });

      return () => {
        active = false;
        socketSession?.close();
      };
    }, [journeyId, isShared, routeEdit])
  );

  const saveRoute = async () => {
    if (!journey) return;
    if (expectedRoute.length === 1) {
      setMessage("Add a second waypoint, or clear the route before saving.");
      return;
    }
    setSavingRoute(true);
    setMessage("");
    try {
      const updated = await updateExpectedRoute(journey.id, expectedRoute);
      setJourney(updated);
      setExpectedRoute(updated.expected_route || []);
      setMessage("Private expected route saved.");
      navigation.goBack();
    } catch (error) {
      setMessage(error.message || "Couldn't save the expected route.");
    } finally {
      setSavingRoute(false);
    }
  };

  const points = journey?.locations || [];
  const coordinates = points.map((point) => ({
    latitude: point.latitude,
    longitude: point.longitude,
  }));
  const latest = points[points.length - 1];
  const expectedCoordinates = expectedRoute.map((point) => ({
    latitude: point.latitude,
    longitude: point.longitude,
  }));

  return (
    <SafeAreaView style={styles.mapRoot}>
      {routeEdit ? (
        <View style={styles.mapHeader}>
          <Text style={styles.sectionTitle}>Private expected route</Text>
          <Text style={styles.hint}>Tap the map to add route waypoints. The route is stored on your account and used only for deviation checks.</Text>
          <Text style={styles.hint}>{expectedRoute.length} waypoint(s)</Text>
          <View style={styles.mapActions}>
            <TouchableOpacity
              style={styles.mapAction}
              onPress={() => setExpectedRoute([])}
              disabled={savingRoute}
            >
              <Text style={styles.mapActionText}>Clear</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.mapAction, savingRoute && styles.disabled]}
              onPress={saveRoute}
              disabled={savingRoute || expectedRoute.length === 1}
            >
              <Text style={styles.mapActionText}>{savingRoute ? "Saving..." : "Save route"}</Text>
            </TouchableOpacity>
          </View>
        </View>
      ) : null}
      {journey ? (
        <View style={routeEdit ? styles.mapSubHeader : styles.mapHeader}>
          <Text style={styles.sectionTitle}>
            {formatMode(journey.transport_mode)} journey
          </Text>
          <Text style={styles.hint}>
            {journey.origin || "Starting point"} → {journey.destination || "Destination"}
          </Text>
          {Object.entries(journey.transport_details || {}).map(([key, value]) => (
            <Text style={styles.hint} key={key}>{key}: {value}</Text>
          ))}
          <Text style={styles.hint}>Started: {formatDate(journey.started_at)}</Text>
          <Text style={styles.hint}>Ended: {formatDate(journey.ended_at)}</Text>
          <Text style={styles.hint}>
            {isShared ? `Shared by ${journey.owner_name || "a SheRail user"}` : `Status: ${journey.status}`}
            {live ? " · Live" : ""}
          </Text>
          {latest ? <Text style={styles.hint}>Last location: {formatDate(latest.captured_at)}</Text> : null}
        </View>
      ) : null}
      {message ? <Text style={styles.message}>{message}</Text> : null}
      <MapView
        style={styles.map}
        region={region}
        onRegionChangeComplete={setRegion}
        onPress={routeEdit
          ? (event) => {
            if (expectedRoute.length >= 100) {
              setMessage("A route can include up to 100 waypoints.");
              return;
            }
            const { latitude, longitude } = event.nativeEvent.coordinate;
            setExpectedRoute((current) => [...current, { latitude, longitude }]);
          }
          : undefined}
      >
        {expectedCoordinates.length > 1 ? (
          <Polyline coordinates={expectedCoordinates} strokeColor="#4378bd" strokeWidth={4} />
        ) : null}
        {routeEdit ? expectedCoordinates.map((coordinate, index) => (
          <Marker
            key={`expected-${index}`}
            coordinate={coordinate}
            title={`Waypoint ${index + 1}`}
            pinColor="#4378bd"
          />
        )) : null}
        {coordinates.length > 1 ? (
          <Polyline coordinates={coordinates} strokeColor={DEEP_PINK} strokeWidth={4} />
        ) : null}
        {latest ? (
          <Marker
            coordinate={{ latitude: latest.latitude, longitude: latest.longitude }}
            title={isShared ? "Shared live location" : "Journey location"}
          />
        ) : (
          <Marker coordinate={{ latitude: region.latitude, longitude: region.longitude }} />
        )}
      </MapView>
      {points.length > 0 ? (
        <ScrollView style={styles.locationTimeline}>
          {points.slice(-20).reverse().map((point) => (
            <Text style={styles.hint} key={point.id || point.captured_at}>
              Location recorded: {formatDate(point.captured_at)}
            </Text>
          ))}
        </ScrollView>
      ) : null}
    </SafeAreaView>
  );
}

const styles = {
  root: { flex: 1, backgroundColor: LIGHT_PINK },
  content: { padding: 16, paddingBottom: 28 },
  title: { color: DEEP_PINK, fontSize: 22, fontWeight: "800", marginBottom: 8 },
  sectionTitle: { color: "#222", fontSize: 17, fontWeight: "800", marginBottom: 8 },
  summary: { color: "#333", fontWeight: "700" },
  hint: { color: "#555", marginTop: 5 },
  label: { color: "#333", fontWeight: "700", marginBottom: 6 },
  input: {
    backgroundColor: WHITE,
    borderWidth: 1,
    borderColor: "#f0d7df",
    borderRadius: 10,
    padding: 12,
    marginBottom: 12,
  },
  card: { backgroundColor: WHITE, padding: 16, borderRadius: 12, marginTop: 14 },
  modeRow: { flexDirection: "row", flexWrap: "wrap", marginBottom: 10 },
  modeChip: {
    borderColor: DEEP_PINK,
    borderWidth: 1,
    borderRadius: 18,
    paddingVertical: 8,
    paddingHorizontal: 12,
    marginRight: 8,
    marginBottom: 8,
  },
  modeChipSelected: { backgroundColor: DEEP_PINK },
  modeChipText: { color: DEEP_PINK, fontWeight: "700" },
  modeChipTextSelected: { color: WHITE },
  button: {
    backgroundColor: DEEP_PINK,
    padding: 14,
    borderRadius: 10,
    alignItems: "center",
    marginTop: 8,
  },
  buttonText: { color: WHITE, fontWeight: "800" },
  disabled: { opacity: 0.6 },
  secondaryButton: {
    borderColor: DEEP_PINK,
    borderWidth: 1,
    borderRadius: 10,
    padding: 12,
    alignItems: "center",
    marginTop: 10,
  },
  secondaryButtonText: { color: DEEP_PINK, fontWeight: "700" },
  recordingBadge: { flexDirection: "row", alignItems: "center", marginTop: 14 },
  recordingDot: { width: 9, height: 9, borderRadius: 5, backgroundColor: "#bd3434", marginRight: 8 },
  recordingText: { color: "#444", fontWeight: "700" },
  shareSection: { borderTopWidth: 1, borderTopColor: "#f0d7df", marginTop: 20, paddingTop: 16 },
  shareRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    borderTopWidth: 1,
    borderTopColor: "#f5e5ea",
    paddingVertical: 12,
  },
  shareRecipient: { flex: 1 },
  removeText: { color: "#a32121", fontWeight: "700" },
  stopSharingButton: { alignItems: "center", padding: 12 },
  message: { color: "#a32121", marginTop: 12, marginBottom: 8 },
  historyCard: { backgroundColor: WHITE, padding: 14, borderRadius: 10, marginTop: 10 },
  historyAction: { color: DEEP_PINK, fontWeight: "800", marginTop: 10 },
  mapRoot: { flex: 1, backgroundColor: LIGHT_PINK },
  mapHeader: { padding: 12, backgroundColor: WHITE },
  mapSubHeader: { paddingHorizontal: 12, paddingTop: 5, backgroundColor: WHITE },
  mapActions: { flexDirection: "row", justifyContent: "space-between" },
  mapAction: {
    borderColor: DEEP_PINK,
    borderWidth: 1,
    borderRadius: 9,
    paddingVertical: 9,
    paddingHorizontal: 18,
    marginVertical: 7,
  },
  mapActionText: { color: DEEP_PINK, fontWeight: "700" },
  map: { flex: 1 },
  locationTimeline: { maxHeight: 112, paddingHorizontal: 12, backgroundColor: WHITE },
};

export { JourneyHistory, JourneyManagement, JourneyMap };
