"""ASCE 7-22 two-period spectrum and the resonance score.

Evaluate the closed form at exactly the period needed — zero interpolation error.
Interpolating between two array points on a 1/T decay segment would introduce real
error, so "which interpolation method?" has a clean answer: there isn't one.

Use the TWO-period spectrum only. The real response carries six; the multi-period
curve is a genuinely different shape with no single plateau value to divide by, and
the MCEr / vertical pairs are different hazard levels and a different axis entirely.
"""
from . import config


def sa(period_s, sds, sd1, t0, ts, tl=6.0):
    T = float(period_s)
    if T < t0:
        return sds * (0.4 + 0.6 * T / t0)      # linear ramp
    if T <= ts:
        return sds                             # plateau — the spectrum's maximum
    if T <= tl:
        return sd1 / T                         # decay
    return sd1 * tl / (T * T)                  # long-period tail


def band(score):
    if score < config.BAND_GREEN_MAX:
        return "green"
    if score < config.BAND_AMBER_MAX:
        return "amber"
    return "red"


def compare(frequency_hz, spectrum, measurement_location=None, site_address=None,
            location_matches_site=True):
    """The measurement-to-site join. Computed HERE and nowhere else — both Verdict
    and the stiffness screen need it, and computing it twice guarantees drift.

    resonance_score is NOT a safety score. It is the ratio of spectral acceleration
    at the measured period to the spectrum's plateau: a statement about how hard
    this ground shakes at this period, not about whether the building stands up.
    """
    if not frequency_hz or not spectrum:
        return None
    T = 1.0 / frequency_hz
    s = spectrum
    val = sa(T, s["sds"], s["sd1"], s["t0"], s["ts"], s.get("tl", 6.0))
    score = val / s["sds"]
    return {
        "measured_period_s": round(T, 5),
        "sa_at_period_g": round(val, 5),
        "resonance_score": round(score, 5),
        "band": band(score),
        "plateau_t0_s": s["t0"],
        "plateau_ts_s": s["ts"],
        "measurement_location": measurement_location,
        "site_address": site_address,
        "location_matches_site": location_matches_site,
    }


# --- The plain-language verdict --------------------------------------------------
#
# The resonance score alone is NOT a safety statement, and presenting it as one was
# wrong. Sa(T)/sds only says whether a building's sway period lands on the flat top
# of the DESIGN spectrum — and a modern building is designed for that spectrum. For
# a low-rise building on firm ground in Seattle, landing on the plateau is the
# expected case, not an alarm.
#
# Mexico City 1985 is a bad comparison for almost every address: that was soft
# lake-bed clay (site class E/F) amplifying ~11x at long period, under mid-rise
# buildings built to 1970s codes with no seismic detailing. Saying "that's the
# pattern that collapsed buildings in Mexico City" about a 2022 university building
# on class C ground is alarmist, and would not survive a question from anyone who
# knows the case.
#
# What actually drives seismic vulnerability, in rough order of weight:
#   1. WHEN it was built. Pre-1980 construction predates modern seismic detailing.
#      This is the largest factor and the basis of Seattle's own URM list.
#   2. What it sits on. Soft soil (E/F) amplifies; liquefaction can remove support.
#   3. Whether its sway rate coincides with the ground's worst band — real, but the
#      thing the building code already accounts for.

_SOIL_WEIGHT = {"A": 0, "B": 0, "BC": 0, "C": 0, "CD": 1, "D": 1, "DE": 2, "E": 2, "F": 2}
_LIQ_WEIGHT = {"very low": 0, "low": 0, "moderate": 1, "high": 2, "very high": 2}
_ICON = ["good", "ok", "watch"]


def assess(spectrum, site_class, liquefaction, year_built, frequency_hz):
    """Screening summary: a level, a plain headline, and the reasoning behind it."""
    if not (spectrum and frequency_hz):
        return None
    t0, ts = spectrum["t0"], spectrum["ts"]
    period = 1.0 / frequency_hz
    in_band = t0 <= period <= ts
    lo, hi = 1 / ts, 1 / t0

    factors, score = [], 0

    if year_built and year_built >= 2000:
        factors.append(["good", f"Built {year_built}",
                        "Designed to modern seismic code — the same code these hazard "
                        "numbers come from."])
    elif year_built and year_built >= 1980:
        score += 1
        factors.append(["ok", f"Built {year_built}",
                        "Built under seismic code, though an older edition."])
    elif year_built:
        score += 2
        factors.append(["watch", f"Built {year_built}",
                        "Predates modern seismic detailing — the biggest single factor "
                        "in how buildings actually perform."])
    else:
        score += 1
        factors.append(["ok", "Age unknown",
                        "No construction date on record, so older detailing cannot be "
                        "ruled out."])

    sw = _SOIL_WEIGHT.get((site_class or "").upper(), 1)
    score += sw
    factors.append([_ICON[sw], f"Site class {site_class or 'unknown'}",
                    "Firm ground. It does not amplify shaking much." if sw == 0
                    else "Stiff soil — some amplification." if sw == 1
                    else "Soft ground. It amplifies shaking substantially."])

    lw = _LIQ_WEIGHT.get((liquefaction or "").lower(), 1)
    score += lw
    factors.append([_ICON[lw], f"Liquefaction risk: {liquefaction or 'unknown'}",
                    "This ground is not expected to lose strength when shaken." if lw == 0
                    else "Some potential for the ground to weaken while shaking." if lw == 1
                    else "This ground could lose strength during shaking."])

    if in_band:
        score += 1
        factors.append(["ok", f"Sways at {frequency_hz:.2f} Hz",
                        f"Inside the {lo:.1f}-{hi:.1f} Hz range this ground amplifies most. "
                        "Normal for a building this size here, and what the code already "
                        "designs for."])
    else:
        factors.append(["good", f"Sways at {frequency_hz:.2f} Hz",
                        f"Outside the {lo:.1f}-{hi:.1f} Hz range this ground amplifies most."])

    if score <= 1:
        level = "good"
        headline = "This building looks fine."
        sub = ("Nothing here suggests a problem — modern construction on ground that "
               "behaves well.")
    elif score <= 3:
        level = "ok"
        headline = "Probably fine."
        sub = ("Nothing alarming. A couple of things here would be worth mentioning to "
               "someone qualified if you ever get the chance.")
    else:
        level = "watch"
        headline = "Worth having someone take a look."
        sub = ("Several factors line up here. That does not mean it is unsafe — it means "
               "this is the kind of building a city would send an engineer to first.")

    return {"level": level, "headline": headline, "sub": sub, "in_band": in_band,
            "band_lo_hz": round(lo, 2), "band_hi_hz": round(hi, 2),
            "factors": factors, "score": score}
