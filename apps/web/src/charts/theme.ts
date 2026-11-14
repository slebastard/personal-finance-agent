import * as echarts from 'echarts/core';
import { BarChart, LineChart, PieChart, ScatterChart, TreemapChart } from 'echarts/charts';
import {
  GridComponent, TooltipComponent, LegendComponent, DatasetComponent, MarkLineComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

// Tree-shaken on purpose: importing all of echarts costs ~1 MB; this set is ~300-400 kB.
echarts.use([BarChart, LineChart, PieChart, ScatterChart, TreemapChart, GridComponent, TooltipComponent, LegendComponent,
             DatasetComponent, MarkLineComponent, CanvasRenderer]);

const css = (name: string, fallback: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

/**
 * ECharts theme derived from OUR validated palette, not ECharts' defaults.
 *
 * Without this the library's own colours would silently replace a palette that was checked with
 * scripts/validate_palette.js for colour-vision separation and surface contrast, in both modes.
 */
export function registerTheme(): string {
  const name = 'pfa';
  const cats = [1, 2, 3, 4, 5, 6, 7, 8].map((i) => css(`--cat-${i}`, '#2a78d6'));
  const text = css('--text-primary', '#0b0b0b');
  const secondary = css('--text-secondary', '#52514e');
  const muted = css('--muted', '#898781');
  const grid = css('--grid', '#e1e0d9');
  const axis = css('--axis', '#c3c2b7');
  const surface = css('--surface-1', '#fcfcfb');

  echarts.registerTheme(name, {
    color: cats,
    backgroundColor: 'transparent',
    textStyle: { fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif' },
    title: { textStyle: { color: text } },
    // recessive chrome: hairline grid one shade off the surface, never dashed
    categoryAxis: {
      axisLine: { lineStyle: { color: axis } },
      axisTick: { show: false },
      axisLabel: { color: muted },
      splitLine: { show: false },
    },
    valueAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: muted },
      splitLine: { lineStyle: { color: grid, type: 'solid' } },
    },
    legend: { textStyle: { color: secondary }, icon: 'roundRect',
              itemWidth: 10, itemHeight: 10 },
    tooltip: {
      backgroundColor: surface, borderColor: css('--border', 'rgba(0,0,0,.1)'),
      borderWidth: 1, textStyle: { color: text, fontSize: 12 },
      extraCssText: 'box-shadow:0 4px 16px rgba(0,0,0,.12);border-radius:8px;',
    },
  });
  return name;
}

export const palette = {
  cat: (i: number) => css(`--cat-${((i - 1) % 8) + 1}`, '#2a78d6'),
  catInk: (i: number) => css(`--cat-${((i - 1) % 8) + 1}-ink`, '#0b0b0b'),
  /** Ordinal quality ramp, 1 (low) .. 5 (high). */
  quality: (i: number) => css(`--q-${Math.min(Math.max(i, 1), 5)}`, '#2a78d6'),
  qualityInk: (i: number) => css(`--q-ink-${Math.min(Math.max(i, 1), 5)}`, '#ffffff'),
  series1: () => css('--series-1', '#2a78d6'),
  good: () => css('--good', '#006300'),
  bad: () => css('--bad', '#d03b3b'),
  axis: () => css('--axis', '#c3c2b7'),
  grid: () => css('--grid', '#e1e0d9'),
  text: () => css('--text-primary', '#0b0b0b'),
  muted: () => css('--muted', '#898781'),
  surface: () => css('--surface-1', '#fcfcfb'),
  target: () => css('--target', '#0b0b0b'),
};

export { echarts };
