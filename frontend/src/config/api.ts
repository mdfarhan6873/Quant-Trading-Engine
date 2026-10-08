export const API_CONFIG = {
  // Use environment variables if available, otherwise fallback to local development defaults
  BASE_URL: process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000",
  WS_URL: process.env.NEXT_PUBLIC_WS_URL || "ws://127.0.0.1:8000/ws",
  
  // Endpoint definitions
  ENDPOINTS: {
    KILL_SWITCH: "/api/kill_switch"
  }
};
