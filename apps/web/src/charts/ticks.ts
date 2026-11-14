import { palette } from './theme';

/**
 * A short vertical mark at (value, category) on a horizontal bar chart: a target or a reference.
 *
 * Drawn as a scatter series with a rectangular symbol. The previous approach, a markLine from a
 * point to itself, has zero length and silently drew nothing — the captions promised "trait =
 * cible" over charts that showed no trait.
 */
export const tickSeries = (points: [value: number, category: string][]) => ({
  type: 'scatter' as const, symbol: 'rect', symbolSize: [3, 24], silent: true, z: 10,
  itemStyle: { color: palette.target() }, data: points,
});
