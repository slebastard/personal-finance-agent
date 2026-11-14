import { ReferenceService } from '../reference/reference.service';

/**
 * Mirrors `pfa/taxonomy.py`, but the TABLES come from `data/generated/taxonomy.json`.
 * Only the folding and lookup logic is reimplemented — never the aliases themselves, so a country
 * or sector mapping has exactly one definition in the repository.
 */
export class Taxonomy {
  constructor(private readonly ref: ReferenceService) {}

  private get t() { return this.ref.taxonomy; }

  static fold(s: string): string {
    return (s ?? '')
      .normalize('NFKD')
      .replace(/[̀-ͯ]/g, '')
      .replace(/’/g, "'")
      .toLowerCase()
      .trim()
      .split(/\s+/)
      .join(' ');
  }

  sector(name: string): string {
    const f = Taxonomy.fold(name);
    if (['other', 'autre', 'autres', 'divers', 'cash', 'liquidites'].includes(f)) return 'Other';
    const aliases = (this.t['sector_aliases'] ?? {}) as Record<string, string>;
    if (aliases[f]) return aliases[f]!;
    return ((this.t['gics'] ?? []) as string[]).includes(name) ? name : 'Other';
  }

  country(name: string): string {
    const f = Taxonomy.fold(name);
    const aliases = (this.t['country_aliases'] ?? {}) as Record<string, string>;
    if (aliases[f]) return aliases[f]!;
    const trimmed = (name ?? '').trim();
    if (!trimmed) return 'Other';
    return trimmed.split(/\s+/)
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(' ');
  }

  regionOfCountry(c: string): string {
    return ((this.t['region_of_country'] ?? {}) as Record<string, string>)[c] ?? 'Other';
  }

  get regions(): string[] { return (this.t['regions'] ?? []) as string[]; }
  get gics(): string[] { return (this.t['gics'] ?? []) as string[]; }
}
