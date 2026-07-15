const currentLocation = typeof window === 'undefined' ? null : window.location;
const defaultApiBaseUrl = currentLocation
  ? `${currentLocation.protocol}//${currentLocation.hostname}:8000`
  : 'http://localhost:8000';
const defaultWebsocketUrl = currentLocation
  ? `${currentLocation.protocol === 'https:' ? 'wss:' : 'ws:'}//${currentLocation.hostname}:8000/ws/status`
  : 'ws://localhost:8000/ws/status';

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || defaultApiBaseUrl;
export const WEBSOCKET_URL = import.meta.env.VITE_WEBSOCKET_URL || defaultWebsocketUrl;
