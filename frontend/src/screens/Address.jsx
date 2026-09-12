import { useEffect, useState } from "react";
import { set, get } from "../store.js";

/* The entry point. Nothing else in the app is reachable until an address is in,
   because every other screen is *about* an address: the ground under it, the
   measurement taken at it, the building drawn from its footprint. Landing on a
   populated Measure screen before anyone said which building it was is what made
   the old flow confusing. */
export default function Address({ s }) {
  const [addr, setAddr] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const submit = async (a) => {
    const q = (a ?? addr).trim();
    if (!q) return setErr("Type an address, or pick one below.");
    setBusy(true); setErr(null);
    try {
      const d = await fetch(`/api/site?address=${encodeURIComponent(q)}`).then((r) => r.json());
      if (d.error) { setErr(d.error); return; }
      // Land on Measure: for any address but Founders Hall there is no reading yet,
      // and that screen is where the instructions and the button live.
      set({ site: d, gated: false, view: 1 });
    } catch {
      setErr("Couldn't reach the backend.");
    } finally { setBusy(false); }
  };

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Enter") submit(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const known = s.known_locations || [];
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column",
                  alignItems: "center", justifyContent: "center", gap: 20 }}>
      <div style={{ maxWidth: 760, width: "100%", textAlign: "center" }}>
        <div className="label" style={{ letterSpacing: ".16em" }}>seismic resonance screening</div>
        <div style={{ fontSize: 46, fontWeight: 600, lineHeight: 1.15, margin: "12px 0 6px" }}>
          Which building?
        </div>
        <div style={{ fontSize: "var(--body)", color: "var(--muted)", lineHeight: 1.5 }}>
          Every building sways at its own rate. Enter an address and we'll show you
          that rate, the ground underneath it, and whether the two match.
        </div>

        <div style={{ display: "flex", gap: 10, marginTop: 26 }}>
          <input autoFocus value={addr} onChange={(e) => setAddr(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && submit()}
                 placeholder="4215 E Stevens Way NE, Seattle, WA 98195"
                 style={{ flex: 1, padding: "16px 18px", fontSize: 22, borderRadius: 10,
                          background: "var(--surface)", border: "1px solid var(--border)",
                          color: "var(--text)", fontFamily: "inherit" }} />
          <button className="btn" disabled={busy} onClick={() => submit()}
                  style={{ padding: "16px 26px" }}>{busy ? "looking up…" : "Go ⏎"}</button>
        </div>

        {err && <div className="card" style={{ borderColor: "var(--amber)", marginTop: 14,
                                               textAlign: "left" }}>
          <b>{err}</b>
          <div className="empty" style={{ marginTop: 6 }}>
            Any US address will return ground data. Only the ones below have a
            measurement on file.</div>
        </div>}

        {known.length > 0 && (
          <div style={{ marginTop: 24 }}>
            <div className="empty" style={{ marginBottom: 8 }}>already measured — one click:</div>
            <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
              {known.map((k) => (
                <button key={k} className="btn" disabled={busy}
                  onClick={() => submit(k === "founders_hall"
                    ? "4215 E Stevens Way NE, Seattle, WA 98195" : k)}
                  style={{ fontSize: "var(--body)", padding: "12px 18px",
                           background: "transparent", color: "var(--text)",
                           borderColor: "var(--top)" }}>
                  {k.replace(/_/g, " ")} ✓</button>))}
            </div>
          </div>)}

        <div className="empty" style={{ marginTop: 28, fontSize: "var(--caption)" }}>
          Ground data is live from WA DNR and the USGS. Everything else in the app is
          about the address you enter here.
        </div>
      </div>
    </div>
  );
}
