/* One store, one socket. The frame never unmounts, so a re-render cannot drop it. */
let state = {
  pinned: null, live: null, comparison: null, site: null, nodes: [], offline: false,
  known_locations: [], session: null, sessionState: "idle",
  trace: { top: [], ground: [] }, view: 1, overlay: false, location: "expo_table",
};
const subs = new Set();
export const get = () => state;
export const subscribe = (fn) => (subs.add(fn), () => subs.delete(fn));
export function set(patch) {
  state = { ...state, ...patch };
  subs.forEach((f) => f());
}
const CAP = 600;                       // ~30 s of trace at 20 Hz x 1 value
export function pushTrace(node, v) {
  const cur = state.trace[node] || [];
  const next = cur.concat(v);
  set({ trace: { ...state.trace, [node]: next.slice(-CAP) } });
}
