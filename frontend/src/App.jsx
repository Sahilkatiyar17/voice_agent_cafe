import { useEffect, useState } from "react";
import { API_BASE_URL, APP_TITLE, HEALTH_PATH, REFRESH_INTERVAL_MS } from "./constants";

export default function App() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function checkHealth() {
      try {
        const res = await fetch(`${API_BASE_URL}${HEALTH_PATH}`);
        setHealth(await res.json());
        setError(null);
      } catch (e) {
        console.error("Health check failed:", e);
        setError("Cannot reach the backend");
      }
    }

    checkHealth();
    const timer = setInterval(checkHealth, REFRESH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, []);

  return (
    <div style={{ fontFamily: "sans-serif", padding: 24 }}>
      <h1>{APP_TITLE}</h1>
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {health && (
        <ul>
          <li>Backend OK: {String(health.ok)}</li>
          <li>Postgres: {String(health.postgres)}</li>
          <li>Redis: {String(health.redis)}</li>
        </ul>
      )}
    </div>
  );
}
