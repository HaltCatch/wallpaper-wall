/** Shared inline SVG icons.
 *
 * Every action control used to carry a Unicode glyph (◌ ⌘ ↗ ↓ ✓ ♥) as its
 * label. Those render from whatever glyph the platform font happens to ship, so
 * on iOS/iPadOS several came out as broken/placeholder shapes and ⌘ is a
 * Mac-only symbol. Real SVGs render identically everywhere and match the
 * stroke style of the folder/showcase/close icons already in use. */

const svg = (paths: string): string => `<svg viewBox="0 0 24 24" aria-hidden="true">${paths}</svg>`;

/** Density / layout toggle — the four-cell grid. */
export const gridIcon = svg('<rect x="3" y="3" width="7.5" height="7.5" rx="1.4"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.4"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.4"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.4"/>');

/** Download to device. */
export const downloadIcon = svg('<path d="M12 3v12"/><path d="m7 12 5 5 5-5"/><path d="M5 20h14"/>');

/** Copy image link (a chain link). */
export const linkIcon = svg('<path d="M9.5 14.5 14.5 9.5"/><path d="M11.5 6.5 13 5a3.7 3.7 0 0 1 5.2 5.2l-1.5 1.5"/><path d="M12.5 17.5 11 19a3.7 3.7 0 0 1-5.2-5.2l1.5-1.5"/>');

/** Confirmation check, shown briefly after a copy. */
export const checkIcon = svg('<path d="M20 6 9 17l-5-5"/>');

/** Favourite heart. Stroke by default; CSS fills it on `.is-favorite`. */
export const heartIcon = svg('<path d="M12 20.5 4.2 12.9a4.6 4.6 0 0 1 6.5-6.5l1.3 1.3 1.3-1.3a4.6 4.6 0 0 1 6.5 6.5Z"/>');

/** Set as wallpaper — a framed picture. */
export const wallpaperIcon = svg('<rect x="3" y="4.5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.6"/><path d="m21 15-4.5-4.5L6 21"/>');

/** External / SSO arrow (used by the OIDC sign-in button). */
export const externalIcon = svg('<path d="M7 17 17 7"/><path d="M8 7h9v9"/>');
