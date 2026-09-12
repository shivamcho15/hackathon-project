import { set, get } from "./store.js";
import { startSession, pin } from "./api.js";

/* `S` is the single most important binding: the panic button when a judge says
   "can you do it again?" It arms from ANY screen and jumps to Measure. */
export function onKey(e) {
  if (e.target.tagName === "INPUT") return;
  const s = get();
  const k = e.key;
  if (k === "Escape") {
    if (s.overlay) return set({ overlay: false });
    return set({ view: 1 });                    // abort is a backend concern; Esc lands here
  }
  if (k === "~" || k === "`") return set({ overlay: !s.overlay });
  if (k === " " || k === "ArrowRight") return set({ view: Math.min(4, s.view + 1) });
  if (k === "ArrowLeft") return set({ view: Math.max(1, s.view - 1) });
  if (/^[1-6]$/.test(k)) return set({ view: +k });
  if (k === "s" || k === "S") {
    set({ view: 1 });
    if (s.sessionState !== "idle") return;      // guarded; the button shows why
    startSession({ mode: "building", location: s.location,
                   address: s.site?.address ?? null });
    return;
  }
  if (k === "p" || k === "P") return void pin().then(() => {});
}
