import { useCallback, useEffect, useState } from "react";

// Persists a bearer token in localStorage so the dashboard keeps working
// across reloads when the API's optional auth layer
// (settings.api_auth_enabled) is turned on. When it's off — the default —
// nothing in this app ever needs a token, and every request just omits it.
const STORAGE_KEY = "legal-engine-api-token";

export function useApiToken() {
  const [token, setTokenState] = useState<string | null>(null);

  useEffect(() => {
    setTokenState(window.localStorage.getItem(STORAGE_KEY));
  }, []);

  const setToken = useCallback((next: string | null) => {
    setTokenState(next);
    if (next) {
      window.localStorage.setItem(STORAGE_KEY, next);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  return { token, setToken };
}
