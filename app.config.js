module.exports = ({ config }) => {
  const plugins = (config.plugins || []).filter((plugin) => {
    const name = Array.isArray(plugin) ? plugin[0] : plugin;
    return name !== "react-native-maps";
  });
  const mapsApiKey = process.env.GOOGLE_MAPS_API_KEY;

  if (mapsApiKey) {
    plugins.push([
      "react-native-maps",
      { androidGoogleMapsApiKey: mapsApiKey },
    ]);
  }

  return { ...config, plugins };
};
