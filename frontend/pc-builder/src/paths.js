export const BUILDER_BASE = '/mvp4/pc-builder/';
export const CUSTOMER_BASE = '/mvp4/';

export function builderAsset(value) {
  const path = String(value || '');
  if (path.startsWith(BUILDER_BASE)) return path;
  return `${BUILDER_BASE}${path.replace(/^\/+/, '')}`;
}

export const CATALOG_URL = builderAsset('data/catalog.json');
export const BRAND_LOGO_URL = builderAsset('assets/brand/popcornai-header-logo-final.png');

export function normalizeCatalog(catalog) {
  return {
    ...catalog,
    parts: catalog.parts.map(part => ({...part, image: builderAsset(part.image)})),
  };
}
