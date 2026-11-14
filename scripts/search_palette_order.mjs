/**
 * Derive the emerald-led categorical order and the green ordinal ramp, using the project's validator.
 *
 *   node scripts/search_palette_order.mjs
 *
 * The documented palette leads with blue. Making green the primary data colour means re-deriving the
 * order (the order IS the colour-vision-safety mechanism) and a one-hue green ramp for ordinal scales,
 * then validating both in light AND dark against the surfaces the charts actually sit on. Nothing here is
 * eyeballed: every candidate goes through validate_palette.js.
 */
import { contrast, validate, validateOrdinal } from "./validate_palette.js";

const SURFACE = { light: "#ffffff", dark: "#12161b" };          // card surfaces (see apps/web/src/theme.css)

// ---- OKLCH <-> hex ---------------------------------------------------------------------------
const toLin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const toGam = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
function oklchToHex(L, C, H) {
  const a = C * Math.cos((H * Math.PI) / 180); const b = C * Math.sin((H * Math.PI) / 180);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3;
  const rgb = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s];
  if (rgb.some((v) => v < -0.0005 || v > 1.0005)) return null;                     // out of sRGB gamut
  return "#" + rgb.map((v) => Math.round(Math.min(1, Math.max(0, toGam(Math.min(1, Math.max(0, v))))) * 255)
    .toString(16).padStart(2, "0")).join("");
}
function hexToOklch(hex) {
  const v = [1, 3, 5].map((i) => toLin(parseInt(hex.slice(i, i + 2), 16) / 255));
  const l = Math.cbrt(0.4122214708 * v[0] + 0.5363325363 * v[1] + 0.0514459929 * v[2]);
  const m = Math.cbrt(0.2119034982 * v[0] + 0.6806995451 * v[1] + 0.1073969566 * v[2]);
  const s = Math.cbrt(0.0883024619 * v[0] + 0.2817188376 * v[1] + 0.6299787005 * v[2]);
  const L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s;
  const a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s;
  const b = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s;
  return [L, Math.hypot(a, b), ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360];
}

// ---- 1. emerald: the documented aqua hue, pushed down in lightness until it holds 3:1 on its surface
const AQUA = { light: "#1baf7a", dark: "#199e70" };
const hue = hexToOklch(AQUA.light)[2];
function emerald(mode) {
  let best = null;
  for (let L = 0.76; L >= 0.40; L -= 0.005) {
    for (const C of [0.15, 0.14, 0.13, 0.12, 0.11]) {
      const hex = oklchToHex(L, C, hue);
      if (hex && contrast(hex, SURFACE[mode]) >= 3.0) { best = best ?? hex; return best; }
    }
  }
  return best;
}
const EM = { light: emerald("light"), dark: AQUA.dark };
console.log("emerald (data green):", EM, "hue", hue.toFixed(1), "contrast", {
  light: contrast(EM.light, SURFACE.light).toFixed(2), dark: contrast(EM.dark, SURFACE.dark).toFixed(2) });

// ---- 2. categorical order, emerald first ---------------------------------------------------------
const OTHERS = {
  blue: ["#2a78d6", "#3987e5"], orange: ["#eb6834", "#d95926"], yellow: ["#eda100", "#c98500"],
  magenta: ["#e87ba4", "#d55181"], green: ["#008300", "#008300"], violet: ["#6250d6", "#9085e9"],
  red: ["#e34948", "#e66767"],
};
const names = Object.keys(OTHERS);
const perms = (a) => (a.length <= 1 ? [a] : a.flatMap((x, i) => perms([...a.slice(0, i), ...a.slice(i + 1)]).map((p) => [x, ...p])));
const wd = (rep) => Number(/ΔE ([\d.]+)/.exec(rep.report.find((r) => r[0] === "CVD separation")[2])[1]);
const wn = (rep) => Number(/ΔE ([\d.]+)/.exec(rep.report.find((r) => r[0] === "Normal-vision floor")[2])[1]);
let top = [];
for (const p of perms(names)) {
  const light = [EM.light, ...p.map((n) => OTHERS[n][0])];
  const dark = [EM.dark, ...p.map((n) => OTHERS[n][1])];
  const rl = validate(light, { mode: "light", surface: SURFACE.light });
  const rd = validate(dark, { mode: "dark", surface: SURFACE.dark });
  if (!rl.ok || !rd.ok) continue;
  top.push({ order: ["emerald", ...p], cvd: Math.min(wd(rl), wd(rd)), normal: Math.min(wn(rl), wn(rd)), light, dark });
}
top.sort((a, b) => b.cvd - a.cvd || b.normal - a.normal);
console.log(`\n${top.length} orders pass every hard gate in both modes. Best 5 (worst adjacent CVD ΔE, normal-vision ΔE):`);
for (const t of top.slice(0, 5)) console.log(" ", t.order.join(" → "), "|", t.cvd.toFixed(1), "|", t.normal.toFixed(1));
const best = top[0];
if (best) {
  console.log("\nCHOSEN (light):", best.light.join(","));
  console.log("CHOSEN (dark): ", best.dark.join(","));
  for (const mode of ["light", "dark"]) {
    const r = validate(mode === "light" ? best.light : best.dark, { mode, surface: SURFACE[mode] });
    console.log(`\n[${mode}]`); r.report.forEach(([n, s, d]) => console.log(`  ${String(s).padEnd(7)} ${n}: ${d}`));
  }
}

// ---- 3. one-hue green ordinal ramp (quality scale), validated with --ordinal semantics -----------
function ramp(mode) {
  // sweep the starting lightness and the step: the light end must still hold 2:1 on the surface
  for (const step of [0.09, 0.085, 0.08, 0.075, 0.07, 0.065]) {
    for (let start = mode === "light" ? 0.74 : 0.34; mode === "light" ? start >= 0.56 : start <= 0.60; start += mode === "light" ? -0.01 : 0.01) {
      const Ls = Array.from({ length: 5 }, (_, i) => (mode === "light" ? start - i * step : start + i * step));
      for (const C of [0.13, 0.12, 0.11, 0.10, 0.09]) {
        const hexes = Ls.map((L) => oklchToHex(L, C, hue));
        if (hexes.some((h) => !h)) continue;
        const r = validateOrdinal(hexes, { mode, surface: SURFACE[mode] });
        if (r.ok) return { hexes, r };
      }
    }
  }
  return null;
}
for (const mode of ["light", "dark"]) {
  const r = ramp(mode);
  console.log(`\nORDINAL RAMP (${mode}, low→high):`, r ? r.hexes.join(",") : "none found");
  if (r) r.r.report.forEach(([n, s, d]) => console.log(`  ${String(s).padEnd(7)} ${n}: ${d}`));
  if (r) console.log("  label ink (white vs near-black by contrast):",
    r.hexes.map((h) => (contrast("#ffffff", h) >= contrast("#0b0b0b", h) ? "#ffffff" : "#0b0b0b")).join(","));
}
