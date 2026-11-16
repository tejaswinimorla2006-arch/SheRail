// App.js — SheRail full updated (Map=B, background=C, boxed login, compartment number)
import React, { useState, useEffect } from "react";
import {
  StyleSheet,
  Text,
  View,
  TextInput,
  TouchableOpacity,
  SafeAreaView,
  Alert,
  ActivityIndicator,
  ScrollView,
  Image,
  FlatList,
  Linking,
  useColorScheme,
} from "react-native";

import * as Notifications from "expo-notifications";
import AsyncStorage from "@react-native-async-storage/async-storage";

import {
  NavigationContainer,
  createNavigationContainerRef,
  useFocusEffect,
} from "@react-navigation/native";
import { createStackNavigator } from "@react-navigation/stack";
import { MaterialIcons, Ionicons } from "@expo/vector-icons";
import {
  clearSession,
  createEmergencyContact,
  deleteEmergencyContact,
  getEmergencyContacts,
  getProfile,
  loginUser,
  registerUser,
  updateEmergencyContact,
  updateProfile,
} from "./src/services/api";
import {
  JourneyHistory,
  JourneyManagement,
  JourneyMap,
} from "./src/screens/JourneyScreens";
import { SafetyDashboard, SafetySOS } from "./src/screens/SafetyScreens";
import { SafetyBuddyScreen, SafetyMapScreen } from "./src/screens/CommunitySafetyScreens";
import { NotificationsScreen, RailwayAssistanceScreen } from "./src/screens/CommunityModules";
import { getThemeTokens } from "./src/theme";
import { CHECKIN_NOTIFICATION_KIND } from "./src/services/safetyNotifications";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

const Stack = createStackNavigator();
const navigationRef = createNavigationContainerRef();

const PINK = "#f6d9e0";
const DEEP_PINK = "#d47b8f";
const WHITE = "#fff";
const LIGHT_PINK = "#fff6f9";

/* -------------------- Storage helpers -------------------- */
async function saveItem(key, item) {
  try {
    const s = await AsyncStorage.getItem(key);
    const arr = s ? JSON.parse(s) : [];
    arr.unshift(item);
    await AsyncStorage.setItem(key, JSON.stringify(arr));
  } catch (e) {
    console.warn(e);
  }
}
async function readItem(key) {
  try {
    const s = await AsyncStorage.getItem(key);
    return s ? JSON.parse(s) : [];
  } catch (e) {
    console.warn(e);
    return [];
  }
}

/* ================== SPLASH / WELCOME ================== */
function Splash({ navigation }) {
  return (
    <SafeAreaView style={styles.splashRoot}>
      <MaterialIcons name="train" size={110} color={DEEP_PINK} />
      <Text style={styles.splashTitle}>SheRail</Text>
      <Text style={styles.splashSub}>Just for Women</Text>

      <TouchableOpacity
        style={styles.splashBtn}
        onPress={() => navigation.navigate("LoginOptions")}
      >
        <Text style={styles.splashBtnText}>LOGIN</Text>
      </TouchableOpacity>

      {/* decorative tiny icons (subtle wallpaper feel) */}
      <View style={styles.decorRow}>
        <Ionicons name="heart" size={14} color="#ffe6f0" />
        <Ionicons name="star" size={12} color="#ffe6f0" style={{ marginLeft: 8 }} />
        <Ionicons name="shield" size={13} color="#ffe6f0" style={{ marginLeft: 8 }} />
      </View>
    </SafeAreaView>
  );
}

/* ================== LOGIN OPTIONS (boxed) ================== */
function LoginOptions({ navigation }) {
  return (
    <SafeAreaView style={styles.centered}>
      <Text style={styles.sectionTitle}>Choose Login Type</Text>

      <View style={{ width: "90%", marginTop: 12 }}>
        <TouchableOpacity
          style={styles.boxCard}
          onPress={() => navigation.navigate("UserLogin")}
        >
          <Text style={styles.boxTitle}>User</Text>
          <Text style={styles.boxSubtitle}>Login as traveler</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.boxCard, { backgroundColor: WHITE, borderWidth: 1, borderColor: DEEP_PINK }]}
          onPress={() => navigation.navigate("AdminLogin")}
        >
          <Text style={[styles.boxTitle, { color: DEEP_PINK }]}>Admin Web Dashboard</Text>
          <Text style={[styles.boxSubtitle, { color: "#444" }]}>Login as admin</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

