import React, { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Image,
  Linking,
  SafeAreaView,
  ScrollView,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import MapView, { Marker } from "react-native-maps";
import * as Location from "expo-location";
import * as ImagePicker from "expo-image-picker";

import {
  getJourneyShares,
  getJourneys,
  getAuthenticatedImageSource,
  getMyCommunityReports,
  getNearbyHelp,
  getNearbyAssistancePoints,
  getPendingSafetyMapReports,
  getSafetyBuddyAlerts,
  getSafetyBuddyOverview,
  getSafetyMapModeratorAccess,
  getSharedJourneys,
  getVerifiedCommunityReports,
  submitCommunitySafetyReportWithImages,
  inviteSafetyBuddy,
  markSafetyBuddyAlertRead,
  removeSafetyBuddy,
  respondToSafetyBuddyInvitation,
  reviewCommunitySafetyReport,
  revokeSafetyBuddyJourneyShare,
  shareJourneyWithSafetyBuddy,
  submitCommunitySafetyReport,
} from "../services/api";

const DEEP_PINK = "#d47b8f";
const LIGHT_PINK = "#fff6f9";
const WHITE = "#fff";
const REPORT_TYPES = [
  ["harassment", "Harassment"],
  ["theft", "Theft"],
  ["unsafe_area", "Unsafe area"],
  ["poor_lighting", "Poor lighting"],
  ["other", "Other"],
];
const MAP_FILTERS = [
  ["all", "All"],
  ["police", "Police"],
  ["hospital", "Hospitals & clinics"],
  ["assistance", "Assistance"],
  ["reports", "Reports"],
];

const formatDate = (value) => value ? new Date(value).toLocaleString() : "—";

function ActionButton({ label, onPress, secondary = false, disabled = false }) {
  return (
    <TouchableOpacity
      style={[
        styles.button,
        secondary && styles.secondaryButton,
        disabled && styles.disabled,
      ]}
      onPress={onPress}
      disabled={disabled}
    >
      <Text style={[styles.buttonText, secondary && styles.secondaryButtonText]}>{label}</Text>
    </TouchableOpacity>
  );
}

export function SafetyBuddyScreen({ navigation }) {
  const [overview, setOverview] = useState({ sent: [], received: [], accepted: [] });
  const [alerts, setAlerts] = useState([]);
  const [journeyAccess, setJourneyAccess] = useState([]);
  const [sharedJourneys, setSharedJourneys] = useState([]);
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const refresh = useCallback(async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    try {
      const [buddyOverview, buddyAlerts, journeys, receivedJourneys] = await Promise.all([
        getSafetyBuddyOverview(),
        getSafetyBuddyAlerts(),
        getJourneys(),
        getSharedJourneys(),
      ]);
      const manageableJourneys = journeys.filter(
        (item) => item.status === "active" || (item.status === "paused" && item.sharing_enabled)
      );
      const journeyShares = await Promise.all(
        manageableJourneys.map(async (item) => ({
          journey: item,
          shares: await getJourneyShares(item.id),
        }))
      );
      setOverview(buddyOverview);
      setAlerts(buddyAlerts);
      setJourneyAccess(journeyShares);
      setSharedJourneys(receivedJourneys);
      return receivedJourneys;
    } catch (error) {
      setMessage(error.message || "Couldn't load Safety Buddy information.");
      return [];
    } finally {
      if (showSpinner) setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      refresh(true);
      const timer = setInterval(() => {
        if (active) refresh(false);
      }, 20000);
      return () => {
        active = false;
        clearInterval(timer);
      };
    }, [refresh])
  );

  const invite = async () => {
    if (!email.trim()) {
      setMessage("Enter the email address of an existing SheRail account.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      await inviteSafetyBuddy(email.trim());
      setEmail("");
      setMessage("Invitation sent. The other person must accept it before you can share a journey.");
      await refresh();
    } catch (error) {
      setMessage(error.message || "Couldn't send the Safety Buddy invitation.");
    } finally {
      setBusy(false);
    }
  };

  const cancelInvitation = (invitation) => {
    const isPending = invitation.status === "pending";
    Alert.alert(
      isPending ? "Cancel invitation?" : "Remove declined invitation?",
      isPending
        ? `Cancel the pending Safety Buddy invitation to ${invitation.peer_name}?`
        : `Remove the declined invitation from ${invitation.peer_name}?`,
      [
        { text: "Keep invitation", style: "cancel" },
        {
          text: isPending ? "Cancel invitation" : "Remove",
          style: "destructive",
          onPress: async () => {
            setBusy(true);
            try {
              await removeSafetyBuddy(invitation.id);
              await refresh();
              setMessage("Safety Buddy invitation cancelled.");
            } catch (error) {
              setMessage(error.message || "Couldn't cancel the invitation.");
            } finally {
              setBusy(false);
            }
          },
        },
      ]
    );
  };

  const respond = async (invitation, accept) => {
    setBusy(true);
    setMessage("");
    try {
      await respondToSafetyBuddyInvitation(invitation.id, accept);
      setMessage(accept
        ? "Safety Buddy invitation accepted. Journey sharing still requires separate consent."
        : "Safety Buddy invitation declined.");
      await refresh();
    } catch (error) {
      setMessage(error.message || "Couldn't respond to this invitation.");
    } finally {
      setBusy(false);
    }
  };

  const updateShare = (buddy, isShared, journey) => {
    const title = isShared ? "Stop sharing this journey?" : "Share this live journey?";
    const description = isShared
      ? `${buddy.peer_name} will lose access to this journey's live location and future safety alerts.`
      : `This shares your live GPS location and journey safety alerts with ${buddy.peer_name}. You can revoke access at any time.`;
    Alert.alert(title, description, [
      { text: "Cancel", style: "cancel" },
      {
        text: isShared ? "Stop sharing" : "Share journey",
        style: isShared ? "destructive" : "default",
        onPress: async () => {
          setBusy(true);
          setMessage("");
          try {
            if (isShared) {
              await revokeSafetyBuddyJourneyShare(journey.id, buddy.peer_user_id);
            } else {
              await shareJourneyWithSafetyBuddy(journey.id, buddy.peer_user_id);
            }
            await refresh();
            setMessage(isShared
              ? "Journey access revoked."
              : "Journey location is now shared with your Safety Buddy.");
          } catch (error) {
            setMessage(error.message || "Couldn't update journey sharing.");
          } finally {
            setBusy(false);
          }
        },
      },
    ]);
  };

  const unlink = (buddy) => {
    Alert.alert(
      "Remove this Safety Buddy?",
      `This removes the trusted connection and revokes journey access between you and ${buddy.peer_name}.`,
      [
        { text: "Keep connection", style: "cancel" },
        {
          text: "Remove",
          style: "destructive",
          onPress: async () => {
            setBusy(true);
            try {
              await removeSafetyBuddy(buddy.id);
              await refresh();
              setMessage("Safety Buddy connection removed and live access revoked.");
            } catch (error) {
              setMessage(error.message || "Couldn't remove this Safety Buddy.");
            } finally {
              setBusy(false);
            }
          },
        },
      ]
    );
  };

  const markRead = async (alert) => {
    try {
      const updated = await markSafetyBuddyAlertRead(alert.id);
      setAlerts((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (error) {
      setMessage(error.message || "Couldn't mark this alert as read.");
    }
  };

  return (
    <SafeAreaView style={styles.root}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Text style={styles.title}>Safety Buddy</Text>
        <Text style={styles.body}>
          Invitations connect existing SheRail accounts. Accepting an invitation does not share location; each journey needs your separate approval.
        </Text>
        <Text style={styles.muted}>
          Open a shared journey&apos;s map for live WebSocket updates. Alerts are saved here and refreshed automatically.
        </Text>

        {loading ? <ActivityIndicator color={DEEP_PINK} /> : null}
        <View style={styles.card}>
          <Text style={styles.heading}>Invite someone you trust</Text>
          <TextInput
            style={styles.input}
            accessibilityLabel="Safety Buddy email address"
            placeholder="Their SheRail account email"
            value={email}
            onChangeText={setEmail}
            keyboardType="email-address"
            autoCapitalize="none"
            autoComplete="email"
          />
          <ActionButton label={busy ? "Sending..." : "Send invitation"} onPress={invite} disabled={busy} />
        </View>

        {overview.received.length > 0 ? (
          <View style={styles.section}>
            <Text style={styles.heading}>Invitations for you</Text>
            {overview.received.map((item) => (
              <View style={styles.card} key={item.id}>
                <Text style={styles.heading}>{item.peer_name}</Text>
                <Text style={styles.muted}>{item.peer_email}</Text>
                <View style={styles.row}>
                  <ActionButton label="Accept" onPress={() => respond(item, true)} disabled={busy} />
                  <ActionButton label="Decline" secondary onPress={() => respond(item, false)} disabled={busy} />
                </View>
              </View>
            ))}
          </View>
        ) : null}

        {overview.sent.length > 0 ? (
          <View style={styles.section}>
            <Text style={styles.heading}>Invitations you sent</Text>
            {overview.sent.map((item) => (
              <View style={styles.shareRow} key={item.id}>
                <Text style={[styles.muted, styles.flex]}>{item.peer_name} · {item.status}</Text>
                <TouchableOpacity onPress={() => cancelInvitation(item)} disabled={busy}>
                  <Text style={styles.dangerText}>
                    {item.status === "pending" ? "Cancel" : "Remove"}
                  </Text>
                </TouchableOpacity>
              </View>
            ))}
          </View>
        ) : null}

        <View style={styles.section}>
          <Text style={styles.heading}>Your journey sharing</Text>
          {journeyAccess.length > 0 ? (
            journeyAccess.map(({ journey: sharedJourney, shares: journeyShares }) => {
              const sharedBuddyIds = new Set(journeyShares.map((share) => share.recipient_user_id));
              const canGrantShare = sharedJourney.status === "active"
                && sharedJourney.location_recording_enabled;
              return (
                <View style={styles.card} key={sharedJourney.id}>
                  <Text style={styles.heading}>
                    {sharedJourney.transport_mode} · {sharedJourney.origin || "Starting point"} → {sharedJourney.destination || "Destination"}
                  </Text>
                  <Text style={styles.muted}>
                    {canGrantShare
                      ? "GPS recording is active. Share only with people you trust."
                      : "This journey is paused. Existing access can be revoked, but location is not being recorded."}
                  </Text>
                  {overview.accepted.map((buddy) => {
                    const isShared = sharedBuddyIds.has(buddy.peer_user_id);
                    return (
                      <View style={styles.shareRow} key={buddy.id}>
                        <View style={styles.flex}>
                          <Text style={styles.body}>{buddy.peer_name}</Text>
                          <Text style={styles.muted}>
                            {isShared
                              ? canGrantShare ? "Journey shared" : "Shared access retained while paused"
                              : "Not sharing"}
                          </Text>
                        </View>
                        <TouchableOpacity
                          onPress={() => updateShare(buddy, isShared, sharedJourney)}
                          disabled={busy || (!isShared && !canGrantShare)}
                        >
                          <Text style={isShared ? styles.dangerText : styles.actionText}>
                            {isShared ? "Revoke" : "Share"}
                          </Text>
                        </TouchableOpacity>
                      </View>
                    );
                  })}
                  {overview.accepted.length === 0 ? (
                    <Text style={styles.muted}>Accept or send a Safety Buddy invitation first.</Text>
                  ) : null}
                </View>
              );
            })
          ) : (
            <Text style={styles.muted}>Start and consent to GPS recording in Journey Management before sharing a live journey.</Text>
          )}
        </View>

        {overview.accepted.length > 0 ? (
          <View style={styles.section}>
            <Text style={styles.heading}>Connected Safety Buddies</Text>
            {overview.accepted.map((item) => (
              <View style={styles.card} key={item.id}>
                <Text style={styles.heading}>{item.peer_name}</Text>
                <Text style={styles.muted}>{item.peer_email}</Text>
                <TouchableOpacity onPress={() => unlink(item)} disabled={busy}>
                  <Text style={styles.dangerText}>Remove Safety Buddy</Text>
                </TouchableOpacity>
              </View>
            ))}
          </View>
        ) : null}

        <View style={styles.section}>
          <Text style={styles.heading}>Journeys shared with you</Text>
          {sharedJourneys.length === 0 ? (
            <Text style={styles.muted}>No one is sharing an active journey with you.</Text>
          ) : sharedJourneys.map((item) => (
            <TouchableOpacity
              key={item.id}
              style={styles.card}
              onPress={() => navigation.navigate("Map", { journeyId: item.id, isShared: true })}
            >
              <Text style={styles.heading}>{item.owner_name}&apos;s {item.transport_mode} journey</Text>
              <Text style={styles.muted}>
                {item.origin || "Starting point"} → {item.destination || "Destination"}
              </Text>
              <Text style={styles.actionText}>Open live map</Text>
            </TouchableOpacity>
          ))}
        </View>

        <View style={styles.section}>
          <Text style={styles.heading}>Buddy alerts</Text>
          {alerts.length === 0 ? (
            <Text style={styles.muted}>Alerts will appear here when someone shares a journey with you.</Text>
          ) : alerts.slice(0, 40).map((item) => (
            <View style={[styles.card, !item.read_at && styles.unreadCard]} key={item.id}>
              <Text style={styles.heading}>{item.alert_type.replace(/_/g, " ")}</Text>
              <Text style={styles.body}>{item.description}</Text>
              <Text style={styles.muted}>From {item.owner_name} · {formatDate(item.created_at)}</Text>
              {item.location_captured_at ? (
                <Text style={styles.muted}>Shared location captured {formatDate(item.location_captured_at)}</Text>
              ) : null}
              {item.journey_id && sharedJourneys.some((journeyItem) => journeyItem.id === item.journey_id) ? (
                <ActionButton
                  label="View shared journey"
                  secondary
                  onPress={() => navigation.navigate("Map", {
                    journeyId: item.journey_id,
                    isShared: true,
                  })}
                />
              ) : null}
              {!item.read_at ? (
                <TouchableOpacity onPress={() => markRead(item)}>
                  <Text style={styles.actionText}>Mark as read</Text>
                </TouchableOpacity>
              ) : null}
            </View>
          ))}
        </View>
        {message ? <Text style={styles.message}>{message}</Text> : null}
      </ScrollView>
    </SafeAreaView>
  );
}

export function SafetyMapScreen({ route }) {
  const [location, setLocation] = useState(null);
  const [region, setRegion] = useState(null);
  const [places, setPlaces] = useState([]);
  const [assistancePoints, setAssistancePoints] = useState([]);
  const [reports, setReports] = useState([]);
  const [myReports, setMyReports] = useState([]);
  const [selected, setSelected] = useState(null);
  const [filter, setFilter] = useState("all");
  const [radius, setRadius] = useState(5000);
  const [reportPin, setReportPin] = useState(null);
  const [reportType, setReportType] = useState("unsafe_area");
  const [reportDescription, setReportDescription] = useState("");
  const [reportImages, setReportImages] = useState([]);
  const [previewImage, setPreviewImage] = useState(null);
  const [canModerate, setCanModerate] = useState(false);
  const [pendingReports, setPendingReports] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const reportMode = route.params?.reportMode === true || route.name === "ReportIncident";
  const screenTitle = reportMode
    ? "Report a Safety Concern"
    : route.name === "NearbyHelp"
      ? "Nearby Help"
      : "Safety Map";

  const searchAround = useCallback(async (center, searchRadius) => {
    const [placeResult, pointResult, reportResult] = await Promise.allSettled([
      getNearbyHelp({
        latitude: center.latitude,
        longitude: center.longitude,
        radius_m: searchRadius,
      }),
      getNearbyAssistancePoints({
        latitude: center.latitude,
        longitude: center.longitude,
        radius_m: searchRadius,
      }),
      getVerifiedCommunityReports({
        latitude: center.latitude,
        longitude: center.longitude,
        radius_m: searchRadius,
      }),
    ]);
    const errors = [];
    if (placeResult.status === "fulfilled") {
      setPlaces(placeResult.value);
    } else {
      setPlaces([]);
      errors.push(`Nearby help: ${placeResult.reason.message || "place search unavailable"}`);
    }
    if (pointResult.status === "fulfilled") {
      setAssistancePoints(pointResult.value);
    } else {
      setAssistancePoints([]);
      errors.push(`Verified assistance points: ${pointResult.reason.message || "search unavailable"}`);
    }
    if (reportResult.status === "fulfilled") {
      setReports(reportResult.value);
    } else {
      setReports([]);
      errors.push(`Community reports: ${reportResult.reason.message || "report search unavailable"}`);
    }
    setMessage(errors.join(" "));
  }, []);

  useFocusEffect(
    useCallback(() => {
      let active = true;
      Promise.allSettled([
        getSafetyMapModeratorAccess(),
        getMyCommunityReports(),
      ]).then(async ([accessResult, reportsResult]) => {
        if (!active) return;
        if (accessResult.status === "fulfilled") {
          setCanModerate(accessResult.value.can_moderate);
          if (accessResult.value.can_moderate) {
            try {
              setPendingReports(await getPendingSafetyMapReports());
            } catch (error) {
              setMessage(error.message || "Couldn't load the report review queue.");
            }
          }
        } else {
          setMessage(accessResult.reason.message || "Couldn't load map moderation access.");
        }
        if (reportsResult.status === "fulfilled") {
          setMyReports(reportsResult.value);
        } else {
          setMessage(reportsResult.reason.message || "Couldn't load your report history.");
        }
      });
      return () => {
        active = false;
      };
    }, [])
  );

  const loadNearby = async () => {
    setLoading(true);
    setMessage("");
    try {
      const permission = await Location.requestForegroundPermissionsAsync();
      if (permission.status !== "granted") {
        throw new Error("Location permission is needed to search nearby services.");
      }
      if (!await Location.hasServicesEnabledAsync()) {
        throw new Error("Turn on location services to search nearby.");
      }
      const fix = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      const center = {
        latitude: fix.coords.latitude,
        longitude: fix.coords.longitude,
      };
      setLocation(center);
      setRegion({
        ...center,
        latitudeDelta: 0.045,
        longitudeDelta: 0.045,
      });
      setSelected(null);
      await searchAround(center, radius);
    } catch (error) {
      setMessage(error.message || "Couldn't get your location or load nearby places.");
    } finally {
      setLoading(false);
    }
  };

  const requestLocationSearch = () => {
    Alert.alert(
      "Search around your location?",
      "Your coordinates are sent to SheRail and OpenStreetMap to find nearby assistance. SheRail does not store this search location. You can clear it from the screen at any time.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Share location for search", onPress: loadNearby },
      ]
    );
  };

  const clearLocation = () => {
    setLocation(null);
    setRegion(null);
    setPlaces([]);
    setAssistancePoints([]);
    setReports([]);
    setSelected(null);
    setReportPin(null);
    setMessage("Search location and loaded results were cleared from this screen.");
  };

  const changeRadius = async (value) => {
    setRadius(value);
    if (location) {
      setLoading(true);
      try {
        await searchAround(location, value);
      } finally {
        setLoading(false);
      }
    }
  };

  const chooseReportImages = async () => {
    const remaining = 4 - reportImages.length;
    if (remaining <= 0) {
      setMessage("A report can include up to four images.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        throw new Error("Allow photo-library access to attach report images.");
      }
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        allowsMultipleSelection: true,
        selectionLimit: remaining,
        quality: 0.8,
      });
      if (result.canceled) return;
      const supportedImages = result.assets.filter((asset) => {
        if (asset.fileSize != null && asset.fileSize > 5 * 1024 * 1024) return false;
        const type = asset.mimeType || "";
        return !type || ["image/jpeg", "image/png", "image/webp"].includes(type);
      });
      if (supportedImages.length !== result.assets.length) {
        setMessage("Only JPEG, PNG, or WebP images up to 5 MB can be attached.");
      }
      setReportImages((current) => [...current, ...supportedImages].slice(0, 4));
    } catch (error) {
      setMessage(error.message || "Couldn't select report images.");
    } finally {
      setBusy(false);
    }
  };

  const openReportImage = async (report, imageId) => {
    try {
      const source = await getAuthenticatedImageSource(
        `/map/reports/${encodeURIComponent(report.id)}/images/${encodeURIComponent(imageId)}`
      );
      setPreviewImage(source);
    } catch (error) {
      setMessage(error.message || "Couldn't load this report image.");
    }
  };

  const submitReport = () => {
    if (!reportPin) {
      setMessage("Long-press the map to choose the report location.");
      return;
    }
    if (reportDescription.trim().length < 10) {
      setMessage("Add at least 10 characters describing the safety concern.");
      return;
    }
    Alert.alert(
      "Submit for moderator review?",
      "The selected map point and your description will be stored with your account. Do not include names, phone numbers, or other identifying details. The report will not appear on the map unless a moderator verifies it.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Submit report",
          onPress: async () => {
            setBusy(true);
            setMessage("");
            try {
              const details = {
                report_type: reportType,
                description: reportDescription.trim(),
                latitude: reportPin.latitude,
                longitude: reportPin.longitude,
              };
              const created = reportImages.length > 0
                ? await submitCommunitySafetyReportWithImages(details, reportImages)
                : await submitCommunitySafetyReport(details);
              setMyReports((current) => [
                created,
                ...current.filter((item) => item.id !== created.id),
              ]);
              setReportPin(null);
              setReportDescription("");
              setReportImages([]);
              setMessage(created.status === "duplicate"
                ? `Possible duplicate linked to an earlier report (${created.duplicate_of_id}).`
                : "Report submitted for moderator review. It is not public until verified.");
              if (canModerate) setPendingReports(await getPendingSafetyMapReports());
            } catch (error) {
              setMessage(error.message || "Couldn't submit this community report.");
            } finally {
              setBusy(false);
            }
          },
        },
      ]
    );
  };

  const reviewReport = (report, nextStatus) => {
    Alert.alert(
      nextStatus === "verified" ? "Verify this report?" : "Reject this report?",
      nextStatus === "verified"
        ? "Only verified reports are shown to SheRail users on the Safety Map."
        : "This report will remain hidden from the Safety Map.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: nextStatus === "verified" ? "Verify" : "Reject",
          style: nextStatus === "verified" ? "default" : "destructive",
          onPress: async () => {
            setBusy(true);
            try {
              await reviewCommunitySafetyReport(report.id, nextStatus);
              setPendingReports((current) => current.filter((item) => item.id !== report.id));
              if (nextStatus === "verified" && location) {
                await searchAround(location, radius);
              }
            } catch (error) {
              setMessage(error.message || "Couldn't review this report.");
            } finally {
              setBusy(false);
            }
          },
        },
      ]
    );
  };

  const openPlace = async (item) => {
    try {
      if (item.osm_url) {
        await Linking.openURL(item.osm_url);
      } else if (item.phone) {
        await Linking.openURL(`tel:${item.phone}`);
      } else {
        setMessage("No external contact link is available for this verified location.");
      }
    } catch {
      setMessage("Could not open this location's contact link.");
    }
  };

  const callAssistancePoint = async (phone) => {
    try {
      await Linking.openURL(`tel:${phone}`);
    } catch (error) {
      setMessage(error.message || "Could not open the phone app.");
    }
  };

  const openMapAttribution = async () => {
    try {
      await Linking.openURL("https://www.openstreetmap.org/copyright");
    } catch (error) {
      setMessage(error.message || "Could not open OpenStreetMap attribution.");
    }
  };

  const isSelectedCategory = (category) => {
    if (filter === "all" || filter === "reports") return true;
    if (filter === "hospital") return category === "hospital" || category === "clinic";
    if (filter === "assistance") {
      return ["assistance", "assistance_point", "shelter", "crisis_center", "railway_assistance"]
        .includes(category);
    }
    return category === filter;
  };
  const visiblePlaces = places.filter((item) => isSelectedCategory(item.category));
  const visibleAssistancePoints = assistancePoints.filter((item) => isSelectedCategory(item.category));
  const visibleReports = filter === "all" || filter === "reports" ? reports : [];
  const placeColor = (category) => (
    category === "police" ? "#2864a5" : category === "hospital" ? "#c23838" : "#6b4ba1"
  );

  return (
    <SafeAreaView style={styles.root}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Text style={styles.title}>{screenTitle}</Text>
        <Text style={styles.body}>
          Nearby services come from live OpenStreetMap data. Community reports are displayed only after moderator verification.
        </Text>
        <View style={styles.row}>
          <TouchableOpacity
            style={[styles.button, styles.flex]}
            onPress={requestLocationSearch}
            disabled={loading}
          >
            <Text style={styles.buttonText}>
              {loading ? "Searching..." : location ? "Refresh nearby search" : "Use my location"}
            </Text>
          </TouchableOpacity>
          {location ? (
            <TouchableOpacity style={styles.clearButton} onPress={clearLocation}>
              <Text style={styles.dangerText}>Clear</Text>
            </TouchableOpacity>
          ) : null}
        </View>
        <View style={styles.optionRow}>
          {[1000, 5000, 10000].map((value) => (
            <TouchableOpacity
              key={value}
              style={[styles.chip, radius === value && styles.chipSelected]}
              onPress={() => changeRadius(value)}
              disabled={loading}
            >
              <Text style={[styles.chipText, radius === value && styles.chipTextSelected]}>
                {value / 1000} km
              </Text>
            </TouchableOpacity>
          ))}
        </View>
        <View style={styles.optionRow}>
          {MAP_FILTERS.map(([value, label]) => (
            <TouchableOpacity
              key={value}
              style={[styles.chip, filter === value && styles.chipSelected]}
              onPress={() => setFilter(value)}
            >
              <Text style={[styles.chipText, filter === value && styles.chipTextSelected]}>
                {label}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {region ? (
          <MapView
            style={styles.map}
            region={region}
            onRegionChangeComplete={setRegion}
            showsUserLocation
            showsMyLocationButton={false}
            onLongPress={(event) => {
              const { latitude, longitude } = event.nativeEvent.coordinate;
              setReportPin({ latitude, longitude });
              setSelected(null);
              setMessage("");
            }}
          >
            {visiblePlaces.map((item) => (
              <Marker
                key={`osm-${item.id}`}
                coordinate={{ latitude: item.latitude, longitude: item.longitude }}
                title={item.name}
                description={`${item.category} · ${item.distance_m} m away`}
                pinColor={placeColor(item.category)}
                onPress={() => setSelected({ kind: "place", item })}
              />
            ))}
            {visibleAssistancePoints.map((item) => (
              <Marker
                key={`verified-${item.id}`}
                coordinate={{ latitude: item.latitude, longitude: item.longitude }}
                title={item.name}
                description={`SheRail-verified ${item.category} · ${item.distance_m} m away`}
                pinColor={placeColor(item.category)}
                onPress={() => setSelected({ kind: "assistancePoint", item })}
              />
            ))}
            {visibleReports.map((item) => (
              <Marker
                key={`report-${item.id}`}
                coordinate={{ latitude: item.latitude, longitude: item.longitude }}
                title={item.report_type.replace(/_/g, " ")}
                description={`Verified ${formatDate(item.verified_at)}`}
                pinColor="#d15a26"
                onPress={() => setSelected({ kind: "report", item })}
              />
            ))}
            {reportPin ? (
              <Marker
                coordinate={reportPin}
                title="Selected report location"
                pinColor="#222"
              />
            ) : null}
          </MapView>
        ) : (
          <View style={styles.mapPlaceholder}>
            <Text style={styles.muted}>Share your location for this search to load the map and real nearby data.</Text>
          </View>
        )}

        <TouchableOpacity onPress={openMapAttribution}>
          <Text style={styles.attribution}>Map data © OpenStreetMap contributors</Text>
        </TouchableOpacity>
        {loading ? <ActivityIndicator color={DEEP_PINK} /> : null}

        {selected ? (
          <View style={styles.card}>
            <Text style={styles.heading}>
              {selected.kind === "report"
                ? selected.item.report_type.replace(/_/g, " ")
                : selected.item.name}
            </Text>
            {selected.kind === "place" ? (
              <>
                <Text style={styles.muted}>
                  {selected.item.category} · {selected.item.distance_m} m away
                </Text>
                {selected.item.address ? <Text style={styles.muted}>{selected.item.address}</Text> : null}
                <ActionButton label="Open OpenStreetMap details" secondary onPress={() => openPlace(selected.item)} />
              </>
            ) : selected.kind === "assistancePoint" ? (
              <>
                <Text style={styles.muted}>
                  SheRail-verified {selected.item.category} · {selected.item.distance_m} m away
                </Text>
                {selected.item.address ? <Text style={styles.muted}>{selected.item.address}</Text> : null}
                {selected.item.description ? <Text style={styles.body}>{selected.item.description}</Text> : null}
                {selected.item.phone ? (
                  <ActionButton
                    label={`Call ${selected.item.phone}`}
                    secondary
                    onPress={() => callAssistancePoint(selected.item.phone)}
                  />
                ) : null}
              </>
            ) : (
              <>
                <Text style={styles.body}>{selected.item.description}</Text>
                <Text style={styles.muted}>
                  Moderator-verified {formatDate(selected.item.verified_at)}
                  {selected.item.distance_m != null ? ` · ${selected.item.distance_m} m away` : ""}
                </Text>
              </>
            )}
          </View>
        ) : null}

        {location ? (
          <>
            <Text style={styles.sectionHeading}>Nearby assistance locations</Text>
            {visiblePlaces.length + visibleAssistancePoints.length === 0 ? (
              <Text style={styles.muted}>No matching OpenStreetMap locations or SheRail-verified assistance points were returned for this search radius.</Text>
            ) : [...visiblePlaces, ...visibleAssistancePoints].slice(0, 120).map((item) => (
              <TouchableOpacity
                style={styles.listCard}
                key={`${item.source}-${item.id}`}
                onPress={() => setSelected({
                  kind: item.source === "sherail_verified" ? "assistancePoint" : "place",
                  item,
                })}
              >
                <Text style={styles.heading}>{item.name}</Text>
                <Text style={styles.muted}>
                  {item.source === "sherail_verified" ? "SheRail verified · " : ""}
                  {item.category} · {item.distance_m} m away{item.address ? ` · ${item.address}` : ""}
                </Text>
              </TouchableOpacity>
            ))}
            <Text style={styles.sectionHeading}>Verified community reports</Text>
            {visibleReports.length === 0 ? (
              <Text style={styles.muted}>No verified community reports were returned for this search radius.</Text>
            ) : visibleReports.slice(0, 80).map((item) => (
              <TouchableOpacity
                style={styles.listCard}
                key={item.id}
                onPress={() => setSelected({ kind: "report", item })}
              >
                <Text style={styles.heading}>{item.report_type.replace(/_/g, " ")}</Text>
                <Text style={styles.body}>{item.description}</Text>
                <Text style={styles.muted}>
                  Verified {formatDate(item.verified_at)}
                  {item.distance_m != null ? ` · ${item.distance_m} m away` : ""}
                </Text>
              </TouchableOpacity>
            ))}
          </>
        ) : null}

        {location ? (
          <View style={styles.section}>
            <Text style={styles.sectionHeading}>Submit a community safety report</Text>
            <Text style={styles.muted}>
              Long-press the map to place a pin. Reports stay private until a moderator verifies them.
            </Text>
            {reportPin ? (
              <View style={styles.card}>
                <Text style={styles.heading}>Report location selected</Text>
                <View style={styles.optionRow}>
                  {REPORT_TYPES.map(([value, label]) => (
                    <TouchableOpacity
                      key={value}
                      style={[styles.chip, reportType === value && styles.chipSelected]}
                      onPress={() => setReportType(value)}
                    >
                      <Text style={[styles.chipText, reportType === value && styles.chipTextSelected]}>
                        {label}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>
                <TextInput
                  style={[styles.input, styles.multiline]}
                  accessibilityLabel="Community safety report description"
                  placeholder="Describe the safety concern (10–500 characters)"
                  value={reportDescription}
                  onChangeText={setReportDescription}
                  multiline
                  maxLength={500}
                />
                <Text style={styles.muted}>
                  Attach up to four JPEG, PNG, or WebP images (5 MB each). Images and the selected report location are stored for moderator review.
                </Text>
                <ActionButton
                  label={reportImages.length ? `Add images (${reportImages.length}/4)` : "Attach images"}
                  secondary
                  onPress={chooseReportImages}
                  disabled={busy || reportImages.length >= 4}
                />
                {reportImages.map((image, index) => (
                  <View style={styles.imageRow} key={`${image.uri}-${index}`}>
                    <Image source={{ uri: image.uri }} style={styles.reportThumbnail} />
                    <View style={styles.flex}>
                      <Text style={styles.body}>{image.fileName || `Selected image ${index + 1}`}</Text>
                      <TouchableOpacity
                        onPress={() => setReportImages((current) => current.filter((_, i) => i !== index))}
                        disabled={busy}
                      >
                        <Text style={styles.dangerText}>Remove image</Text>
                      </TouchableOpacity>
                    </View>
                  </View>
                ))}
                <ActionButton
                  label={busy ? "Submitting..." : "Submit for review"}
                  onPress={submitReport}
                  disabled={busy}
                />
                <ActionButton
                  label="Remove selected location"
                  secondary
                  onPress={() => setReportPin(null)}
                  disabled={busy}
                />
              </View>
            ) : (
              <ActionButton
                label="Choose a report location on the map"
                secondary
                onPress={() => setMessage("Long-press the map to choose where the concern occurred.")}
              />
            )}
          </View>
        ) : null}

        <View style={styles.section}>
          <Text style={styles.sectionHeading}>Your community reports</Text>
          {myReports.length === 0 ? (
            <Text style={styles.muted}>You have not submitted any community safety reports.</Text>
          ) : myReports.slice(0, 30).map((item) => (
            <View style={styles.card} key={item.id}>
              <Text style={styles.heading}>{item.report_type.replace(/_/g, " ")}</Text>
              <Text style={styles.body}>{item.description}</Text>
              <Text style={styles.muted}>
                Status: {item.status.replace(/_/g, " ")} · Submitted {formatDate(item.created_at)}
              </Text>
              {item.duplicate_of_id ? (
                <Text style={styles.muted}>Linked to earlier report {item.duplicate_of_id}.</Text>
              ) : null}
              {item.image_ids?.map((imageId) => (
                <TouchableOpacity
                  key={imageId}
                  onPress={() => openReportImage(item, imageId)}
                >
                  <Text style={styles.actionText}>View attached image</Text>
                </TouchableOpacity>
              ))}
            </View>
          ))}
        </View>

        {previewImage ? (
          <View style={styles.card}>
            <Image source={previewImage} style={styles.imagePreview} resizeMode="contain" />
            <ActionButton
              label="Close image"
              secondary
              onPress={() => setPreviewImage(null)}
            />
          </View>
        ) : null}

        {canModerate ? (
          <View style={styles.section}>
            <Text style={styles.sectionHeading}>Community report review queue</Text>
            {pendingReports.length === 0 ? (
              <Text style={styles.muted}>No reports are waiting for review.</Text>
            ) : pendingReports.map((item) => (
              <View style={styles.card} key={item.id}>
                <Text style={styles.heading}>{item.report_type.replace(/_/g, " ")}</Text>
                <Text style={styles.body}>{item.description}</Text>
                <Text style={styles.muted}>Submitted {formatDate(item.created_at)}</Text>
                <View style={styles.row}>
                  <ActionButton
                    label="Verify"
                    onPress={() => reviewReport(item, "verified")}
                    disabled={busy}
                  />
                  <ActionButton
                    label="Reject"
                    secondary
                    onPress={() => reviewReport(item, "rejected")}
                    disabled={busy}
                  />
                </View>
              </View>
            ))}
          </View>
        ) : null}
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
  sectionHeading: { color: "#222", fontSize: 18, fontWeight: "800", marginTop: 18, marginBottom: 8 },
  body: { color: "#333", lineHeight: 21, marginBottom: 8 },
  muted: { color: "#555", lineHeight: 19, marginBottom: 7 },
  card: { backgroundColor: WHITE, padding: 14, borderRadius: 12, marginTop: 10 },
  listCard: { backgroundColor: WHITE, padding: 12, borderRadius: 10, marginTop: 8 },
  unreadCard: { borderWidth: 1, borderColor: DEEP_PINK },
  section: { marginTop: 14 },
  input: {
    backgroundColor: WHITE,
    borderWidth: 1,
    borderColor: "#f0d7df",
    borderRadius: 10,
    padding: 12,
    marginTop: 8,
    marginBottom: 8,
  },
  multiline: { minHeight: 100, textAlignVertical: "top" },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  flex: { flex: 1 },
  shareRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 10,
    borderTopWidth: 1,
    borderTopColor: "#f5e5ea",
  },
  imageRow: { flexDirection: "row", alignItems: "center", gap: 12, marginTop: 10 },
  reportThumbnail: { width: 72, height: 72, borderRadius: 8, backgroundColor: "#eee" },
  imagePreview: { width: "100%", height: 260, backgroundColor: "#eee", borderRadius: 8 },
  button: {
    backgroundColor: DEEP_PINK,
    padding: 12,
    borderRadius: 10,
    alignItems: "center",
    marginTop: 8,
    minHeight: 44,
    justifyContent: "center",
  },
  buttonText: { color: WHITE, fontWeight: "800", textAlign: "center" },
  secondaryButton: { backgroundColor: WHITE, borderWidth: 1, borderColor: DEEP_PINK },
  secondaryButtonText: { color: DEEP_PINK },
  clearButton: {
    backgroundColor: WHITE,
    borderWidth: 1,
    borderColor: DEEP_PINK,
    borderRadius: 10,
    padding: 12,
    marginLeft: 8,
    marginTop: 8,
  },
  disabled: { opacity: 0.55 },
  actionText: { color: DEEP_PINK, fontWeight: "800", marginTop: 8 },
  dangerText: { color: "#a32121", fontWeight: "800", marginTop: 8 },
  optionRow: { flexDirection: "row", flexWrap: "wrap", marginTop: 4 },
  chip: {
    borderColor: DEEP_PINK,
    borderWidth: 1,
    borderRadius: 18,
    paddingVertical: 8,
    paddingHorizontal: 12,
    marginRight: 7,
    marginTop: 7,
  },
  chipSelected: { backgroundColor: DEEP_PINK },
  chipText: { color: DEEP_PINK, fontWeight: "700" },
  chipTextSelected: { color: WHITE },
  map: { height: 390, borderRadius: 12, marginTop: 12 },
  mapPlaceholder: {
    height: 220,
    backgroundColor: WHITE,
    borderRadius: 12,
    justifyContent: "center",
    alignItems: "center",
    padding: 20,
    marginTop: 12,
  },
  attribution: { color: "#555", textAlign: "center", marginTop: 7, textDecorationLine: "underline" },
  message: { color: "#a32121", marginTop: 12, lineHeight: 20 },
};
