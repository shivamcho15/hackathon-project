const j = async (r) => r.json();
export const getState = () => fetch("/api/state").then(j);
export const startSession = (body) =>
  fetch("/api/sessions", { method: "POST", headers: { "Content-Type": "application/json" },
                           body: JSON.stringify(body) }).then(j);
export const pin = () => fetch("/api/pin", { method: "POST" }).then(j);
export const measurements = (location) =>
  fetch(`/api/measurements?location=${encodeURIComponent(location)}`).then(j);