/* ================== USER LOGIN ================== */
function UserLogin({ navigation }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [train, setTrain] = useState("");
  const [time, setTime] = useState("");
  const [errors, setErrors] = useState({});
  const [message, setMessage] = useState("");
  const [isRegistering, setIsRegistering] = useState(false);
  const [busy, setBusy] = useState(false);

  const updateField = (field, setter) => (value) => {
    setter(value);
    setErrors((current) => current[field] ? { ...current, [field]: "" } : current);
  };

  const handle = async () => {
    const nextErrors = {
      name: !isRegistering || name.trim() ? "" : "Please enter your name.",
      email: /^\S+@\S+\.\S+$/.test(email.trim()) ? "" : "Enter a valid email address.",
      password: !password ? "Please enter your password." : isRegistering && password.length < 10
        ? "Use at least 10 characters for your password."
        : "",
      train: train.trim() ? "" : "Please add your train number.",
      time: time.trim() ? "" : "Please enter your travel time (for example, 18:30).",
    };
    setErrors(nextErrors);
    setMessage("");
    if (Object.values(nextErrors).some(Boolean)) {
      return;
    }

    setBusy(true);
    try {
      const user = isRegistering
        ? await registerUser({ name: name.trim(), email: email.trim(), password })
        : await loginUser({ email: email.trim(), password });
      navigation.replace("Home", {
        username: user.name,
        train: train.trim(),
        boardingTime: time.trim(),
        isAdmin: false,
      });
    } catch (error) {
      setMessage(error.message || (
        isRegistering
          ? "We couldn't create your account. Please try again."
          : "We couldn't sign you in. Please try again."
      ));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.loginRoot}>
      <ScrollView contentContainerStyle={styles.loginForm} keyboardShouldPersistTaps="handled">
        <Text style={styles.sectionTitleBlack}>{isRegistering ? "Create Account" : "User Login"}</Text>

        {isRegistering ? (
          <>
            <Text style={styles.inputLabel}>Your name *</Text>
            <TextInput
              accessibilityLabel="Your name, required"
              placeholder="e.g. Priya Sharma"
              style={[styles.input, errors.name && styles.inputError]}
              value={name}
              onChangeText={updateField("name", setName)}
              autoComplete="name"
            />
            {errors.name ? <Text style={styles.inputErrorText}>{errors.name}</Text> : null}
          </>
        ) : null}

        <Text style={styles.inputLabel}>Email *</Text>
        <TextInput
          accessibilityLabel="Email, required"
          placeholder="you@example.com"
          style={[styles.input, errors.email && styles.inputError]}
          value={email}
          onChangeText={updateField("email", setEmail)}
          keyboardType="email-address"
          autoCapitalize="none"
          autoComplete="email"
        />
        {errors.email ? <Text style={styles.inputErrorText}>{errors.email}</Text> : null}

        <Text style={styles.inputLabel}>Password *</Text>
        <TextInput
          accessibilityLabel="Password, required"
          placeholder={isRegistering ? "At least 10 characters" : "Enter your password"}
          style={[styles.input, errors.password && styles.inputError]}
          value={password}
          onChangeText={updateField("password", setPassword)}
          secureTextEntry
          autoComplete={isRegistering ? "new-password" : "password"}
        />
        {errors.password ? <Text style={styles.inputErrorText}>{errors.password}</Text> : null}

        <Text style={styles.inputLabel}>Train number *</Text>
        <TextInput
          accessibilityLabel="Train number, required"
          placeholder="e.g. 12001"
          style={[styles.input, errors.train && styles.inputError]}
          value={train}
          onChangeText={updateField("train", setTrain)}
        />
        {errors.train ? <Text style={styles.inputErrorText}>{errors.train}</Text> : null}

        <Text style={styles.inputLabel}>Travel time (boarding time) *</Text>
        <TextInput
          accessibilityLabel="Travel time, required"
          placeholder="e.g. 18:30"
          style={[styles.input, errors.time && styles.inputError]}
          value={time}
          onChangeText={updateField("time", setTime)}
        />
        {errors.time ? <Text style={styles.inputErrorText}>{errors.time}</Text> : null}

        {message ? <Text style={styles.formMessage}>{message}</Text> : null}
        <TouchableOpacity
          style={[styles.primaryBtn, busy && styles.disabledBtn]}
          onPress={handle}
          disabled={busy}
        >
          {busy ? <ActivityIndicator color={WHITE} /> : (
            <Text style={styles.primaryBtnText}>{isRegistering ? "Create Account" : "Continue"}</Text>
          )}
        </TouchableOpacity>

        <TouchableOpacity
          style={styles.modeToggle}
          onPress={() => {
            setIsRegistering((current) => !current);
            setErrors({});
            setMessage("");
          }}
          disabled={busy}
        >
          <Text style={styles.modeToggleText}>
            {isRegistering ? "Already have an account? Sign in" : "New to SheRail? Create an account"}
          </Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

/* ================== USER PROFILE ================== */
function UserProfile({ navigation, route }) {
  const [profile, setProfile] = useState(null);
  const [contacts, setContacts] = useState([]);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [contactName, setContactName] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [contactRelationship, setContactRelationship] = useState("");
  const [editingContactId, setEditingContactId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useFocusEffect(
    React.useCallback(() => {
      let active = true;
      setLoading(true);
      setMessage("");
      Promise.all([getProfile(), getEmergencyContacts()])
        .then(([user, savedContacts]) => {
          if (!active) return;
          setProfile(user);
          setName(user.name);
          setEmail(user.email);
          setContacts(savedContacts);
        })
        .catch((error) => {
          if (active) setMessage(error.message || "Couldn't load your profile.");
        })
        .finally(() => {
          if (active) setLoading(false);
        });
      return () => {
        active = false;
      };
    }, [])
  );

  const resetContactForm = () => {
    setEditingContactId(null);
    setContactName("");
    setContactPhone("");
    setContactRelationship("");
  };

  const saveProfile = async () => {
    if (!name.trim() || !email.trim()) {
      setMessage("Please enter your name and email.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const updated = await updateProfile({ name: name.trim(), email: email.trim() });
      setProfile(updated);
      navigation.navigate("Home", {
        username: updated.name,
        train: route.params?.train,
        boardingTime: route.params?.boardingTime,
        isAdmin: false,
      });
    } catch (error) {
      setMessage(error.message || "Couldn't save your profile.");
    } finally {
      setBusy(false);
    }
  };

  const saveContact = async () => {
    if (!contactName.trim() || !contactPhone.trim()) {
      setMessage("Please enter the contact's name and phone number.");
      return;
    }
    setBusy(true);
    setMessage("");
    const details = {
      name: contactName.trim(),
      phone: contactPhone.trim(),
      relationship: contactRelationship.trim() || null,
    };
    try {
      if (editingContactId) {
        const updated = await updateEmergencyContact(editingContactId, details);
        setContacts((current) => current.map((item) => item.id === updated.id ? updated : item));
      } else {
        const created = await createEmergencyContact(details);
        setContacts((current) => [...current, created]);
      }
      resetContactForm();
    } catch (error) {
      setMessage(error.message || "Couldn't save this emergency contact.");
    } finally {
      setBusy(false);
    }
  };

  const removeContact = async (id) => {
    setMessage("");
    try {
      await deleteEmergencyContact(id);
      setContacts((current) => current.filter((item) => item.id !== id));
      if (editingContactId === id) resetContactForm();
    } catch (error) {
      setMessage(error.message || "Couldn't remove this emergency contact.");
    }
  };

  const editContact = (contact) => {
    setEditingContactId(contact.id);
    setContactName(contact.name);
    setContactPhone(contact.phone);
    setContactRelationship(contact.relationship || "");
    setMessage("");
  };

  return (
    <SafeAreaView style={styles.loginRoot}>
      <ScrollView contentContainerStyle={styles.profileContent} keyboardShouldPersistTaps="handled">
        <Text style={styles.sectionTitleBlack}>My Profile</Text>
        {loading ? <ActivityIndicator color={DEEP_PINK} /> : null}
        {profile ? (
          <>
            <Text style={styles.inputLabel}>Your name *</Text>
            <TextInput
              accessibilityLabel="Your name"
              placeholder="Enter your name"
              style={styles.input}
              value={name}
              onChangeText={setName}
              autoComplete="name"
            />
            <Text style={styles.inputLabel}>Email *</Text>
            <TextInput
              accessibilityLabel="Email"
              placeholder="you@example.com"
              style={styles.input}
              value={email}
              onChangeText={setEmail}
              keyboardType="email-address"
              autoCapitalize="none"
              autoComplete="email"
            />
            <TouchableOpacity style={styles.primaryBtn} onPress={saveProfile} disabled={busy}>
              <Text style={styles.primaryBtnText}>Save Profile</Text>
            </TouchableOpacity>

            <Text style={styles.profileSectionTitle}>Emergency Contacts</Text>
            {contacts.length === 0 ? (
              <Text style={styles.profileHint}>Add someone you trust to contact in an emergency.</Text>
            ) : contacts.map((contact) => (
              <View key={contact.id} style={styles.contactCard}>
                <View style={styles.contactDetails}>
                  <Text style={styles.contactName}>{contact.name}</Text>
                  <Text style={styles.profileHint}>{contact.phone}</Text>
                  {contact.relationship ? (
                    <Text style={styles.profileHint}>{contact.relationship}</Text>
                  ) : null}
                </View>
                <View style={styles.contactActions}>
                  <TouchableOpacity onPress={() => editContact(contact)}>
                    <Text style={styles.modeToggleText}>Edit</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={() => Alert.alert(
                      "Remove contact?",
                      `Remove ${contact.name} from your emergency contacts?`,
                      [
                        { text: "Cancel", style: "cancel" },
                        { text: "Remove", style: "destructive", onPress: () => removeContact(contact.id) },
                      ]
                    )}
                  >
                    <Text style={styles.removeText}>Remove</Text>
                  </TouchableOpacity>
                </View>
              </View>
            ))}

            <Text style={styles.profileSectionTitle}>
              {editingContactId ? "Edit Emergency Contact" : "Add Emergency Contact"}
            </Text>
            <Text style={styles.inputLabel}>Contact name *</Text>
            <TextInput
              accessibilityLabel="Contact name"
              placeholder="Enter their name"
              style={styles.input}
              value={contactName}
              onChangeText={setContactName}
            />
            <Text style={styles.inputLabel}>Phone number *</Text>
            <TextInput
              accessibilityLabel="Contact phone number"
              placeholder="e.g. +1 555 010 1234"
              style={styles.input}
              value={contactPhone}
              onChangeText={setContactPhone}
              keyboardType="phone-pad"
            />
            <Text style={styles.inputLabel}>Relationship (optional)</Text>
            <TextInput
              accessibilityLabel="Relationship to contact"
              placeholder="e.g. Sister"
              style={styles.input}
              value={contactRelationship}
              onChangeText={setContactRelationship}
            />
            <TouchableOpacity style={styles.primaryBtn} onPress={saveContact} disabled={busy}>
              <Text style={styles.primaryBtnText}>
                {editingContactId ? "Save Contact" : "Add Contact"}
              </Text>
            </TouchableOpacity>
            {editingContactId ? (
              <TouchableOpacity style={styles.modeToggle} onPress={resetContactForm}>
                <Text style={styles.modeToggleText}>Cancel editing</Text>
              </TouchableOpacity>
            ) : null}
          </>
        ) : null}
        {message ? <Text style={styles.formMessage}>{message}</Text> : null}
      </ScrollView>
    </SafeAreaView>
  );
}

/* ================== ADMIN LOGIN ================== */
function AdminLogin() {
  const handle = async () => {
    const adminUrl = process.env.EXPO_PUBLIC_ADMIN_URL;
    if (!adminUrl || !adminUrl.startsWith("https://")) {
      Alert.alert(
        "Admin dashboard unavailable",
        "Configure the secure SheRail admin dashboard URL before opening it."
      );
      return;
    }
    try {
      await Linking.openURL(adminUrl);
    } catch (error) {
      Alert.alert("Couldn't open dashboard", error.message || "Try again later.");
    }
  };

  return (
    <SafeAreaView style={styles.loginRoot}>
      <Text style={styles.sectionTitleBlack}>Admin Web Dashboard</Text>
      <Text style={styles.muted}>
        Administrator credentials and access checks are handled by the secured web dashboard.
      </Text>

      <TouchableOpacity style={styles.primaryBtn} onPress={handle}>
        <Text style={styles.primaryBtnText}>Open Admin Dashboard</Text>
      </TouchableOpacity>
    </SafeAreaView>
  );
}

/* ================== HOME (USER) ================== */
function HomeActionCard({ title, description, icon, onPress, theme, variant = "row" }) {
  const isGrid = variant === "grid";
  const iconContent = (
    <View style={[styles.homeActionIcon, { backgroundColor: theme.accentSoft }]}>
      <Ionicons name={icon} size={21} color={theme.accent} />
    </View>
  );
  const copyContent = (
    <View style={[styles.homeActionCopy, isGrid && styles.homeActionGridCopy]}>
      <Text style={[styles.homeActionTitle, { color: theme.text }]}>{title}</Text>
      <Text style={[styles.homeActionDescription, { color: theme.muted }]}>{description}</Text>
    </View>
  );

  return (
    <TouchableOpacity
      accessibilityRole="button"
      accessibilityLabel={`${title}. ${description}`}
      activeOpacity={0.78}
      onPress={onPress}
      style={[
        styles.homeActionCard,
        isGrid ? styles.homeActionGridCard : styles.homeActionRow,
        { backgroundColor: theme.surface, borderColor: theme.border },
      ]}
    >
      {isGrid ? (
        <>
          <View style={styles.homeActionTop}>
            {iconContent}
            <Ionicons name="chevron-forward" size={18} color={theme.muted} />
          </View>
          {copyContent}
        </>
      ) : (
        <>
          {iconContent}
          {copyContent}
          <Ionicons name="chevron-forward" size={18} color={theme.muted} />
        </>
      )}
    </TouchableOpacity>
  );
}

function Home({ navigation, route }) {
  const { username, train, boardingTime } = route.params ?? {};
  const theme = getThemeTokens(useColorScheme());
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

  const handleLogout = async () => {
    try {
      const warning = await clearSession();
      navigation.replace("LoginOptions");
      if (warning) Alert.alert("Signed out", warning);
    } catch (error) {
      Alert.alert("Sign out failed", error.message || "Please try again.");
    }
  };

  const quickActions = [
    {
      title: "Live map",
      description: "Open your journey map",
      icon: "map-outline",
      onPress: () => navigation.navigate("Map", { username, train }),
    },
    {
      title: "Safety check-ins",
      description: "Check-ins and safety alerts",
      icon: "shield-checkmark-outline",
      onPress: () => navigation.navigate("SafetyDashboard"),
    },
    {
      title: "Safety Buddy",
      description: "Trusted journey sharing",
      icon: "people-outline",
      onPress: () => navigation.navigate("SafetyBuddy"),
    },
    {
      title: "Nearby help",
      description: "Find assistance nearby",
      icon: "medkit-outline",
      onPress: () => navigation.navigate("NearbyHelp"),
    },
    {
      title: "Safety Map",
      description: "Map and verified reports",
      icon: "navigate-outline",
      onPress: () => navigation.navigate("SafetyMap"),
    },
  ];

  return (
    <SafeAreaView style={[styles.homeScreen, { backgroundColor: theme.background }]}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerStyle={styles.homeScrollContent}
      >
        <View style={styles.homeHeader}>
          <View style={[styles.homeBrandMark, { backgroundColor: theme.accentSoft }]}>
            <Ionicons name="shield-checkmark" size={22} color={theme.accent} />
          </View>
          <View>
            <Text style={[styles.homeEyebrow, { color: theme.muted }]}>SHERAIL SAFETY</Text>
            <Text style={[styles.homeGreeting, { color: theme.text }]}>{greeting},</Text>
            <Text style={[styles.homeName, { color: theme.text }]}>{username || "traveller"}</Text>
          </View>
        </View>

        <View style={[styles.journeyCard, { backgroundColor: theme.journey, borderColor: theme.border }]}>
          <View style={styles.journeyCardHeader}>
            <View style={[styles.journeyIcon, { backgroundColor: theme.surface }]}>
              <Ionicons name="train-outline" size={22} color={theme.accent} />
            </View>
            <View style={styles.journeyHeading}>
              <Text style={[styles.journeyTitle, { color: theme.text }]}>Your journey</Text>
              <Text style={[styles.journeyCaption, { color: theme.muted }]}>Travel details</Text>
            </View>
            <View style={[styles.journeyBadge, { backgroundColor: theme.surface }]}>
              <Text style={[styles.journeyBadgeText, { color: theme.accent }]}>MY TRIP</Text>
            </View>
          </View>

          <View style={styles.journeyDetails}>
            <View style={styles.journeyDetail}>
              <Text style={[styles.journeyLabel, { color: theme.muted }]}>TRAIN / SERVICE</Text>
              <Text numberOfLines={1} style={[styles.journeyValue, { color: theme.text }]}>
                {train || "Not added"}
              </Text>
            </View>
            <View style={styles.journeyDetail}>
              <Text style={[styles.journeyLabel, { color: theme.muted }]}>BOARDING TIME</Text>
              <Text numberOfLines={1} style={[styles.journeyValue, { color: theme.text }]}>
                {boardingTime || "Not added"}
              </Text>
            </View>
          </View>

          <TouchableOpacity
            accessibilityRole="button"
            activeOpacity={0.8}
            style={[styles.journeyButton, { backgroundColor: theme.accent }]}
            onPress={() => navigation.navigate("JourneyManagement")}
          >
            <Text style={[styles.journeyButtonText, { color: theme.accentForeground }]}>Manage journey</Text>
            <Ionicons name="arrow-forward" size={18} color={theme.accentForeground} />
          </TouchableOpacity>
        </View>

        <TouchableOpacity
          accessibilityRole="button"
          accessibilityLabel="Open SOS emergency options"
          activeOpacity={0.82}
          style={[styles.sosCard, { backgroundColor: theme.sosSoft, borderColor: theme.border }]}
          onPress={() => navigation.navigate("SOS", { username, train })}
        >
          <View style={[styles.sosIcon, { backgroundColor: theme.sos }]}>
            <Ionicons name="alert" size={24} color={theme.sosForeground} />
          </View>
          <View style={styles.sosCopy}>
            <Text style={[styles.sosTitle, { color: theme.text }]}>Need urgent help?</Text>
            <Text style={[styles.sosDescription, { color: theme.muted }]}>Open SOS emergency options</Text>
          </View>
          <View style={[styles.sosAction, { backgroundColor: theme.sos }]}>
            <Text style={[styles.sosActionText, { color: theme.sosForeground }]}>SOS</Text>
            <Ionicons name="arrow-forward" size={16} color={theme.sosForeground} />
          </View>
        </TouchableOpacity>

        <View style={styles.homeSectionHeader}>
          <Text style={[styles.homeSectionTitle, { color: theme.text }]}>Safety tools</Text>
          <Text style={[styles.homeSectionCaption, { color: theme.muted }]}>Quick access</Text>
        </View>
        <View style={styles.homeActionGridContainer}>
          {quickActions.map((action) => (
            <HomeActionCard key={action.title} {...action} theme={theme} variant="grid" />
          ))}
        </View>

        <View style={styles.homeSectionHeader}>
          <Text style={[styles.homeSectionTitle, { color: theme.text }]}>Your SheRail</Text>
          <Text style={[styles.homeSectionCaption, { color: theme.muted }]}>More features</Text>
        </View>
        <View style={styles.homeMoreList}>
          <HomeActionCard
            title="Profile & emergency contacts"
            description="Manage your details and trusted contacts"
            icon="person-outline"
            onPress={() => navigation.navigate("UserProfile", { username, train, boardingTime })}
            theme={theme}
          />
          <HomeActionCard
            title="Journey history"
            description="Review past journeys and shared routes"
            icon="time-outline"
            onPress={() => navigation.navigate("JourneyHistory")}
            theme={theme}
          />
          <HomeActionCard
            title="Notifications"
            description="View safety updates and alerts"
            icon="notifications-outline"
            onPress={() => navigation.navigate("Notifications")}
            theme={theme}
          />
          <HomeActionCard
            title="Railway Assistance"
            description="Optional railway support"
            icon="help-buoy-outline"
            onPress={() => navigation.navigate("RailwayAssistance")}
            theme={theme}
          />
          <HomeActionCard
            title="Safety Compartment Review"
            description="Share a review for your compartment"
            icon="chatbox-ellipses-outline"
            onPress={() => navigation.navigate("SafetyCompartment", { train })}
            theme={theme}
          />
          <HomeActionCard
            title="Report a safety concern"
            description="Submit a community safety report"
            icon="flag-outline"
            onPress={() => navigation.navigate("SafetyMap", { reportMode: true })}
            theme={theme}
          />
        </View>

        <TouchableOpacity
          accessibilityRole="button"
          activeOpacity={0.8}
          style={[styles.logoutButton, { borderColor: theme.border }]}
          onPress={handleLogout}
        >
          <Ionicons name="log-out-outline" size={19} color={theme.muted} />
          <Text style={[styles.logoutText, { color: theme.muted }]}>Sign out</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

/* ================== Safety Compartment ================== */
function SafetyCompartment({ route }) {
  const { train } = route.params ?? {};
  const [compNo, setCompNo] = useState("");
  const [rating, setRating] = useState(null);
  const [comment, setComment] = useState("");
  const [reviews, setReviews] = useState([]);

  useEffect(() => {
    (async () => {
      const all = await readItem("sr_reviews");
      setReviews(all);
    })();
  }, []);

  const submit = async () => {
    if (!compNo.trim()) return Alert.alert("Compartment", "Please enter compartment number.");
    if (!rating) return Alert.alert("Pick rating", "Select Safe or Unsafe");

    const entry = { id: Date.now().toString(), train: train || "unknown", compartment: compNo.trim(), rating, comment, timestamp: new Date().toISOString() };
    await saveItem("sr_reviews", entry);
    Alert.alert("Thanks", "Your review is saved.");
    setRating(null);
    setComment("");
    // refresh local reviews
    const all = await readItem("sr_reviews");
    setReviews(all);
  };

  // filter reviews for this compartment
  const filtered = reviews.filter((r) => r.train === (train || "") && r.compartment === compNo.trim());

  return (
    <SafeAreaView style={{ flex: 1, padding: 16, backgroundColor: LIGHT_PINK }}>
      <Text style={styles.headingBlack}>Safety Compartment</Text>
      <Text style={{ marginTop: 6 }}>Train: {train}</Text>

      <TextInput placeholder="Enter compartment number" value={compNo} onChangeText={setCompNo} style={{ marginTop: 12, borderWidth: 1, borderColor: "#eee", padding: 10, borderRadius: 8, backgroundColor: WHITE }} />

      <View style={{ flexDirection: "row", marginTop: 12 }}>
        <TouchableOpacity style={[styles.smallChoice, rating === "Safe" && { backgroundColor: DEEP_PINK }]} onPress={() => setRating("Safe")}>
          <Text style={{ color: rating === "Safe" ? WHITE : DEEP_PINK }}>Safe</Text>
        </TouchableOpacity>

        <TouchableOpacity style={[styles.smallChoice, { marginLeft: 12 }, rating === "Unsafe" && { backgroundColor: DEEP_PINK }]} onPress={() => setRating("Unsafe")}>
          <Text style={{ color: rating === "Unsafe" ? WHITE : DEEP_PINK }}>Unsafe</Text>
        </TouchableOpacity>
      </View>

      <TextInput placeholder="Tell us more (optional)" value={comment} onChangeText={setComment} style={{ marginTop: 12, borderWidth: 1, borderColor: "#eee", padding: 10, borderRadius: 8, backgroundColor: WHITE }} />

      <TouchableOpacity style={[styles.primaryBtn, { marginTop: 12 }]} onPress={submit}>
        <Text style={styles.primaryBtnText}>Submit Review</Text>
      </TouchableOpacity>

      <Text style={{ marginTop: 18, fontWeight: "700" }}>Reviews for compartment {compNo || "—"}</Text>
      {filtered.length === 0 ? <Text style={{ marginTop: 8 }}>No reviews for this compartment yet.</Text> : (
        <FlatList
          style={{ marginTop: 8 }}
          data={filtered}
          keyExtractor={(i) => i.id}
          renderItem={({ item }) => (
            <View style={{ backgroundColor: WHITE, padding: 10, borderRadius: 8, marginBottom: 8 }}>
              <Text style={{ fontWeight: "700" }}>{item.rating}</Text>
              <Text>Comment: {item.comment || "—"}</Text>
              <Text>Time: {new Date(item.timestamp).toLocaleString()}</Text>
            </View>
          )}
        />
      )}
    </SafeAreaView>
  );
}

/* ================== App Root & Navigation ================== */
export default function App() {
  const theme = getThemeTokens(useColorScheme());
  const pendingNotificationRef = React.useRef(null);
  const openNotificationTarget = React.useCallback((response) => {
    const data = response?.notification?.request?.content?.data;
    const target = data?.kind === CHECKIN_NOTIFICATION_KIND
      || data?.screen === "SafetyDashboard"
      ? "SafetyDashboard"
      : "Notifications";
    if (navigationRef.isReady()) {
      navigationRef.navigate(target);
    } else {
      pendingNotificationRef.current = target;
    }
  }, []);

  useEffect(() => {
    const subscription = Notifications.addNotificationResponseReceivedListener(openNotificationTarget);
    const lastResponse = Notifications.getLastNotificationResponse();
    if (lastResponse) {
      openNotificationTarget(lastResponse);
      Notifications.clearLastNotificationResponse();
    }
    return () => subscription.remove();
  }, [openNotificationTarget]);

  return (
    <NavigationContainer
      ref={navigationRef}
      onReady={() => {
        if (pendingNotificationRef.current) {
          const target = pendingNotificationRef.current;
          pendingNotificationRef.current = null;
          navigationRef.navigate(target);
        }
      }}
    >
      <Stack.Navigator
        initialRouteName="Splash"
        screenOptions={{
          headerStyle: { backgroundColor: theme.header },
          headerTintColor: theme.text,
          headerTitleStyle: { color: theme.text, fontWeight: "700" },
        }}
      >
        <Stack.Screen name="Splash" component={Splash} options={{ headerShown: false }} />
        <Stack.Screen name="LoginOptions" component={LoginOptions} options={{ title: "Login" }} />
        <Stack.Screen name="UserLogin" component={UserLogin} options={{ title: "User Login" }} />
        <Stack.Screen name="UserProfile" component={UserProfile} options={{ title: "My Profile" }} />
        <Stack.Screen name="AdminLogin" component={AdminLogin} options={{ title: "Admin Login" }} />
        <Stack.Screen name="Home" component={Home} options={{ title: "SheRail Home", headerLeft: null }} />
        <Stack.Screen name="Map" component={JourneyMap} options={{ title: "Live Map" }} />
        <Stack.Screen name="JourneyManagement" component={JourneyManagement} options={{ title: "Journey Management" }} />
        <Stack.Screen name="JourneyHistory" component={JourneyHistory} options={{ title: "Journey History" }} />
        <Stack.Screen name="SOS" component={SafetySOS} options={{ title: "Emergency" }} />
        <Stack.Screen name="SafetyDashboard" component={SafetyDashboard} options={{ title: "Safety Monitoring" }} />
        <Stack.Screen name="SafetyBuddy" component={SafetyBuddyScreen} options={{ title: "Safety Buddy" }} />
        <Stack.Screen name="TravelBuddy" component={SafetyBuddyScreen} options={{ title: "Safety Buddy" }} />
        <Stack.Screen name="NearbyHelp" component={SafetyMapScreen} options={{ title: "Nearby Help" }} />
        <Stack.Screen name="SafetyMap" component={SafetyMapScreen} options={{ title: "Safety Map" }} />
        <Stack.Screen name="Notifications" component={NotificationsScreen} options={{ title: "Notifications" }} />
        <Stack.Screen name="RailwayAssistance" component={RailwayAssistanceScreen} options={{ title: "Railway Assistance" }} />
        <Stack.Screen name="SafetyCompartment" component={SafetyCompartment} options={{ title: "Compartment Review" }} />
        <Stack.Screen name="ReportIncident" component={SafetyMapScreen} options={{ title: "Report a Safety Concern" }} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}

/* ================== Styles ================== */
const styles = StyleSheet.create({
  splashRoot: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: LIGHT_PINK },
  splashTitle: { fontSize: 36, marginTop: 12, fontWeight: "900", color: DEEP_PINK },
  splashSub: { fontSize: 16, marginTop: 4, color: "#555" },
  splashBtn: { marginTop: 28, backgroundColor: DEEP_PINK, paddingVertical: 14, paddingHorizontal: 34, borderRadius: 26 },
  splashBtnText: { color: WHITE, fontWeight: "800", fontSize: 16 },
  decorRow: { position: "absolute", bottom: 20, flexDirection: "row" },

  centered: { flex: 1, alignItems: "center", justifyContent: "center", padding: 20, backgroundColor: LIGHT_PINK },
  sectionTitle: { fontSize: 22, fontWeight: "800", color: DEEP_PINK, marginBottom: 12 },
  sectionTitleBlack: { fontSize: 22, fontWeight: "800", color: "#000", marginBottom: 12 },

  boxCard: { backgroundColor: DEEP_PINK, padding: 18, borderRadius: 12, marginBottom: 12 },
  boxTitle: { color: WHITE, fontSize: 18, fontWeight: "800" },
  boxSubtitle: { color: "#fff5f8", marginTop: 6 },

  loginRoot: { flex: 1, padding: 20, backgroundColor: LIGHT_PINK, justifyContent: "center" },
  loginForm: { flexGrow: 1, justifyContent: "center", paddingVertical: 16 },
  input: { backgroundColor: WHITE, padding: 12, borderRadius: 12, marginBottom: 12, borderWidth: 1, borderColor: PINK },
  inputLabel: { fontWeight: "700", color: "#333", marginBottom: 6 },
  inputError: { borderColor: "#c62828" },
  inputErrorText: { color: "#c62828", fontSize: 13, marginTop: -8, marginBottom: 10 },
  formMessage: { color: "#a32121", marginTop: 8, marginBottom: 4 },
  disabledBtn: { opacity: 0.65 },
  modeToggle: { alignItems: "center", padding: 14 },
  modeToggleText: { color: DEEP_PINK, fontWeight: "700" },
  profileContent: { flexGrow: 1, paddingBottom: 24 },
  profileSectionTitle: { fontSize: 18, fontWeight: "800", color: DEEP_PINK, marginTop: 22, marginBottom: 10 },
  profileHint: { color: "#555", marginTop: 4 },
  contactCard: { backgroundColor: WHITE, borderRadius: 10, padding: 12, marginBottom: 10, flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  contactDetails: { flex: 1 },
  contactName: { fontWeight: "700", color: "#333" },
  contactActions: { alignItems: "flex-end", marginLeft: 12, gap: 8 },
  removeText: { color: "#a32121", fontWeight: "700" },

  primaryBtn: { backgroundColor: DEEP_PINK, padding: 14, borderRadius: 12, alignItems: "center", marginTop: 8 },
  primaryBtnText: { color: WHITE, fontWeight: "800" },

  listText: { fontSize: 16, fontWeight: "700", color: "#333" },

  homeScreen: { flex: 1 },
  homeScrollContent: { paddingHorizontal: 20, paddingTop: 22, paddingBottom: 36 },
  homeHeader: { flexDirection: "row", alignItems: "center", marginBottom: 22 },
  homeBrandMark: { width: 50, height: 50, borderRadius: 17, alignItems: "center", justifyContent: "center", marginRight: 14 },
  homeEyebrow: { fontSize: 10, fontWeight: "800", letterSpacing: 1.6, marginBottom: 4 },
  homeGreeting: { fontSize: 16, fontWeight: "600" },
  homeName: { fontSize: 27, fontWeight: "800", letterSpacing: -0.5 },

  journeyCard: { borderWidth: 1, borderRadius: 24, padding: 18, marginBottom: 14 },
  journeyCardHeader: { flexDirection: "row", alignItems: "center" },
  journeyIcon: { width: 46, height: 46, borderRadius: 16, alignItems: "center", justifyContent: "center", marginRight: 12 },
  journeyHeading: { flex: 1 },
  journeyTitle: { fontSize: 17, fontWeight: "800" },
  journeyCaption: { fontSize: 12, marginTop: 3 },
  journeyBadge: { borderRadius: 20, paddingHorizontal: 10, paddingVertical: 6 },
  journeyBadgeText: { fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  journeyDetails: { flexDirection: "row", marginTop: 18 },
  journeyDetail: { flex: 1, minWidth: 0 },
  journeyLabel: { fontSize: 9, fontWeight: "800", letterSpacing: 1 },
  journeyValue: { fontSize: 15, fontWeight: "700", marginTop: 6 },
  journeyButton: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", borderRadius: 15, paddingHorizontal: 16, paddingVertical: 13, marginTop: 16 },
  journeyButtonText: { fontSize: 14, fontWeight: "800" },

  sosCard: { flexDirection: "row", alignItems: "center", borderWidth: 1, borderRadius: 22, padding: 14, marginBottom: 26 },
  sosIcon: { width: 46, height: 46, borderRadius: 16, alignItems: "center", justifyContent: "center" },
  sosCopy: { flex: 1, marginLeft: 12, marginRight: 8 },
  sosTitle: { fontSize: 15, fontWeight: "800" },
  sosDescription: { fontSize: 11, marginTop: 4 },
  sosAction: { flexDirection: "row", alignItems: "center", borderRadius: 14, paddingHorizontal: 11, paddingVertical: 10 },
  sosActionText: { fontSize: 13, fontWeight: "900", marginRight: 5 },

  homeSectionHeader: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between", marginBottom: 12 },
  homeSectionTitle: { fontSize: 19, fontWeight: "800", letterSpacing: -0.2 },
  homeSectionCaption: { fontSize: 11, fontWeight: "600" },
  homeActionGridContainer: { flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between", marginBottom: 17 },
  homeActionCard: { borderWidth: 1, borderRadius: 19 },
  homeActionGridCard: { width: "48%", minHeight: 128, padding: 13, marginBottom: 11 },
  homeActionRow: { flexDirection: "row", alignItems: "center", minHeight: 70, padding: 12, marginBottom: 10 },
  homeActionTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  homeActionIcon: { width: 40, height: 40, borderRadius: 14, alignItems: "center", justifyContent: "center" },
  homeActionCopy: { flex: 1, marginLeft: 12 },
  homeActionGridCopy: { marginTop: 12, marginLeft: 0 },
  homeActionTitle: { fontSize: 13, fontWeight: "800" },
  homeActionDescription: { fontSize: 11, lineHeight: 15, marginTop: 4 },
  homeMoreList: { marginBottom: 8 },
  logoutButton: { flexDirection: "row", alignItems: "center", justifyContent: "center", borderWidth: 1, borderRadius: 16, padding: 14, marginTop: 2 },
  logoutText: { fontSize: 14, fontWeight: "700", marginLeft: 8 },


  headingBlack: {
  fontSize: 20,
  fontWeight: "800",
  color: "#000"
},

smallChoice: {
  padding: 12,
  borderWidth: 1,
  borderColor: DEEP_PINK,
  borderRadius: 8
}

});