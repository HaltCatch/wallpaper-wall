/** Encode a catalog-relative path ("images/期数/图.png") for use in a URL. */
export const encodePath = (path: string): string => {
  // User media is served through an access-controlled API URL, while the
  // system catalogue continues to use relative static paths.
  if (/^https?:\/\//i.test(path) || path.startsWith('/')) return path;
  return path.split('/').map(encodeURIComponent).join('/');
};

/**
 * The site root both pages live in. Derived from the document instead of
 * import.meta.url because bundled modules are served from /assets/.
 */
export const appRoot = (): URL => new URL('.', document.baseURI);
