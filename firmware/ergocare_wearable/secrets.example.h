// Copy this file to secrets.h (same folder) and fill in your values.
// secrets.h is git-ignored so your Wi-Fi password never reaches GitHub.
// Leave WIFI_SSID empty to run in USB-only mode.

#define WIFI_SSID     "your-wifi-name"      // must be a 2.4 GHz network (ESP32 has no 5 GHz)
#define WIFI_PASSWORD "your-wifi-password"
#define BACKEND_URL   "http://192.168.1.20:8000"   // laptop IP running the FastAPI backend
#define DEVICE_ID     "ERGO-01"

// Must match DEVICE_INGEST_TOKEN in ergo_ml_backend/.env.
// Generate one with:  python -c "import secrets;print(secrets.token_urlsafe(32))"
#define DEVICE_TOKEN  ""
