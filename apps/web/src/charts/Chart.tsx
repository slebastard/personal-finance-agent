import { useEffect, useRef } from 'react';
import type { EChartsOption } from 'echarts';
import { echarts, registerTheme } from './theme';

/**
 * Thin wrapper around echarts/core — no echarts-for-react dependency.
 * The page remounts when the theme changes (see layout/Shell.tsx), so a chart is always built with
 * the colours of the current mode: dark mode is a real re-theme, not a filter.
 */
export function Chart({ option, height = 260, ariaLabel, onClick }:
  { option: EChartsOption; height?: number; ariaLabel: string; onClick?: (params: any) => void }) {
  const el = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts>();
  const clickRef = useRef(onClick);
  clickRef.current = onClick;

  useEffect(() => {
    if (!el.current) return;
    inst.current = echarts.init(el.current, registerTheme(), { renderer: 'canvas' });
    inst.current.on('click', (p: any) => clickRef.current?.(p));
    const onResize = () => inst.current?.resize();
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      inst.current?.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { inst.current?.setOption(option, true); }, [option]);

  return <div ref={el} style={{ height }} role="img" aria-label={ariaLabel} />;
}
