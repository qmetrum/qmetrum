/** Parsing and formatting for timestamps that come back from the API.
 *
 * The backend persists timestamps with `datetime.utcnow()`, which is *naive*:
 * the value is UTC, but the serialised string carries no timezone designator
 * (e.g. "2026-07-29T14:54:14.123456"). Per the ECMAScript spec, a date-time
 * string without an offset is parsed as LOCAL time, so `new Date(iso)` silently
 * shifts every API timestamp by the viewer's UTC offset — in CEST that made a
 * freshly-triggered alert read "2h ago" the moment it arrived.
 *
 * Every API timestamp must therefore go through `parseApiDate` rather than
 * `new Date` directly. Date-ONLY strings ("2026-07-29") are exempt: the spec
 * parses those as UTC already, so charts keyed on plain dates are unaffected.
 */

/** True when the string already states a timezone ("Z" or "+02:00"/"-0500"). */
function hasTimezone(iso: string): boolean {
  return /(Z|[+-]\d{2}:?\d{2})$/.test(iso);
}

/** True for a bare calendar date, which the spec already parses as UTC. */
function isDateOnly(iso: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(iso);
}

/** Parse an API timestamp, treating a missing timezone as UTC.
 *  Returns null for empty or unparseable input so callers can render a dash. */
export function parseApiDate(iso?: string | null): Date | null {
  if (!iso) return null;
  const raw = iso.trim();
  if (!raw) return null;
  // Some backends emit "YYYY-MM-DD HH:MM:SS" (a space, not "T"), which older
  // engines reject outright; normalise before adding the designator.
  const normalized = isDateOnly(raw) || hasTimezone(raw) ? raw : `${raw.replace(" ", "T")}Z`;
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Epoch milliseconds for an API timestamp, or null when it cannot be parsed. */
export function apiDateMs(iso?: string | null): number | null {
  return parseApiDate(iso)?.getTime() ?? null;
}

/** Compact relative age, e.g. "just now" / "12m ago" / "3h ago" / "5d ago". */
export function timeAgo(iso?: string | null): string {
  const then = apiDateMs(iso);
  if (then == null) return "";
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

/** Localised calendar date for an API timestamp; em dash when absent. */
export function formatApiDate(iso?: string | null): string {
  return parseApiDate(iso)?.toLocaleDateString() ?? "—";
}

/** Localised date and time for an API timestamp; em dash when absent. */
export function formatApiDateTime(iso?: string | null): string {
  return parseApiDate(iso)?.toLocaleString() ?? "—";
}
