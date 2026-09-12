/* Shaking severity AT A PLACE.

   Magnitude (Richter, or properly moment magnitude) measures energy released at
   the earthquake's SOURCE — one number for the whole event, the same whether you
   are above it or 300 km away. It cannot describe what a building experiences,
   which is the only thing this screen is about: an M9 Cascadia rupture 150 km
   offshore shakes Seattle LESS than an M6.5 directly beneath it.

   The scale that does describe shaking at a place is Modified Mercalli Intensity
   (MMI) — I to X+, defined by what actually happens there. PGA→MMI thresholds
   below follow Wald et al. (1999), the relation USGS ShakeMap uses. */

export const MMI = [
  [0.014, "IV",  "Light",       "Felt indoors. Dishes and windows rattle."],
  [0.039, "V",   "Moderate",    "Felt by nearly everyone. Small objects fall over."],
  [0.092, "VI",  "Strong",      "Felt by all. Plaster cracks; heavy furniture moves."],
  [0.18,  "VII", "Very strong", "Hard to stand. Weak buildings take real damage."],
  [0.34,  "VIII","Severe",      "Serious damage to ordinary buildings."],
  [0.65,  "IX",  "Violent",     "Heavy damage. Buildings shift off foundations."],
  [1.24,  "X",   "Extreme",     "Most masonry and frame structures destroyed."],
];

export function intensityFor(pga) {
  let hit = MMI[0];
  for (const row of MMI) if (pga >= row[0]) hit = row;
  return { pga, roman: hit[1], word: hit[2], text: hit[3] };
}
